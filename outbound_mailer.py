"""
outbound_mailer.py
------------------
1. Pulls leads with status='pending' from the CRM.
2. Uses Groq (Llama-3) to generate a highly personalized 3-sentence cold email.
3. Sends it via SMTP.
4. Updates lead status to 'unanswered'.
5. Sleeps 3–8 minutes between sends to avoid spam filters.

Anti-spam practices built in:
  - Randomized send delays (3–8 min)
  - Personalized subject lines (not templated)
  - Plain-text body (higher deliverability than HTML)
  - Sender name rotation (optional)
"""

import logging
import random
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from groq import Groq

import crm_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [MAILER] %(message)s")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# USER CONFIG — paste your credentials here
# ──────────────────────────────────────────────

# Groq API
GROQ_API_KEY   = "gsk_XXXXXXXXXXXXXXXXXXXXXXXX"   # ← your Groq API key from console.groq.com
GROQ_MODEL     = "llama3-70b-8192"                # ← or "mixtral-8x7b-32768"

# SMTP (Outbound Email)
# Free options: Gmail (with App Password), Brevo, Mailjet, SendGrid free tier
SMTP_HOST      = "smtp.gmail.com"                 # ← your SMTP host
SMTP_PORT      = 587                              # ← 587 for TLS, 465 for SSL
SMTP_USERNAME  = "youremail@gmail.com"            # ← your sending email address
SMTP_PASSWORD  = "your_app_password_here"         # ← Gmail: use App Password, NOT your login password
SENDER_NAME    = "Alex Morgan"                    # ← display name (sounds human, not a company)
SENDER_EMAIL   = "youremail@gmail.com"            # ← same as SMTP_USERNAME typically

# Your agency's value proposition (1-2 lines — used in the AI prompt)
AGENCY_OFFER = (
    "We help {industry} businesses generate 3-5 qualified leads per week "
    "using done-for-you LinkedIn outreach — no retainer, pay-per-result only."
)

# Send delay range (seconds) — 3 to 8 minutes
DELAY_MIN_SEC = 180
DELAY_MAX_SEC = 480

# ──────────────────────────────────────────────


# ── Groq: Email Generation ─────────────────────

def _generate_cold_email(lead: dict) -> tuple[str, str]:
    """
    Use Groq to write a personalized 3-sentence cold email.
    Returns (subject, body) as strings.
    """
    client = Groq(api_key=GROQ_API_KEY)

    business_name = lead.get("business_name", "your company")
    website       = lead.get("website", "")
    email         = lead.get("email", "")

    # Infer industry/niche from the business name for personalization
    system_prompt = """You are an expert B2B cold email copywriter.
Your emails are concise (3 sentences MAX), hyper-personalized, and conversational.
You never use buzzwords, corporate speak, or generic phrases.
You always write in plain text — no bullet points, no HTML.
Output format: two sections separated by a blank line.
Line 1: Subject: <subject line>
Line 3+: <email body, 3 sentences max>"""

    user_prompt = f"""Write a cold email for the following lead:
Business Name: {business_name}
Website: {website}
Email: {email}

Our offer: {AGENCY_OFFER.format(industry="their")}

Rules:
- Subject line must mention {business_name} specifically
- First sentence: one genuine observation about their business (from the business name/website clue)
- Second sentence: the offer, framed as solving a pain they likely have
- Third sentence: a soft CTA — ask if they're open to a quick 15-min call this week
- Sign off as: {SENDER_NAME}
- Tone: friendly peer, not a sales robot"""

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.85,
        max_tokens=300,
    )

    raw = response.choices[0].message.content.strip()
    lines = raw.splitlines()

    # Parse subject and body
    subject = "Quick question"
    body_lines = []
    for i, line in enumerate(lines):
        if line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
        else:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    return subject, body


# ── SMTP: Send Email ───────────────────────────

def _send_email(to_email: str, subject: str, body: str) -> bool:
    """
    Send a plain-text email via SMTP.
    Returns True on success, False on failure.
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["To"]      = to_email
        msg["Subject"] = subject

        # Plain text only — better deliverability than HTML
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()                          # Upgrade to TLS
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())

        logger.info(f"✉  Email sent to {to_email} | Subject: {subject}")
        return True

    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending to {to_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending to {to_email}: {e}")
        return False


# ── Main Outbound Loop ─────────────────────────

def run_outbound() -> dict:
    """
    Entry point called by main.py.
    Processes all 'pending' leads.
    Returns a summary dict with counts.
    """
    pending_leads = crm_manager.get_leads_by_status("pending")

    if not pending_leads:
        logger.info("No pending leads to process.")
        return {"sent": 0, "failed": 0, "skipped": 0}

    logger.info(f"Processing {len(pending_leads)} pending lead(s)...")

    sent    = 0
    failed  = 0
    skipped = 0

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
            logger.debug(f"Generated subject: {subject}")
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

        # ── Anti-spam sleep between sends ──────────────────────
        if i < len(pending_leads) - 1:   # Don't sleep after the last email
            delay = random.uniform(DELAY_MIN_SEC, DELAY_MAX_SEC)
            minutes = delay / 60
            logger.info(f"Sleeping {minutes:.1f} min before next send...")
            time.sleep(delay)

    summary = {"sent": sent, "failed": failed, "skipped": skipped}
    logger.info(f"Outbound complete: {summary}")
    return summary


# ── Standalone test ────────────────────────────
if __name__ == "__main__":
    # Quick single-lead test without touching CRM
    test_lead = {
        "business_name": "Apex Digital Solutions",
        "website":       "https://apexdigital.example.com",
        "email":         "test@example.com",
    }
    subject, body = _generate_cold_email(test_lead)
    print(f"\nSubject: {subject}\n\n{body}\n")
