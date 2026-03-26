"""
crm_manager.py
──────────────
All interactions with the Google Sheets CRM.
Google credentials and sheet names are loaded from config.py → .env.

Sheet columns (A–F):
  A: business_name
  B: website
  C: email
  D: status          ← pending | unanswered | not interested | closed client
  E: date_added
  F: last_updated
"""

import logging
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from config import cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [CRM] %(message)s")
logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

VALID_STATUSES = {"pending", "unanswered", "not interested", "closed client"}

COL = {
    "business_name": 1,
    "website":       2,
    "email":         3,
    "status":        4,
    "date_added":    5,
    "last_updated":  6,
}

HEADER_ROW = ["business_name", "website", "email", "status", "date_added", "last_updated"]


# ── Connection ───────────────────────────────────────────────────

def _get_worksheet() -> gspread.Worksheet:
    """Authenticate using service account from cfg and return the target worksheet."""
    creds_path = cfg.google_service_account_path   # resolved absolute Path

    if not creds_path.exists():
        raise FileNotFoundError(
            f"Google service account file not found: {creds_path}\n"
            "Set GOOGLE_SERVICE_ACCOUNT_FILE in your .env file."
        )

    creds  = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet  = client.open(cfg.GOOGLE_SPREADSHEET_NAME)

    try:
        ws = sheet.worksheet(cfg.GOOGLE_WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=cfg.GOOGLE_WORKSHEET_NAME, rows="1000", cols="10")
        ws.append_row(HEADER_ROW)
        logger.info(f"Created worksheet '{cfg.GOOGLE_WORKSHEET_NAME}' with headers.")

    # Ensure headers exist
    if ws.row_values(1) != HEADER_ROW:
        ws.insert_row(HEADER_ROW, 1)
        logger.info("Header row inserted.")

    return ws


# ── Read ─────────────────────────────────────────────────────────

def get_all_leads() -> list[dict]:
    ws      = _get_worksheet()
    records = ws.get_all_records()
    logger.info(f"Fetched {len(records)} total leads from CRM.")
    return records


def get_leads_by_status(status: str) -> list[dict]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {VALID_STATUSES}")
    all_leads = get_all_leads()
    filtered  = [lead for lead in all_leads if lead.get("status") == status]
    logger.info(f"Found {len(filtered)} leads with status='{status}'.")
    return filtered


def find_row_by_email(email: str) -> int | None:
    ws     = _get_worksheet()
    emails = ws.col_values(COL["email"])
    try:
        return emails.index(email) + 1   # 1-based
    except ValueError:
        return None


# ── Write ─────────────────────────────────────────────────────────

def add_leads(leads: list[dict]) -> int:
    ws              = _get_worksheet()
    existing_emails = set(ws.col_values(COL["email"])[1:])
    now             = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    rows_to_append  = []
    added           = 0

    for lead in leads:
        email = lead.get("email", "").strip()
        if not email or email in existing_emails:
            continue
        rows_to_append.append([
            lead.get("business_name", ""),
            lead.get("website", ""),
            email,
            lead.get("status", "pending"),
            now,
            now,
        ])
        existing_emails.add(email)
        added += 1

    if rows_to_append:
        ws.append_rows(rows_to_append, value_input_option="RAW")
        logger.info(f"Added {added} new lead(s) to CRM.")
    else:
        logger.info("No new leads to add (all duplicates).")

    return added


def update_status(email: str, new_status: str) -> bool:
    """
    Update status for a lead by email.

    Valid statuses:
      pending        → scraped, not emailed yet
      unanswered     → email sent, no reply
      not interested → AI determined rejection
      closed client  → deal closed by AI negotiation
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{new_status}'. Must be one of: {VALID_STATUSES}")

    row = find_row_by_email(email)
    if row is None:
        logger.warning(f"Email not found in CRM: {email}")
        return False

    ws  = _get_worksheet()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    ws.update_cell(row, COL["status"],       new_status)
    ws.update_cell(row, COL["last_updated"], now)
    logger.info(f"Updated '{email}' → status='{new_status}'")
    return True


def bulk_update_status(email_status_pairs: list[tuple[str, str]]) -> None:
    for email, status in email_status_pairs:
        update_status(email, status)


# ── Reporting ─────────────────────────────────────────────────────

def print_crm_summary() -> None:
    leads  = get_all_leads()
    counts: dict[str, int] = {}
    for lead in leads:
        s = lead.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1

    print("\n── CRM Summary ─────────────────────")
    for status, count in sorted(counts.items()):
        print(f"  {status:<22} {count}")
    print(f"  {'TOTAL':<22} {len(leads)}")
    print("────────────────────────────────────\n")


if __name__ == "__main__":
    print_crm_summary()
