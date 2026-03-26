# 🤖 Autonomous B2B Arbitrage Agency v2.0 — Setup Guide

## Project Structure

```
b2b_agency/
├── .env                     ← ⚠️  YOUR secrets (never commit this)
├── .env.example             ← Template — copy this to .env and fill in
├── .gitignore               ← Protects .env and credentials.json from Git
├── config.py                ← Loads .env, validates all values, exports `cfg`
│
├── main.py                  ← Orchestrator (run this)
├── scraper.py               ← Lead scraper
├── crm_manager.py           ← Google Sheets CRM
├── outbound_mailer.py       ← Cold email sender
├── inbound_negotiator.py    ← Reply reader & AI negotiator
│
├── requirements.txt         ← Python dependencies
├── credentials.json         ← ⚠️  GCP Service Account key (add manually, never commit)
└── agency.log               ← Auto-generated run log
```

### Config Architecture (how secrets flow)

```
.env  ──→  config.py (loads + validates)  ──→  cfg singleton
                                                    ↓
                          scraper.py ←─────────────┤
                          crm_manager.py ←──────────┤
                          outbound_mailer.py ←───────┤
                          inbound_negotiator.py ←────┘
```

**Rule:** Only `.env` holds secrets. Only `config.py` reads `.env`.
Every other module imports `from config import cfg`.

---

## Step 1 — Python Environment

```bash
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

---

## Step 2 — Create Your .env File

```bash
cp .env.example .env
```

Then open `.env` and fill in every value. The sections below explain each one.

---

## Step 3 — Groq API Key

1. Go to https://console.groq.com → sign up (free)
2. Generate an API key
3. Paste into `.env`:
```
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=llama3-70b-8192
```

---

## Step 4 — Google Sheets CRM

### 4a. Create the Sheet
1. Go to https://sheets.google.com
2. Create a new spreadsheet
3. Name it exactly as you set in `.env` → `GOOGLE_SPREADSHEET_NAME`
4. The script auto-creates headers on first run

### 4b. GCP Service Account
1. https://console.cloud.google.com → New project
2. Enable: **Google Sheets API** + **Google Drive API**
3. IAM & Admin → Service Accounts → Create
4. Keys tab → Add Key → JSON → download
5. Rename to `credentials.json`, place in project root

### 4c. Share the Sheet
Open `credentials.json`, copy the `client_email` value,
then share your Google Sheet with it (Editor access).

### 4d. Set in .env
```
GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json
GOOGLE_SPREADSHEET_NAME=B2B Agency CRM
GOOGLE_WORKSHEET_NAME=Leads
```

---

## Step 5 — Gmail SMTP + IMAP

### Enable App Passwords (required for Gmail)
1. Google Account → Security → 2-Step Verification (enable it)
2. Security → App Passwords → create one named "B2B Agency"
3. Copy the 16-character password

### Enable IMAP in Gmail
Gmail → Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP

### Set in .env
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=youremail@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx
SENDER_NAME=Alex Morgan
SENDER_EMAIL=youremail@gmail.com

IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USERNAME=youremail@gmail.com
IMAP_PASSWORD=xxxx xxxx xxxx xxxx
IMAP_FOLDER=INBOX
```

---

## Step 6 — Configure Your Niche

In `.env`:
```
SCRAPER_TARGET_INDUSTRY=digital marketing agency
SCRAPER_TARGET_LOCATION=New York
SCRAPER_MAX_LEADS=50
AGENCY_OFFER=We help {industry} businesses generate 3-5 qualified leads per week using done-for-you LinkedIn outreach — no retainer, pay-per-result only.
SENDER_NAME=Alex Morgan
```

---

## Step 7 — Validate Config Before First Run

```bash
python config.py
```

This prints a redacted summary of all settings and runs validation checks.
Fix any errors reported before proceeding.

---

## Step 8 — Running the Agency

```bash
# Validate config only (secrets redacted)
python main.py --config

# Run everything once
python main.py

# Run on a loop (repeats every LOOP_INTERVAL_SEC)
python main.py --loop

# Skip scraper (if you're adding leads manually)
python main.py --no-scrape

# Individual phases
python main.py --scrape
python main.py --outbound
python main.py --inbound
```

---

## CRM Status Flow

```
[scraper]  ──→  pending
                  ↓
[outbound_mailer]  ──→  unanswered
                           ↓
[inbound_negotiator]  ──→  not interested
                       ──→  unanswered  (still negotiating — loops back)
                       ──→  closed client  🎉
```

---

## Security Checklist

- [ ] `.env` is in `.gitignore` (already done — do not remove it)
- [ ] `credentials.json` is in `.gitignore` (already done)
- [ ] You ran `python config.py` and saw ✅ Config validated
- [ ] You never paste secrets directly into `.py` files
- [ ] If deploying to a server: use environment variables or a secrets manager instead of `.env`

---

## Free Tier Limits

| Service        | Free Limit                          |
|----------------|-------------------------------------|
| Groq API       | 14,400 tokens/min (very generous)   |
| Gmail SMTP     | 500 emails/day                      |
| Google Sheets  | 10M cells per spreadsheet           |

---

## Troubleshooting

**`Missing required config: 'GROQ_API_KEY'`**
→ You haven't created `.env` yet. Run: `cp .env.example .env` then fill it in.

**`SMTP authentication failed`**
→ You need a Gmail App Password (not your login password). IMAP must also be enabled.

**`Google service account file not found`**
→ `credentials.json` must be in the project root, and its path must match `GOOGLE_SERVICE_ACCOUNT_FILE` in `.env`.

**`Spreadsheet not found`**
→ `GOOGLE_SPREADSHEET_NAME` must match the sheet name exactly (case-sensitive) and the service account email must have Editor access.

**Scraper returns 0 leads**
→ YellowPages changes HTML selectors occasionally. Test standalone: `python scraper.py`
