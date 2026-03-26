"""
main.py
───────
Orchestrator for the autonomous B2B arbitrage agency.

Startup sequence:
  1. Load and validate ALL config from .env via config.py
     (fails loudly if any required secret is missing)
  2. Run phases in order: scrape → outbound → inbound

Run modes:
  python main.py            → single full cycle
  python main.py --loop     → repeat every LOOP_INTERVAL_SEC seconds
  python main.py --scrape   → only scrape leads
  python main.py --outbound → only send pending emails
  python main.py --inbound  → only check replies
  python main.py --config   → print config summary (secrets redacted) and exit
"""

import argparse
import logging
import sys
import time

# config.py is imported first — if .env is missing required values, it exits here.
from config import cfg

import crm_manager
import inbound_negotiator
import outbound_mailer
import scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MAIN] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agency.log"),
    ],
)
logger = logging.getLogger(__name__)


# ── Phase runners ────────────────────────────────────────────────

def run_scrape_phase() -> None:
    logger.info("═" * 52)
    logger.info("PHASE 1 — SCRAPING NEW LEADS")
    logger.info("═" * 52)
    try:
        leads = scraper.run_scraper()
        if leads:
            added = crm_manager.add_leads(leads)
            logger.info(f"Scraping complete. {added} new lead(s) added to CRM.")
        else:
            logger.warning("Scraper returned 0 leads. Check SCRAPER_TARGET_INDUSTRY / LOCATION in .env")
    except Exception as e:
        logger.error(f"Scraper phase failed: {e}", exc_info=True)


def run_outbound_phase() -> None:
    logger.info("═" * 52)
    logger.info("PHASE 2 — OUTBOUND COLD EMAILS")
    logger.info("═" * 52)
    try:
        summary = outbound_mailer.run_outbound()
        logger.info(
            f"Outbound complete → sent={summary['sent']}, "
            f"failed={summary['failed']}, skipped={summary['skipped']}"
        )
    except Exception as e:
        logger.error(f"Outbound phase failed: {e}", exc_info=True)


def run_inbound_phase() -> None:
    logger.info("═" * 52)
    logger.info("PHASE 3 — INBOUND REPLY NEGOTIATION")
    logger.info("═" * 52)
    try:
        summary = inbound_negotiator.run_inbound()
        logger.info(
            f"Inbound complete → processed={summary['processed']}, "
            f"not_interested={summary['not_interested']}, "
            f"follow_up={summary['follow_up']}, "
            f"closed={summary['closed']}"
        )
    except Exception as e:
        logger.error(f"Inbound phase failed: {e}", exc_info=True)


def run_full_cycle(enable_scraper: bool = True) -> None:
    if enable_scraper:
        run_scrape_phase()
    run_outbound_phase()
    run_inbound_phase()
    crm_manager.print_crm_summary()
    logger.info("Full cycle complete.")


# ── Banner ───────────────────────────────────────────────────────

def print_banner() -> None:
    print("""
╔══════════════════════════════════════════════════╗
║     🤖 AUTONOMOUS B2B ARBITRAGE AGENCY v2.0      ║
║     Scrape → Email → Negotiate → Close           ║
╚══════════════════════════════════════════════════╝
""")


# ── Entry point ──────────────────────────────────────────────────

def main() -> None:
    print_banner()

    parser = argparse.ArgumentParser(description="B2B Arbitrage Agency Orchestrator")
    parser.add_argument("--loop",     action="store_true", help="Run continuously on a schedule")
    parser.add_argument("--scrape",   action="store_true", help="Only run the scraper phase")
    parser.add_argument("--outbound", action="store_true", help="Only run the outbound mailer")
    parser.add_argument("--inbound",  action="store_true", help="Only run the inbound negotiator")
    parser.add_argument("--config",   action="store_true", help="Print config summary and exit")
    parser.add_argument("--no-scrape", action="store_true", help="Skip scraper in full cycle")
    args = parser.parse_args()

    # ── Always validate config on startup ───────────────────────
    try:
        cfg.validate()
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    # ── --config: just show settings and exit ───────────────────
    if args.config:
        print(cfg.redacted_summary())
        return

    # ── Single-phase modes ───────────────────────────────────────
    if args.scrape:
        run_scrape_phase()
        crm_manager.print_crm_summary()
        return

    if args.outbound:
        run_outbound_phase()
        crm_manager.print_crm_summary()
        return

    if args.inbound:
        run_inbound_phase()
        crm_manager.print_crm_summary()
        return

    enable_scraper = not args.no_scrape

    # ── Continuous loop mode ─────────────────────────────────────
    if args.loop:
        interval = cfg.LOOP_INTERVAL_SEC
        logger.info(f"Loop mode active. Cycling every {interval // 60} minutes.")
        cycle = 1
        while True:
            logger.info(f"\n{'▶' * 5} CYCLE #{cycle} {'◀' * 5}")
            run_full_cycle(enable_scraper=enable_scraper)
            logger.info(f"Cycle #{cycle} done. Sleeping {interval // 60} min...\n")
            time.sleep(interval)
            cycle += 1

    # ── Default: single full run ─────────────────────────────────
    else:
        run_full_cycle(enable_scraper=enable_scraper)


if __name__ == "__main__":
    main()
