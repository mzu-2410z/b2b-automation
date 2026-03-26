# 🤖 Autonomous B2B Arbitrage Agency — Setup Guide

## Project Structure
```
b2b_agency/
├── main.py                  ← Orchestrator (run this)
├── scraper.py               ← Lead scraper
├── crm_manager.py           ← Google Sheets CRM
├── outbound_mailer.py       ← Cold email sender (Groq + SMTP)
├── inbound_negotiator.py    ← Reply reader & AI negotiator
├── requirements.txt         ← Python dependencies
├── credentials.json         ← ⚠️ YOUR Google service account key (add manually)
└── agency.log               ← Auto-generated run log
```

---

## Step 1 — Python Environment

```bash
# Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# Install all dependencies
pip install -r requirements.txt
```

---

## Step 2 — Groq API Key

1. Go to https://console.groq.com
2. Sign up for a free account
3. Generate an API key
4. Paste it in BOTH files:
   - `outbound_mailer.py`   → `GROQ_API_KEY = "gsk_..."`
   - `inbound_negotiator.py` → `GROQ_API_KEY = "gsk_..."`

---

## Step 3 — Google Sheets CRM Setup

### 3a. Create the Google Sheet
1. Go to https://sheets.google.com
2. Create a new sheet named exactly: **B2B Agency CRM**
3. Inside it, create a tab named: **Leads**
4. The script will auto-add headers on first run.

### 3b. Create a Google Cloud Service Account
1. Go to https://console.cloud.google.com
2. Create a new project (e.g., "b2b-agency")
3. Enable APIs:
   - **Google Sheets API**
   - **Google Drive API**
4. Go to IAM & Admin → Service Accounts → Create Service Account
5. Name it anything (e.g., "b2b-crm-bot")
6. Click the service account → Keys tab → Add Key → JSON
7. Download the JSON file
8. Rename it to `credentials.json` and place it in the project folder

### 3c. Share the Sheet with the Service Account
1. Open `credentials.json` — find the `client_email` field (looks like `b2b-crm-bot@yourproject.iam.gserviceaccount.com`)
2. Open your Google Sheet → Share → paste that email → Editor access

### 3d. Update crm_manager.py
```python
SERVICE_ACCOUNT_FILE = "credentials.json"   # ← already set
SPREADSHEET_NAME     = "B2B Agency CRM"     # ← must match exactly
WORKSHEET_NAME       = "Leads"              # ← must match exactly
```

---

## Step 4 — Gmail SMTP + IMAP (Free Sending)

Gmail is the easiest free SMTP/IMAP option. You MUST use an **App Password** (not your login password).

### Enable App Passwords:
1. Go to your Google Account → Security
2. Enable **2-Step Verification** (required)
3. Go to Security → **App Passwords**
4. Select app: "Mail", device: "Other" → name it "B2B Agency"
5. Copy the 16-character password shown

### Update both files:
In `outbound_mailer.py`:
```python
SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USERNAME = "yourgmail@gmail.com"
SMTP_PASSWORD = "xxxx xxxx xxxx xxxx"   # ← 16-char App Password (no spaces needed)
SENDER_NAME   = "Your Name"
SENDER_EMAIL  = "yourgmail@gmail.com"
```

In `inbound_negotiator.py`:
```python
IMAP_HOST     = "imap.gmail.com"
IMAP_PORT     = 993
IMAP_USERNAME = "yourgmail@gmail.com"
IMAP_PASSWORD = "xxxx xxxx xxxx xxxx"   # ← same App Password
SMTP_HOST     = "smtp.gmail.com"
# ... rest same as above
```

### Enable IMAP in Gmail:
Gmail Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP → Save

---

## Step 5 — Configure Your Niche

In `scraper.py`:
```python
TARGET_INDUSTRY = "digital marketing agency"  # ← your target niche
TARGET_LOCATION = "New York"                  # ← your target city
MAX_LEADS       = 50                          # ← leads per run
```

In `outbound_mailer.py`:
```python
AGENCY_OFFER = (
    "We help {industry} businesses generate 3-5 qualified leads per week "
    "using done-for-you LinkedIn outreach — no retainer, pay-per-result only."
)
SENDER_NAME = "Alex Morgan"    # ← use a real-sounding human name
```

---

## Step 6 — Running the Agency

```bash
# Run everything once (scrape → email → check replies)
python main.py

# Run on a loop (repeats every 60 min by default)
python main.py --loop

# Individual phases:
python main.py --scrape     # Only scrape leads
python main.py --outbound   # Only send pending emails
python main.py --inbound    # Only check/negotiate replies
```

---

## CRM Status Flow

```
[scraper.py]  →  pending
                   ↓
[outbound_mailer.py]  →  unanswered
                           ↓
[inbound_negotiator.py]  →  not interested
                          →  unanswered (still negotiating)
                          →  closed client  🎉
```

---

## Free Tier Limits to Know

| Service       | Free Limit                              |
|---------------|----------------------------------------|
| Groq API      | 14,400 tokens/min (very generous)      |
| Gmail SMTP    | 500 emails/day                         |
| Google Sheets | 10M cells per spreadsheet              |
| YellowPages   | No rate limit (be polite: use delays)  |

---

## Troubleshooting

**"Authentication failed" on Gmail SMTP/IMAP:**
→ Make sure you're using an App Password, not your account password.
→ Make sure IMAP is enabled in Gmail settings.

**"Spreadsheet not found" error:**
→ The sheet name must match SPREADSHEET_NAME exactly (case-sensitive).
→ The service account email must be shared with the sheet as Editor.

**Groq API errors:**
→ Check your API key at console.groq.com
→ Verify you're using a supported model name (llama3-70b-8192 or mixtral-8x7b-32768)

**Scraper returns 0 leads:**
→ YellowPages changes its HTML structure occasionally. Check if `div.result` selector still works.
→ Try running `scraper.py` standalone: `python scraper.py`
→ If blocked, reduce scraping frequency or rotate User-Agent strings.

---

## Legal & Ethical Notes

- Only scrape publicly available business contact information.
- Always include an unsubscribe option in your emails (CAN-SPAM / GDPR compliance).
- Respect robots.txt of target websites.
- Keep daily email volume under 100-200/day for new accounts to build sender reputation.
