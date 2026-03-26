"""
crm_manager.py
--------------
All interactions with the Google Sheets CRM.

Sheet columns (A–F):
  A: business_name
  B: website
  C: email
  D: status          ← one of: pending | unanswered | not interested | closed client
  E: date_added
  F: last_updated

Setup:
  1. Create a Google Cloud project.
  2. Enable Google Sheets API + Google Drive API.
  3. Create a Service Account and download credentials JSON.
  4. Share your target Google Sheet with the service account email.
"""

import logging
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(level=logging.INFO, format="%(asctime)s [CRM] %(message)s")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# USER CONFIG — paste your values here
# ──────────────────────────────────────────────
SERVICE_ACCOUNT_FILE = "credentials.json"        # ← path to your downloaded GCP service account JSON
SPREADSHEET_NAME     = "B2B Agency CRM"          # ← exact name of your Google Sheet
WORKSHEET_NAME       = "Leads"                   # ← tab name inside the sheet
# ──────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

VALID_STATUSES = {"pending", "unanswered", "not interested", "closed client"}

# Column index mapping (1-based for gspread)
COL = {
    "business_name": 1,
    "website":       2,
    "email":         3,
    "status":        4,
    "date_added":    5,
    "last_updated":  6,
}

HEADER_ROW = ["business_name", "website", "email", "status", "date_added", "last_updated"]


# ── Connection ─────────────────────────────────

def _get_worksheet() -> gspread.Worksheet:
    """Authenticate and return the target worksheet object."""
    creds  = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet  = client.open(SPREADSHEET_NAME)

    # Create worksheet if it doesn't exist yet
    try:
        ws = sheet.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=WORKSHEET_NAME, rows="1000", cols="10")
        ws.append_row(HEADER_ROW)
        logger.info(f"Created worksheet '{WORKSHEET_NAME}' with headers.")

    # Ensure header row exists
    first_row = ws.row_values(1)
    if first_row != HEADER_ROW:
        ws.insert_row(HEADER_ROW, 1)
        logger.info("Header row inserted.")

    return ws


# ── Read ───────────────────────────────────────

def get_all_leads() -> list[dict]:
    """Return all rows from the sheet as a list of dicts."""
    ws      = _get_worksheet()
    records = ws.get_all_records()   # Uses row 1 as header automatically
    logger.info(f"Fetched {len(records)} total leads from CRM.")
    return records


def get_leads_by_status(status: str) -> list[dict]:
    """Return only rows where the 'status' column matches the given value."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {VALID_STATUSES}")

    all_leads = get_all_leads()
    filtered  = [lead for lead in all_leads if lead.get("status") == status]
    logger.info(f"Found {len(filtered)} leads with status='{status}'.")
    return filtered


def find_row_by_email(email: str) -> int | None:
    """
    Return the 1-based row number for the given email, or None if not found.
    We search column C (email).
    """
    ws       = _get_worksheet()
    emails   = ws.col_values(COL["email"])   # ['email', 'alice@co.com', ...]
    try:
        idx = emails.index(email)            # 0-based
        return idx + 1                       # convert to 1-based row
    except ValueError:
        return None


# ── Write ──────────────────────────────────────

def add_leads(leads: list[dict]) -> int:
    """
    Append new leads to the sheet. Skips leads whose email already exists.
    Returns the count of actually-added rows.
    """
    ws             = _get_worksheet()
    existing_emails = set(ws.col_values(COL["email"])[1:])  # Skip header
    now            = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    added          = 0

    rows_to_append = []
    for lead in leads:
        email = lead.get("email", "").strip()
        if not email or email in existing_emails:
            logger.debug(f"Skipping duplicate or empty email: {email}")
            continue

        row = [
            lead.get("business_name", ""),
            lead.get("website", ""),
            email,
            lead.get("status", "pending"),
            now,   # date_added
            now,   # last_updated
        ]
        rows_to_append.append(row)
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
    Update the 'status' and 'last_updated' columns for a lead identified by email.
    Returns True on success, False if email not found.

    Status values:
      pending        → scraped, email not sent yet
      unanswered     → initial email sent, no reply yet
      not interested → AI determined they rejected the offer
      closed client  → AI successfully negotiated the deal
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
    """
    Batch update statuses for multiple leads.
    email_status_pairs: list of (email, new_status) tuples.
    """
    for email, status in email_status_pairs:
        update_status(email, status)


# ── Stats / Reporting ──────────────────────────

def print_crm_summary() -> None:
    """Print a quick summary of lead counts by status."""
    leads = get_all_leads()
    counts: dict[str, int] = {}
    for lead in leads:
        s = lead.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1

    print("\n── CRM Summary ─────────────────────")
    for status, count in sorted(counts.items()):
        print(f"  {status:<20} {count}")
    print(f"  {'TOTAL':<20} {len(leads)}")
    print("────────────────────────────────────\n")


# ── Standalone test ────────────────────────────
if __name__ == "__main__":
    print_crm_summary()
