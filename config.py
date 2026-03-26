"""
config.py
─────────
Single source of truth for ALL configuration.

How it works:
  1. Loads every value from the .env file via python-dotenv.
  2. Validates that required secrets are present — fails loudly on startup
     if anything critical is missing, so you catch errors before sending emails.
  3. Exposes typed constants that every other module imports.

Usage in any module:
  from config import cfg
  print(cfg.GROQ_API_KEY)

NEVER hardcode secrets in any other file. All changes go in .env only.
"""

import os
import sys
import logging
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── Load .env file ──────────────────────────────────────────────
# Looks for .env in the same directory as this file (project root).
_ENV_PATH = Path(__file__).parent / ".env"

if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)
    logger.debug(f"Loaded environment from {_ENV_PATH}")
else:
    # Fallback: check current working directory
    load_dotenv()
    logger.warning(
        ".env file not found at project root. "
        "Falling back to system environment variables. "
        "Run: cp .env.example .env  and fill in your values."
    )


# ── Helper ──────────────────────────────────────────────────────

def _require(key: str) -> str:
    """
    Get an env var by name. Raises a clear RuntimeError if missing or empty.
    This is called at import time — missing secrets crash fast at startup.
    """
    value = os.getenv(key, "").strip()
    if not value:
        raise RuntimeError(
            f"\n\n❌  Missing required config: '{key}'\n"
            f"    Open your .env file and set:  {key}=your_value_here\n"
            f"    (Copy .env.example → .env if you haven't already)\n"
        )
    return value


def _optional(key: str, default: str = "") -> str:
    """Get an optional env var, returning default if not set."""
    return os.getenv(key, default).strip()


def _optional_int(key: str, default: int) -> int:
    """Get an optional integer env var."""
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"Config '{key}' is not a valid integer ('{raw}'). Using default: {default}")
        return default


# ── Config Dataclass ────────────────────────────────────────────

@dataclass(frozen=True)   # frozen=True → immutable after creation (safer)
class Config:
    """
    All application configuration, loaded from .env.
    Access via the module-level singleton: `from config import cfg`
    """

    # ── Groq AI ────────────────────────────────────────────────
    GROQ_API_KEY:  str
    GROQ_MODEL:    str

    # ── Google Sheets CRM ──────────────────────────────────────
    GOOGLE_SERVICE_ACCOUNT_FILE: str
    GOOGLE_SPREADSHEET_NAME:     str
    GOOGLE_WORKSHEET_NAME:       str

    # ── SMTP (Outbound) ────────────────────────────────────────
    SMTP_HOST:     str
    SMTP_PORT:     int
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    SENDER_NAME:   str
    SENDER_EMAIL:  str

    # ── IMAP (Inbound) ─────────────────────────────────────────
    IMAP_HOST:     str
    IMAP_PORT:     int
    IMAP_USERNAME: str
    IMAP_PASSWORD: str
    IMAP_FOLDER:   str

    # ── Scraper ────────────────────────────────────────────────
    SCRAPER_TARGET_INDUSTRY: str
    SCRAPER_TARGET_LOCATION: str
    SCRAPER_MAX_LEADS:       int

    # ── Agency Identity ────────────────────────────────────────
    AGENCY_OFFER: str

    # ── Timing & Throttling ────────────────────────────────────
    SEND_DELAY_MIN_SEC: int
    SEND_DELAY_MAX_SEC: int
    LOOP_INTERVAL_SEC:  int

    # ── Derived / computed properties ──────────────────────────
    @property
    def google_service_account_path(self) -> Path:
        """Resolve the service account file to an absolute Path."""
        p = Path(self.GOOGLE_SERVICE_ACCOUNT_FILE)
        if not p.is_absolute():
            p = Path(__file__).parent / p
        return p

    def validate(self) -> None:
        """
        Run post-load sanity checks. Called once at startup.
        Raises ValueError with a clear message if anything looks wrong.
        """
        errors = []

        # Groq key format check (Groq keys start with "gsk_")
        if not self.GROQ_API_KEY.startswith("gsk_"):
            errors.append(
                "GROQ_API_KEY doesn't look valid (should start with 'gsk_'). "
                "Get yours at https://console.groq.com"
            )

        # Service account file existence check
        if not self.google_service_account_path.exists():
            errors.append(
                f"GOOGLE_SERVICE_ACCOUNT_FILE not found: '{self.google_service_account_path}'\n"
                "  Download it from GCP → IAM → Service Accounts → Keys."
            )

        # Port range checks
        if not (1 <= self.SMTP_PORT <= 65535):
            errors.append(f"SMTP_PORT must be 1–65535 (got {self.SMTP_PORT})")
        if not (1 <= self.IMAP_PORT <= 65535):
            errors.append(f"IMAP_PORT must be 1–65535 (got {self.IMAP_PORT})")

        # Delay sanity check
        if self.SEND_DELAY_MIN_SEC >= self.SEND_DELAY_MAX_SEC:
            errors.append(
                f"SEND_DELAY_MIN_SEC ({self.SEND_DELAY_MIN_SEC}) must be "
                f"less than SEND_DELAY_MAX_SEC ({self.SEND_DELAY_MAX_SEC})"
            )

        # Email format (basic)
        for label, addr in [("SENDER_EMAIL", self.SENDER_EMAIL), ("SMTP_USERNAME", self.SMTP_USERNAME)]:
            if "@" not in addr:
                errors.append(f"{label} doesn't look like a valid email: '{addr}'")

        if errors:
            msg = "\n\n❌  Config validation failed:\n" + "\n".join(f"  • {e}" for e in errors)
            raise ValueError(msg)

        logger.info("✅  Config validated successfully.")

    def redacted_summary(self) -> str:
        """Return a safe summary (secrets redacted) for logging."""
        def redact(s: str) -> str:
            if len(s) <= 8:
                return "***"
            return s[:4] + "*" * (len(s) - 8) + s[-4:]

        return (
            f"\n── Config Summary ───────────────────────────────\n"
            f"  Groq model:       {self.GROQ_MODEL}\n"
            f"  Groq API key:     {redact(self.GROQ_API_KEY)}\n"
            f"  Google sheet:     '{self.GOOGLE_SPREADSHEET_NAME}' / '{self.GOOGLE_WORKSHEET_NAME}'\n"
            f"  Credentials file: {self.google_service_account_path}\n"
            f"  SMTP:             {self.SENDER_NAME} <{self.SENDER_EMAIL}> via {self.SMTP_HOST}:{self.SMTP_PORT}\n"
            f"  IMAP:             {self.IMAP_USERNAME} @ {self.IMAP_HOST}:{self.IMAP_PORT}/{self.IMAP_FOLDER}\n"
            f"  Scraper niche:    '{self.SCRAPER_TARGET_INDUSTRY}' in '{self.SCRAPER_TARGET_LOCATION}' (max {self.SCRAPER_MAX_LEADS})\n"
            f"  Send delay:       {self.SEND_DELAY_MIN_SEC}–{self.SEND_DELAY_MAX_SEC}s\n"
            f"  Loop interval:    {self.LOOP_INTERVAL_SEC}s\n"
            f"────────────────────────────────────────────────"
        )


# ── Build the singleton ─────────────────────────────────────────
# This runs once at import time. Any missing required variable
# raises RuntimeError immediately — no silent failures.

try:
    cfg = Config(
        # ── Groq ──────────────────────────────────────────────
        GROQ_API_KEY   = _require("GROQ_API_KEY"),
        GROQ_MODEL     = _optional("GROQ_MODEL", "llama3-70b-8192"),

        # ── Google Sheets ──────────────────────────────────────
        GOOGLE_SERVICE_ACCOUNT_FILE = _optional("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json"),
        GOOGLE_SPREADSHEET_NAME     = _require("GOOGLE_SPREADSHEET_NAME"),
        GOOGLE_WORKSHEET_NAME       = _optional("GOOGLE_WORKSHEET_NAME", "Leads"),

        # ── SMTP ───────────────────────────────────────────────
        SMTP_HOST     = _require("SMTP_HOST"),
        SMTP_PORT     = _optional_int("SMTP_PORT", 587),
        SMTP_USERNAME = _require("SMTP_USERNAME"),
        SMTP_PASSWORD = _require("SMTP_PASSWORD"),
        SENDER_NAME   = _optional("SENDER_NAME", "Alex Morgan"),
        SENDER_EMAIL  = _require("SENDER_EMAIL"),

        # ── IMAP ───────────────────────────────────────────────
        IMAP_HOST     = _require("IMAP_HOST"),
        IMAP_PORT     = _optional_int("IMAP_PORT", 993),
        IMAP_USERNAME = _require("IMAP_USERNAME"),
        IMAP_PASSWORD = _require("IMAP_PASSWORD"),
        IMAP_FOLDER   = _optional("IMAP_FOLDER", "INBOX"),

        # ── Scraper ────────────────────────────────────────────
        SCRAPER_TARGET_INDUSTRY = _require("SCRAPER_TARGET_INDUSTRY"),
        SCRAPER_TARGET_LOCATION = _require("SCRAPER_TARGET_LOCATION"),
        SCRAPER_MAX_LEADS       = _optional_int("SCRAPER_MAX_LEADS", 50),

        # ── Agency identity ────────────────────────────────────
        AGENCY_OFFER = _optional(
            "AGENCY_OFFER",
            "We help {industry} businesses generate 3-5 qualified leads per week "
            "using done-for-you LinkedIn outreach — no retainer, pay-per-result only."
        ),

        # ── Timing ─────────────────────────────────────────────
        SEND_DELAY_MIN_SEC = _optional_int("SEND_DELAY_MIN_SEC", 180),
        SEND_DELAY_MAX_SEC = _optional_int("SEND_DELAY_MAX_SEC", 480),
        LOOP_INTERVAL_SEC  = _optional_int("LOOP_INTERVAL_SEC", 3600),
    )

except RuntimeError as e:
    # Print the friendly error and exit — don't let the app start half-configured
    print(e, file=sys.stderr)
    sys.exit(1)


# ── Standalone test ─────────────────────────────────────────────
if __name__ == "__main__":
    print(cfg.redacted_summary())
    try:
        cfg.validate()
    except ValueError as e:
        print(e)
