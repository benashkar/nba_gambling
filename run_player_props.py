#!/usr/bin/env python3
"""
Player Props Scraper - Daily Runner

Scrapes player prop lines from FanDuel and DraftKings using The Odds API.
Designed to run multiple times daily (6am, 12pm, 4pm CST) to capture line movements.

Usage:
    python run_player_props.py              # Standard run
    python run_player_props.py --compare    # Also save odds comparison
"""

import sys
import os
import logging
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# Project path
PROJECT_DIR = Path(__file__).parent
os.chdir(PROJECT_DIR)
sys.path.insert(0, str(PROJECT_DIR))

# Setup logging
LOG_PATH = PROJECT_DIR / "logs"
LOG_PATH.mkdir(parents=True, exist_ok=True)

log_file = LOG_PATH / f"player_props_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Scrape NBA player props')
    parser.add_argument('--compare', action='store_true', help='Save odds comparison file')
    parser.add_argument('--markets', nargs='+',
                        default=['points', 'rebounds', 'assists', 'threes'],
                        help='Prop types to scrape')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("PLAYER PROPS SCRAPER")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    try:
        from scrapers.odds_api_props_scraper import OddsAPIPropsScraper

        # Initialize scraper
        scraper = OddsAPIPropsScraper()

        # Scrape all props
        logger.info(f"Scraping markets: {args.markets}")
        results = scraper.scrape_all_props(
            markets=args.markets,
            bookmakers=['fanduel', 'draftkings', 'betmgm']
        )

        # Summary
        total = sum(len(props) for props in results.values())
        logger.info(f"\nResults:")
        for book, props in sorted(results.items()):
            logger.info(f"  {book.upper()}: {len(props)} props")
        logger.info(f"  TOTAL: {total} props")
        logger.info(f"  API requests remaining: {scraper.requests_remaining}")

        if total > 0:
            # Save with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            filename = f"player_props_{timestamp}.csv"
            output_path = scraper.save_results(results, filename=filename)
            logger.info(f"Saved to: {output_path}")

            # Also save a "latest" version for easy access
            latest_path = scraper.save_results(results, filename="player_props_latest.csv")

            if args.compare:
                import pandas as pd
                comparison = scraper.find_best_odds(results)
                compare_path = Path("data/output") / f"props_comparison_{timestamp}.csv"
                comparison.to_csv(compare_path, index=False)
                logger.info(f"Comparison saved to: {compare_path}")
        else:
            logger.warning("No props found (games may not be available yet)")

        logger.info("\nScrape completed successfully")
        return True

    except Exception as e:
        logger.error(f"Scrape failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
