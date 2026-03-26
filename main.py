"""
main.py
-------
The orchestrator for the fully autonomous B2B arbitrage agency.

Execution flow:
  1. Scrape new leads (if ENABLE_SCRAPER is True)
  2. Push new leads to Google Sheets CRM
  3. Send cold emails to 'pending' leads (outbound loop)
  4. Read replies and negotiate (inbound loop)
  5. Sleep and repeat (continuous mode) OR run once and exit

Run modes:
  python main.py            → runs all modules once then exits
  python main.py --loop     → runs continuously on a schedule
  python main.py --inbound  → only check/process inbound replies
  python main.py --outbound → only send pending emails
  python main.py --scrape   → only scrape and add leads to CRM
"""

import argparse
import logging
import sys
import time

import crm_manager
import inbound_negotiator
import outbound_mailer
import scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MAIN] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agency.log"),   # Also write to log file
    ],
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# ORCHESTRATION CONFIG
# ──────────────────────────────────────────────
ENABLE_SCRAPER  = True    # Set to False if you're adding leads manually to the sheet
LOOP_INTERVAL   = 3600    # Seconds between full cycles in --loop mode (1 hour default)
# ──────────────────────────────────────────────


def run_scrape_phase() -> None:
    """Phase 1: Scrape new leads and add to CRM."""
    logger.info("═" * 50)
    logger.info("PHASE 1: SCRAPING NEW LEADS")
    logger.info("═" * 50)
    try:
        leads = scraper.run_scraper()
        if leads:
            added = crm_manager.add_leads(leads)
            logger.info(f"Scraping complete. {added} new lead(s) added to CRM.")
        else:
            logger.warning("Scraper returned 0 leads. Check TARGET_INDUSTRY/LOCATION settings.")
    except Exception as e:
        logger.error(f"Scraper phase failed: {e}", exc_info=True)


def run_outbound_phase() -> None:
    """Phase 2: Send cold emails to pending leads."""
    logger.info("═" * 50)
    logger.info("PHASE 2: OUTBOUND COLD EMAILS")
    logger.info("═" * 50)
    try:
        summary = outbound_mailer.run_outbound()
        logger.info(
            f"Outbound complete → sent={summary['sent']}, "
            f"failed={summary['failed']}, skipped={summary['skipped']}"
        )
    except Exception as e:
        logger.error(f"Outbound phase failed: {e}", exc_info=True)


def run_inbound_phase() -> None:
    """Phase 3: Read replies and negotiate autonomously."""
    logger.info("═" * 50)
    logger.info("PHASE 3: INBOUND REPLY NEGOTIATION")
    logger.info("═" * 50)
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


def print_banner() -> None:
    print("""
╔══════════════════════════════════════════════════╗
║     🤖 AUTONOMOUS B2B ARBITRAGE AGENCY v1.0      ║
║     Scrape → Email → Negotiate → Close           ║
╚══════════════════════════════════════════════════╝
""")


def run_full_cycle() -> None:
    """Run all three phases sequentially."""
    logger.info("Starting full agency cycle...")

    if ENABLE_SCRAPER:
        run_scrape_phase()

    run_outbound_phase()
    run_inbound_phase()

    crm_manager.print_crm_summary()
    logger.info("Full cycle complete.")


def main() -> None:
    print_banner()

    parser = argparse.ArgumentParser(description="B2B Arbitrage Agency Orchestrator")
    parser.add_argument("--loop",     action="store_true", help="Run continuously on a schedule")
    parser.add_argument("--scrape",   action="store_true", help="Only run the scraper phase")
    parser.add_argument("--outbound", action="store_true", help="Only run the outbound mailer phase")
    parser.add_argument("--inbound",  action="store_true", help="Only run the inbound negotiator phase")
    args = parser.parse_args()

    # ── Single-phase modes ──────────────────────
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

    # ── Continuous loop mode ────────────────────
    if args.loop:
        logger.info(f"Loop mode active. Cycling every {LOOP_INTERVAL // 60} minutes.")
        cycle = 1
        while True:
            logger.info(f"\n{'▶' * 5} CYCLE #{cycle} {'◀' * 5}")
            run_full_cycle()
            logger.info(f"Cycle #{cycle} complete. Sleeping {LOOP_INTERVAL // 60} min...\n")
            time.sleep(LOOP_INTERVAL)
            cycle += 1

    # ── Default: single full run ────────────────
    else:
        run_full_cycle()


if __name__ == "__main__":
    main()
