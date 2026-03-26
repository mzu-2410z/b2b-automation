"""
outbound_mailer.py
──────────────────
1. Pulls leads with status='pending' from the CRM.
2. Uses Groq (Llama-3) to generate a personalized 3-sentence cold email.
3. Sends it via SMTP.
4. Updates lead status to 'unanswered'.
5. Sleeps a random 3–8 minutes between sends (anti-spam).

All credentials and settings loaded from config.py → .env.
No secrets in this file.
"""

import logging
import random
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from groq import Groq

import crm_manager
from config import cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [MAILER] %(message)s")
logger = logging.getLogger(__name__)


# ── Groq: Email Generation ────────────────────────────────────────

def _generate_cold_email(lead: dict) -> tuple[str, str]:
    """
    Use Groq to write a personalized 3-sentence cold email.
    Returns (subject_line, email_body).
    """
    client = Groq(api_key=cfg.GROQ_API_KEY)

    business_name = lead.get("business_name", "your company")
    website       = lead.get("website", "")
    email         = lead.get("email", "")

    system_prompt = """You are an expert B2B cold email copywriter.
Your emails are concise (3 sentences MAX), hyper-personalized, and conversational.
You never use buzzwords, corporate speak, or generic phrases.
You always write in plain text — no bullet points, no HTML.
Output format:
Line 1: Subject: <subject line>
Blank line
Lines 3+: <email body, 3 sentences max>"""

    user_prompt = f"""Write a cold email for the following lead:
Business Name: {business_name}
Website: {website}
Email: {email}

Our offer: {cfg.AGENCY_OFFER.format(industry="their")}

Rules:
- Subject line must mention {business_name} specifically
- First sentence: one genuine observation about their business
- Second sentence: the offer, framed as solving a likely pain point
- Third sentence: soft CTA — ask if they're open to a 15-min call this week
- Sign off as: {cfg.SENDER_NAME}
- Tone: friendly peer, not a sales robot"""

    response = client.chat.completions.create(
        model=cfg.GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.85,
        max_tokens=300,
    )

    raw   = response.choices[0].message.content.strip()
    lines = raw.splitlines()

    subject    = "Quick question"
    body_lines = []

    for line in lines:
        if line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
        else:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    return subject, body


# ── SMTP: Send Email ──────────────────────────────────────────────

def _send_email(to_email: str, subject: str, body: str) -> bool:
    """Send a plain-text email via SMTP. Returns True on success."""
    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = f"{cfg.SENDER_NAME} <{cfg.SENDER_EMAIL}>"
        msg["To"]      = to_email
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg.SMTP_USERNAME, cfg.SMTP_PASSWORD)
            server.sendmail(cfg.SENDER_EMAIL, to_email, msg.as_string())

        logger.info(f"✉  Sent to {to_email} | Subject: {subject}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "SMTP authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD in .env. "
            "Gmail users: use an App Password, not your login password."
        )
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending to {to_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending to {to_email}: {e}")
        return False


# ── Main Outbound Loop ────────────────────────────────────────────

def run_outbound() -> dict:
    """
    Entry point called by main.py.
    Processes all 'pending' leads.
    Returns summary: {sent, failed, skipped}
    """
    pending_leads = crm_manager.get_leads_by_status("pending")

    if not pending_leads:
        logger.info("No pending leads to process.")
        return {"sent": 0, "failed": 0, "skipped": 0}

    logger.info(f"Processing {len(pending_leads)} pending lead(s)...")
    sent = failed = skipped = 0

    for i, lead in enumerate(pending_leads):
        email = lead.get("email", "").strip()
        name  = lead.get("business_name", "Unknown")

        if not email:
            logger.warning(f"Skipping lead with no email: {name}")
            skipped += 1
            continue

        logger.info(f"[{i+1}/{len(pending_leads)}] Generating email for: {name} <{email}>")

        try:
            subject, body = _generate_cold_email(lead)
        except Exception as e:
            logger.error(f"Groq API error for {email}: {e}")
            failed += 1
            continue

        success = _send_email(email, subject, body)

        if success:
            crm_manager.update_status(email, "unanswered")
            sent += 1
        else:
            failed += 1
            continue

        # ── Anti-spam delay between sends ─────────────────────
        if i < len(pending_leads) - 1:
            delay   = random.uniform(cfg.SEND_DELAY_MIN_SEC, cfg.SEND_DELAY_MAX_SEC)
            minutes = delay / 60
            logger.info(f"⏳  Sleeping {minutes:.1f} min before next send...")
            time.sleep(delay)

    summary = {"sent": sent, "failed": failed, "skipped": skipped}
    logger.info(f"Outbound complete: {summary}")
    return summary


if __name__ == "__main__":
    # Test email generation only (no actual send or CRM update)
    test_lead = {
        "business_name": "Apex Digital Solutions",
        "website":       "https://apexdigital.example.com",
        "email":         "test@example.com",
    }
    subject, body = _generate_cold_email(test_lead)
    print(f"\nSubject: {subject}\n\n{body}\n")
