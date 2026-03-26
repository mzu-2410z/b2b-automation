"""
inbound_negotiator.py
─────────────────────
1. Connects to your inbox via IMAP and reads unread replies.
2. Matches each reply to a CRM lead by sender email address.
3. Feeds the reply to Groq AI with a strict negotiation system prompt.
4. AI decides: NOT_INTERESTED | FOLLOW_UP | CLOSED
5. Sends follow-up reply if negotiation is ongoing.
6. Updates CRM status accordingly.

All credentials and settings loaded from config.py → .env.
No secrets in this file.
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
from config import cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [INBOUND] %(message)s")
logger = logging.getLogger(__name__)


# ── Outcome labels ────────────────────────────────────────────────
OUTCOME_NOT_INTERESTED = "NOT_INTERESTED"
OUTCOME_FOLLOW_UP      = "FOLLOW_UP"
OUTCOME_CLOSED         = "CLOSED"

OUTCOME_TO_STATUS = {
    OUTCOME_NOT_INTERESTED: "not interested",
    OUTCOME_FOLLOW_UP:      "unanswered",      # Still negotiating
    OUTCOME_CLOSED:         "closed client",
}

NEGOTIATION_SYSTEM_PROMPT = f"""You are a highly skilled B2B sales negotiator AI.
Your job is to read a prospect's reply and decide the outcome.

RULES:
1. Analyze the reply carefully for intent.
2. Choose ONE outcome from: {OUTCOME_NOT_INTERESTED} | {OUTCOME_FOLLOW_UP} | {OUTCOME_CLOSED}
3. If outcome is FOLLOW_UP or CLOSED, write a short reply (3–4 sentences max).

Outcome definitions:
  {OUTCOME_NOT_INTERESTED}: Prospect clearly declined, said "not interested", or unsubscribed. Do NOT reply.
  {OUTCOME_FOLLOW_UP}:      Prospect asked questions, said "maybe", or needs more info. Reply to move them forward.
  {OUTCOME_CLOSED}:         Prospect said YES, agreed to a call, or wants to proceed. Send warm confirmation.

OUTPUT FORMAT (strictly follow this):
OUTCOME: <label>
REPLY:
<reply email body, or NONE if NOT_INTERESTED>"""


# ── IMAP: Read Replies ────────────────────────────────────────────

def _decode_header_value(value: str) -> str:
    parts = decode_header(value)
    result = ""
    for part, charset in parts:
        if isinstance(part, bytes):
            result += part.decode(charset or "utf-8", errors="replace")
        else:
            result += part
    return result.strip()


def _extract_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    charset = part.get_content_charset() or "utf-8"
                    body    = part.get_payload(decode=True).decode(charset, errors="replace")
                    break
                except Exception:
                    pass
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            body    = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            pass
    return body.strip()


def fetch_unread_replies() -> list[dict]:
    """
    Connect to IMAP (credentials from cfg), return unread emails as dicts.
    Marks each fetched email as read.
    """
    replies = []

    try:
        mail = imaplib.IMAP4_SSL(cfg.IMAP_HOST, cfg.IMAP_PORT)
        mail.login(cfg.IMAP_USERNAME, cfg.IMAP_PASSWORD)
        mail.select(cfg.IMAP_FOLDER)

        status, message_ids = mail.search(None, "UNSEEN")
        if status != "OK":
            logger.warning("IMAP search failed.")
            mail.logout()
            return replies

        ids = message_ids[0].split()
        logger.info(f"Found {len(ids)} unread message(s) in {cfg.IMAP_FOLDER}.")

        for uid in ids:
            status, msg_data = mail.fetch(uid, "(RFC822)")
            if status != "OK":
                continue

            msg          = email.message_from_bytes(msg_data[0][1])
            from_header  = _decode_header_value(msg.get("From", ""))
            subject      = _decode_header_value(msg.get("Subject", ""))

            if "<" in from_header and ">" in from_header:
                from_email = from_header.split("<")[1].split(">")[0].strip()
                from_name  = from_header.split("<")[0].strip().strip('"')
            else:
                from_email = from_header
                from_name  = from_header

            body = _extract_body(msg)
            if not body:
                continue

            mail.store(uid, "+FLAGS", "\\Seen")

            replies.append({
                "from_email": from_email,
                "from_name":  from_name,
                "subject":    subject,
                "body":       body[:3000],
            })
            logger.info(f"  Read reply from: {from_email} | {subject}")

        mail.logout()

    except imaplib.IMAP4.error as e:
        logger.error(
            f"IMAP error: {e}. "
            "Check IMAP_HOST, IMAP_USERNAME, IMAP_PASSWORD in .env. "
            "Gmail: ensure IMAP is enabled and you're using an App Password."
        )
    except Exception as e:
        logger.error(f"Unexpected IMAP error: {e}")

    return replies


# ── Groq: Analyze + Negotiate ──────────────────────────────────────

def _analyze_and_negotiate(reply: dict) -> dict:
    """Feed reply to Groq. Returns {outcome, reply_body}."""
    client = Groq(api_key=cfg.GROQ_API_KEY)

    user_prompt = f"""Prospect's reply:
From: {reply['from_name']} <{reply['from_email']}>
Subject: {reply['subject']}

---
{reply['body']}
---

Analyze this reply and respond strictly in the required format."""

    response = client.chat.completions.create(
        model=cfg.GROQ_MODEL,
        messages=[
            {"role": "system", "content": NEGOTIATION_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.6,
        max_tokens=500,
    )

    raw              = response.choices[0].message.content.strip()
    outcome          = OUTCOME_NOT_INTERESTED  # safe default
    reply_lines      = []
    in_reply_section = False

    for line in raw.splitlines():
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


# ── SMTP: Send Follow-up ──────────────────────────────────────────

def _send_reply(to_email: str, to_name: str, subject: str, body: str) -> bool:
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = f"{cfg.SENDER_NAME} <{cfg.SENDER_EMAIL}>"
        msg["To"]      = f"{to_name} <{to_email}>"
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg.SMTP_USERNAME, cfg.SMTP_PASSWORD)
            server.sendmail(cfg.SENDER_EMAIL, to_email, msg.as_string())

        logger.info(f"↩  Follow-up sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send follow-up to {to_email}: {e}")
        return False


# ── Main Inbound Loop ─────────────────────────────────────────────

def run_inbound() -> dict:
    """Entry point called by main.py."""
    replies = fetch_unread_replies()

    if not replies:
        logger.info("No unread replies found.")
        return {"processed": 0, "not_interested": 0, "follow_up": 0, "closed": 0}

    counts      = {"processed": 0, "not_interested": 0, "follow_up": 0, "closed": 0}
    all_leads   = crm_manager.get_all_leads()
    crm_emails  = {lead["email"].lower(): lead for lead in all_leads}

    for reply in replies:
        from_email = reply["from_email"].lower()
        logger.info(f"Processing reply from: {from_email}")

        lead = crm_emails.get(from_email)
        if not lead:
            logger.info(f"  Sender not in CRM: {from_email} — skipping.")
            continue

        if lead.get("status") in {"not interested", "closed client"}:
            logger.info(f"  Lead already finalized — skipping.")
            continue

        result     = _analyze_and_negotiate(reply)
        outcome    = result["outcome"]
        reply_body = result["reply_body"]

        logger.info(f"  AI outcome: {outcome}")

        if outcome in {OUTCOME_FOLLOW_UP, OUTCOME_CLOSED} and reply_body:
            _send_reply(reply["from_email"], reply["from_name"], reply["subject"], reply_body)
            time.sleep(2)

        crm_manager.update_status(from_email, OUTCOME_TO_STATUS[outcome])
        counts["processed"] += 1

        if outcome == OUTCOME_NOT_INTERESTED:
            counts["not_interested"] += 1
        elif outcome == OUTCOME_FOLLOW_UP:
            counts["follow_up"] += 1
        elif outcome == OUTCOME_CLOSED:
            counts["closed"] += 1

    logger.info(f"Inbound complete: {counts}")
    return counts


if __name__ == "__main__":
    # Test negotiation logic with a sample reply (no IMAP needed)
    sample = {
        "from_email": "john@testbusiness.com",
        "from_name":  "John Smith",
        "subject":    "Re: Quick question",
        "body":       "Hi, this sounds interesting. Can you tell me more about the pricing?",
    }
    result = _analyze_and_negotiate(sample)
    print(f"\nOutcome: {result['outcome']}")
    print(f"\nAI Reply:\n{result['reply_body']}")
