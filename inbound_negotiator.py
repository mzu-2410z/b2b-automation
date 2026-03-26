"""
inbound_negotiator.py
---------------------
1. Connects to your inbox via IMAP and reads unread replies.
2. Matches each reply to a lead in the CRM by email address.
3. Feeds the reply to Groq AI with a strict negotiation system prompt.
4. AI determines outcome: 'not interested' | 'needs follow-up' | 'closed client'
5. Sends a follow-up reply if negotiation is ongoing.
6. Updates CRM status accordingly.

Supported IMAP providers:
  Gmail:   imap.gmail.com  (port 993, SSL) — requires App Password
  Outlook: outlook.office365.com (port 993)
  Yahoo:   imap.mail.yahoo.com (port 993)
"""

import email
import imaplib
import logging
import smtplib
import time
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from groq import Groq

import crm_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [INBOUND] %(message)s")
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# USER CONFIG — paste your credentials here
# ──────────────────────────────────────────────

# Groq API
GROQ_API_KEY  = "gsk_XXXXXXXXXXXXXXXXXXXXXXXX"   # ← same key as outbound_mailer.py
GROQ_MODEL    = "llama3-70b-8192"

# IMAP (Inbound Email — reading replies)
IMAP_HOST     = "imap.gmail.com"                 # ← your IMAP server
IMAP_PORT     = 993                              # ← 993 for SSL
IMAP_USERNAME = "youremail@gmail.com"            # ← inbox to monitor
IMAP_PASSWORD = "your_app_password_here"         # ← App Password (Gmail) or regular password

# SMTP (to send follow-up replies)
SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USERNAME = "youremail@gmail.com"
SMTP_PASSWORD = "your_app_password_here"
SENDER_NAME   = "Alex Morgan"
SENDER_EMAIL  = "youremail@gmail.com"

# Folder to check for replies (Gmail uses "INBOX", some use "[Gmail]/All Mail")
IMAP_FOLDER   = "INBOX"

# ──────────────────────────────────────────────


# ── IMAP: Read Replies ─────────────────────────

def _decode_header_value(value: str) -> str:
    """Decode an encoded email header (handles UTF-8, base64, etc.)."""
    decoded_parts = decode_header(value)
    result = ""
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result += part.decode(charset or "utf-8", errors="replace")
        else:
            result += part
    return result.strip()


def _extract_body(msg) -> str:
    """Extract the plain-text body from an email message object."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition  = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in disposition:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    body = part.get_payload(decode=True).decode(charset, errors="replace")
                    break
                except Exception:
                    pass
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            body = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            pass
    return body.strip()


def fetch_unread_replies() -> list[dict]:
    """
    Connect to IMAP and return a list of unread emails as dicts:
      {from_email, from_name, subject, body, message_id, raw_msg}
    Marks fetched emails as read.
    """
    replies = []

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select(IMAP_FOLDER)

        # Search for UNSEEN (unread) emails
        status, message_ids = mail.search(None, "UNSEEN")
        if status != "OK":
            logger.warning("IMAP search failed.")
            mail.logout()
            return replies

        ids = message_ids[0].split()
        logger.info(f"Found {len(ids)} unread message(s) in {IMAP_FOLDER}.")

        for uid in ids:
            status, msg_data = mail.fetch(uid, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg       = email.message_from_bytes(raw_email)

            from_header = _decode_header_value(msg.get("From", ""))
            subject     = _decode_header_value(msg.get("Subject", ""))
            message_id  = msg.get("Message-ID", "")

            # Extract sender email from "Name <email@domain.com>" format
            from_email = from_header
            if "<" in from_header and ">" in from_header:
                from_email = from_header.split("<")[1].split(">")[0].strip()
                from_name  = from_header.split("<")[0].strip().strip('"')
            else:
                from_name = from_email

            body = _extract_body(msg)

            if not body:
                logger.debug(f"Empty body from {from_email} — skipping.")
                continue

            # Mark as read (SEEN)
            mail.store(uid, "+FLAGS", "\\Seen")

            replies.append({
                "from_email":  from_email,
                "from_name":   from_name,
                "subject":     subject,
                "body":        body[:3000],   # Truncate to avoid huge prompts
                "message_id":  message_id,
            })
            logger.info(f"  Read reply from: {from_email} | Subject: {subject}")

        mail.logout()

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error: {e}")
    except Exception as e:
        logger.error(f"Unexpected IMAP error: {e}")

    return replies


# ── Groq: Analyze Reply + Generate Response ────

# Outcome labels the AI must return
OUTCOME_NOT_INTERESTED = "NOT_INTERESTED"
OUTCOME_FOLLOW_UP      = "FOLLOW_UP"
OUTCOME_CLOSED         = "CLOSED"

NEGOTIATION_SYSTEM_PROMPT = f"""You are a highly skilled B2B sales negotiator AI.
Your job is to read a prospect's email reply to a cold outreach and decide the outcome.

RULES:
1. Analyze the reply carefully for intent.
2. Choose ONE outcome from: {OUTCOME_NOT_INTERESTED} | {OUTCOME_FOLLOW_UP} | {OUTCOME_CLOSED}
3. If outcome is FOLLOW_UP or CLOSED, write a short reply (3–4 sentences max).

Outcome definitions:
  {OUTCOME_NOT_INTERESTED}: Prospect clearly declined, unsubscribed, said "not interested", 
                             or expressed no need. DO NOT follow up.
  {OUTCOME_FOLLOW_UP}:      Prospect asked questions, showed mild interest, said "maybe", 
                             "tell me more", or needs more info. Reply to move them forward.
  {OUTCOME_CLOSED}:         Prospect said YES, agreed to a call, signed up, or wants to proceed.
                             Send a warm confirmation email with next steps.

OUTPUT FORMAT (strictly follow this):
OUTCOME: <one of the three labels>
REPLY:
<your reply email body, or NONE if NOT_INTERESTED>"""


def _analyze_and_negotiate(reply: dict) -> dict:
    """
    Feed the prospect's reply to Groq.
    Returns: {outcome, reply_body}
    """
    client = Groq(api_key=GROQ_API_KEY)

    user_prompt = f"""Prospect's reply:
From: {reply['from_name']} <{reply['from_email']}>
Subject: {reply['subject']}

---
{reply['body']}
---

Analyze this and respond in the required format."""

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": NEGOTIATION_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.6,
        max_tokens=500,
    )

    raw = response.choices[0].message.content.strip()
    logger.debug(f"Groq negotiation response:\n{raw}")

    # Parse outcome and reply body
    outcome    = OUTCOME_NOT_INTERESTED  # default safe
    reply_body = ""

    lines = raw.splitlines()
    reply_lines = []
    in_reply_section = False

    for line in lines:
        if line.upper().startswith("OUTCOME:"):
            extracted = line.split(":", 1)[1].strip().upper()
            if extracted in {OUTCOME_NOT_INTERESTED, OUTCOME_FOLLOW_UP, OUTCOME_CLOSED}:
                outcome = extracted
        elif line.upper().startswith("REPLY:"):
            in_reply_section = True
        elif in_reply_section:
            reply_lines.append(line)

    reply_body = "\n".join(reply_lines).strip()
    if reply_body.upper() == "NONE":
        reply_body = ""

    return {"outcome": outcome, "reply_body": reply_body}


# ── SMTP: Send Follow-up Reply ─────────────────

def _send_reply(to_email: str, to_name: str, subject: str, body: str) -> bool:
    """Send a follow-up reply via SMTP. Returns True on success."""
    # Prefix subject with Re: if not already
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["To"]      = f"{to_name} <{to_email}>"
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())

        logger.info(f"↩  Follow-up sent to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send follow-up to {to_email}: {e}")
        return False


# ── CRM Status Mapping ─────────────────────────

OUTCOME_TO_STATUS = {
    OUTCOME_NOT_INTERESTED: "not interested",
    OUTCOME_FOLLOW_UP:      "unanswered",     # Still in negotiation
    OUTCOME_CLOSED:         "closed client",
}


# ── Main Inbound Loop ──────────────────────────

def run_inbound() -> dict:
    """
    Entry point called by main.py.
    Reads unread replies, negotiates, updates CRM.
    Returns summary dict.
    """
    replies = fetch_unread_replies()

    if not replies:
        logger.info("No unread replies found.")
        return {"processed": 0, "not_interested": 0, "follow_up": 0, "closed": 0}

    counts = {
        "processed":    0,
        "not_interested": 0,
        "follow_up":    0,
        "closed":       0,
    }

    # Get all CRM leads to match replies against
    all_leads = crm_manager.get_all_leads()
    crm_emails = {lead["email"].lower(): lead for lead in all_leads}

    for reply in replies:
        from_email = reply["from_email"].lower()
        logger.info(f"Processing reply from: {from_email}")

        # Check if this sender is in our CRM
        lead = crm_emails.get(from_email)
        if not lead:
            logger.info(f"  Reply from unknown sender (not in CRM): {from_email} — skipping.")
            continue

        # Skip if already closed or not interested
        current_status = lead.get("status", "")
        if current_status in {"not interested", "closed client"}:
            logger.info(f"  Lead already finalized ({current_status}) — skipping.")
            continue

        # ── AI negotiation ─────────────────────
        result     = _analyze_and_negotiate(reply)
        outcome    = result["outcome"]
        reply_body = result["reply_body"]

        logger.info(f"  AI outcome: {outcome}")

        # ── Send follow-up if needed ────────────
        if outcome in {OUTCOME_FOLLOW_UP, OUTCOME_CLOSED} and reply_body:
            _send_reply(
                to_email=reply["from_email"],
                to_name=reply["from_name"],
                subject=reply["subject"],
                body=reply_body,
            )
            time.sleep(2)   # Brief pause between sends

        # ── Update CRM ──────────────────────────
        new_status = OUTCOME_TO_STATUS[outcome]
        crm_manager.update_status(from_email, new_status)

        # ── Update counts ───────────────────────
        counts["processed"] += 1
        if outcome == OUTCOME_NOT_INTERESTED:
            counts["not_interested"] += 1
        elif outcome == OUTCOME_FOLLOW_UP:
            counts["follow_up"] += 1
        elif outcome == OUTCOME_CLOSED:
            counts["closed"] += 1

    logger.info(f"Inbound processing complete: {counts}")
    return counts


# ── Standalone test ────────────────────────────
if __name__ == "__main__":
    sample_reply = {
        "from_email": "john@testbusiness.com",
        "from_name":  "John Smith",
        "subject":    "Re: Quick question",
        "body":       "Hi, this sounds interesting. Can you tell me more about the pricing?",
    }
    result = _analyze_and_negotiate(sample_reply)
    print(f"\nOutcome: {result['outcome']}")
    print(f"\nAI Reply:\n{result['reply_body']}")
