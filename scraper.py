"""
scraper.py
──────────
Scrapes business names, websites, and emails from the target industry.
All settings are loaded from config.py (which reads from .env).

No credentials or hardcoded values in this file.
"""

import re
import time
import random
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from config import cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SCRAPER] %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


# ── Helpers ─────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    return " ".join(text.split()).strip()


def _extract_emails_from_text(text: str) -> list[str]:
    found = EMAIL_REGEX.findall(text)
    valid = [
        e for e in found
        if not any(e.endswith(ext) for ext in [".png", ".jpg", ".gif", ".css", ".js"])
    ]
    return list(set(valid))


def _fetch_page(url: str, retries: int = 3) -> str | None:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logger.warning(f"Fetch failed ({attempt+1}/{retries}): {url} — {e}")
            time.sleep(random.uniform(2, 5))
    return None


def _scrape_email_from_website(site_url: str) -> str:
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    for path in ["", "/contact", "/contact-us", "/about"]:
        url  = urljoin(site_url, path)
        html = _fetch_page(url)
        if not html:
            continue
        emails    = _extract_emails_from_text(html)
        preferred = [e for e in emails if not e.startswith(("info@", "support@", "noreply@"))]
        if preferred:
            return preferred[0]
        if emails:
            return emails[0]
        time.sleep(random.uniform(1, 3))
    return ""


# ── Scrapers ─────────────────────────────────────────────────────

def _scrape_yellowpages(industry: str, location: str, max_leads: int) -> list[dict]:
    leads = []
    page  = 1

    while len(leads) < max_leads:
        query = f"{industry} {location}".replace(" ", "+")
        url   = f"https://www.yellowpages.com/search?search_terms={query}&page={page}"
        logger.info(f"Scraping YellowPages page {page}: {url}")

        html = _fetch_page(url)
        if not html:
            break

        soup     = BeautifulSoup(html, "html.parser")
        listings = soup.select("div.result")
        if not listings:
            logger.info("No more listings found — stopping pagination.")
            break

        for listing in listings:
            if len(leads) >= max_leads:
                break

            name_tag = listing.select_one("a.business-name span")
            name     = _clean_text(name_tag.text) if name_tag else ""
            if not name:
                continue

            site_tag = listing.select_one("a.track-visit-website")
            website  = site_tag["href"].strip() if site_tag and site_tag.get("href") else ""

            email = ""
            if website:
                logger.info(f"  Visiting site for email: {name} → {website}")
                email = _scrape_email_from_website(website)
                time.sleep(random.uniform(2, 5))

            if not email:
                logger.info(f"  No email found for: {name} — skipping")
                continue

            leads.append({
                "business_name": name,
                "website":       website,
                "email":         email,
                "status":        "pending",
            })
            logger.info(f"  ✓ Lead captured: {name} | {email}")

        page += 1
        time.sleep(random.uniform(5, 10))

    return leads


def _scrape_google_fallback(industry: str, location: str, max_leads: int) -> list[dict]:
    leads = []
    query = f'"{industry}" "{location}" email contact site'
    url   = f"https://www.google.com/search?q={query.replace(' ', '+')}&num=50"

    html = _fetch_page(url)
    if not html:
        return leads

    soup   = BeautifulSoup(html, "html.parser")
    emails = _extract_emails_from_text(soup.get_text())

    for email in emails[:max_leads]:
        domain = email.split("@")[1]
        leads.append({
            "business_name": domain.split(".")[0].title(),
            "website":       f"https://{domain}",
            "email":         email,
            "status":        "pending",
        })
    return leads


# ── Public API ───────────────────────────────────────────────────

def run_scraper() -> list[dict]:
    """Entry point called by main.py. All config loaded from cfg."""
    industry  = cfg.SCRAPER_TARGET_INDUSTRY
    location  = cfg.SCRAPER_TARGET_LOCATION
    max_leads = cfg.SCRAPER_MAX_LEADS

    logger.info(f"Starting scraper: industry='{industry}', location='{location}', max={max_leads}")

    leads = _scrape_yellowpages(industry, location, max_leads)

    if len(leads) < max_leads:
        logger.info(f"Only {len(leads)} leads from YP — running Google fallback...")
        extra = _scrape_google_fallback(industry, location, max_leads - len(leads))
        leads.extend(extra)

    seen, unique = set(), []
    for lead in leads:
        if lead["email"] not in seen:
            seen.add(lead["email"])
            unique.append(lead)

    logger.info(f"Scraper finished. Total unique leads: {len(unique)}")
    return unique


if __name__ == "__main__":
    results = run_scraper()
    for r in results:
        print(r)
