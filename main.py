#!/usr/bin/env python3
"""
NBA Odds Scraper - Main Entry Point

Scrapes NBA closing lines from OddsPortal.com for historical seasons.
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from scrapers.oddsportal_scraper import OddsPortalScraper
from utils.validators import DataValidator

# Optional MySQL support
try:
    from database import init_database, GamesRepository
    from database.repository import ScrapeRunsRepository
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

# Setup logging
def setup_logging(verbose: bool = False, log_file: str = None):
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO

    # Use UTF-8 encoding for handlers
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    handlers = [stdout_handler]

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


def export_to_csv(games: list, output_path: str, append: bool = False):
    """
    Export games to CSV file.

    Args:
        games: List of game dictionaries
        output_path: Path for output CSV
        append: Whether to append to existing file
    """
    if not games:
        logging.warning("No games to export")
        return

    # Define column order
    columns = [
        'game_id',
        'game_date',
        'season',
        'home_team',
        'away_team',
        'home_score',
        'away_score',
        'closing_spread',
        'closing_over_under',
        'closing_moneyline_home',
        'closing_moneyline_away',
        'scraped_at'
    ]

    df = pd.DataFrame(games)

    # Ensure all columns exist
    for col in columns:
        if col not in df.columns:
            df[col] = None

    # Reorder columns
    df = df[columns]

    # Remove duplicates
    initial_count = len(df)
    df = df.drop_duplicates(subset=['game_id'], keep='last')
    if len(df) < initial_count:
        logging.info(f"Removed {initial_count - len(df)} duplicate games")

    # Sort by date
    df = df.sort_values('game_date')

    # Export
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    mode = 'a' if append and output_path.exists() else 'w'
    header = not (append and output_path.exists())

    df.to_csv(output_path, mode=mode, header=header, index=False)
    logging.info(f"Exported {len(df)} games to {output_path}")


def export_to_mysql(games: list, scraper_name: str = 'oddsportal') -> dict:
    """
    Export games to MySQL database.

    Args:
        games: List of game dictionaries
        scraper_name: Name of the scraper for tracking

    Returns:
        Dictionary with results: inserted, updated, failed
    """
    if not MYSQL_AVAILABLE:
        logging.error("MySQL support not available. Install mysql-connector-python.")
        return {'inserted': 0, 'updated': 0, 'failed': len(games)}

    if not games:
        logging.warning("No games to export to MySQL")
        return {'inserted': 0, 'updated': 0, 'failed': 0}

    logger = logging.getLogger(__name__)

    # Initialize repositories
    games_repo = GamesRepository()
    runs_repo = ScrapeRunsRepository()

    # Start a scrape run record
    run_id = runs_repo.start_run(scraper_name)

    try:
        # Batch upsert all games
        results = games_repo.upsert_games_batch(games)

        # Record successful completion
        if run_id:
            runs_repo.complete_run(
                run_id,
                games_scraped=len(games),
                games_inserted=results['inserted'],
                games_updated=results['updated']
            )

        logger.info(f"MySQL export complete: {results['inserted']} inserted, {results['updated']} updated, {results['failed']} failed")
        return results

    except Exception as e:
        logger.error(f"MySQL export failed: {e}")
        if run_id:
            runs_repo.fail_run(run_id, str(e))
        return {'inserted': 0, 'updated': 0, 'failed': len(games)}


def main():
    parser = argparse.ArgumentParser(
        description='Scrape NBA odds from OddsPortal.com'
    )

    parser.add_argument(
        '--season',
        type=str,
        help='Specific season to scrape (e.g., 2024-2025). Scrapes all if not specified.'
    )

    parser.add_argument(
        '--all-seasons',
        action='store_true',
        help='Scrape all available seasons (2021-2022 through 2025-2026)'
    )

    parser.add_argument(
        '--resume',
        action='store_true',
        default=True,
        help='Resume from checkpoint if available (default: True)'
    )

    parser.add_argument(
        '--no-resume',
        action='store_true',
        help='Start fresh, ignoring any checkpoints'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='data/output/nba_odds.csv',
        help='Output CSV file path'
    )

    # MySQL options
    parser.add_argument(
        '--mysql',
        action='store_true',
        help='Export to MySQL database (requires mysql-connector-python)'
    )

    parser.add_argument(
        '--mysql-host',
        type=str,
        default=os.getenv('MYSQL_HOST', 'localhost'),
        help='MySQL host (default: localhost or MYSQL_HOST env var)'
    )

    parser.add_argument(
        '--mysql-port',
        type=int,
        default=int(os.getenv('MYSQL_PORT', '3306')),
        help='MySQL port (default: 3306 or MYSQL_PORT env var)'
    )

    parser.add_argument(
        '--mysql-user',
        type=str,
        default=os.getenv('MYSQL_USER', 'nba_scraper'),
        help='MySQL user (default: nba_scraper or MYSQL_USER env var)'
    )

    parser.add_argument(
        '--mysql-password',
        type=str,
        default=os.getenv('MYSQL_PASSWORD', ''),
        help='MySQL password (default: MYSQL_PASSWORD env var)'
    )

    parser.add_argument(
        '--mysql-database',
        type=str,
        default=os.getenv('MYSQL_DATABASE', 'nba_gambling'),
        help='MySQL database name (default: nba_gambling or MYSQL_DATABASE env var)'
    )

    parser.add_argument(
        '--no-csv',
        action='store_true',
        help='Skip CSV export (use with --mysql to only export to database)'
    )

    parser.add_argument(
        '--max-pages',
        type=int,
        help='Maximum pages to scrape per season (for testing)'
    )

    parser.add_argument(
        '--headless',
        action='store_true',
        default=True,
        help='Run Chrome in headless mode (default: True)'
    )

    parser.add_argument(
        '--no-headless',
        action='store_true',
        help='Run Chrome with visible browser window'
    )

    parser.add_argument(
        '--fetch-details',
        action='store_true',
        help='Fetch spread and O/U from game detail pages (slower, ~5 sec per game)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    parser.add_argument(
        '--log-file',
        type=str,
        default='logs/scraper.log',
        help='Log file path'
    )

    parser.add_argument(
        '--validate-only',
        type=str,
        metavar='CSV_FILE',
        help='Validate an existing CSV file without scraping'
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose, log_file=args.log_file)
    logger = logging.getLogger(__name__)

    # Validation-only mode
    if args.validate_only:
        logger.info(f"Validating {args.validate_only}")
        df = pd.read_csv(args.validate_only)
        games = df.to_dict('records')

        validator = DataValidator()
        result = validator.validate_batch(games)

        print(f"\nValidation Results:")
        print(f"  Total games: {result['total']}")
        print(f"  Valid: {result['valid']}")
        print(f"  With errors: {result['with_errors']}")
        print(f"  With warnings: {result['with_warnings']}")

        if result['errors']:
            print(f"\nSample errors:")
            for err in result['errors'][:10]:
                print(f"  - {err}")

        if result['warnings']:
            print(f"\nSample warnings:")
            for warn in result['warnings'][:10]:
                print(f"  - {warn}")

        # Check duplicates
        duplicates = validator.check_duplicates(games)
        if duplicates:
            print(f"\nDuplicate game IDs: {len(duplicates)}")
            for dup in duplicates[:5]:
                print(f"  - {dup}")

        return

    # Determine resume setting
    resume = args.resume and not args.no_resume

    # Determine headless setting
    headless = args.headless and not args.no_headless

    # Determine seasons to scrape
    seasons = None
    if args.season:
        seasons = [args.season]
    elif args.all_seasons:
        seasons = None  # Will use all available seasons

    if not args.season and not args.all_seasons:
        parser.error("Please specify --season or --all-seasons")

    logger.info("=" * 60)
    logger.info("NBA Odds Scraper Starting")
    logger.info(f"  Seasons: {seasons or 'all'}")
    logger.info(f"  Resume: {resume}")
    logger.info(f"  Headless: {headless}")
    logger.info(f"  Fetch Details: {args.fetch_details}")
    logger.info(f"  Output: {args.output}")
    logger.info(f"  MySQL: {args.mysql}")
    logger.info("=" * 60)

    # Initialize MySQL connection if requested
    if args.mysql:
        if not MYSQL_AVAILABLE:
            logger.error("MySQL support not available. Install: pip install mysql-connector-python")
            sys.exit(1)

        try:
            db = init_database(
                host=args.mysql_host,
                port=args.mysql_port,
                user=args.mysql_user,
                password=args.mysql_password,
                database=args.mysql_database
            )
            if db.test_connection():
                logger.info(f"MySQL connection established: {args.mysql_host}:{args.mysql_port}/{args.mysql_database}")
            else:
                logger.error("MySQL connection test failed")
                sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to connect to MySQL: {e}")
            sys.exit(1)

    # Create scraper
    scraper = OddsPortalScraper(
        headless=headless,
        checkpoint_dir='checkpoints'
    )

    all_games = []

    try:
        if seasons:
            # Scrape specific seasons
            for season in seasons:
                logger.info(f"Scraping season {season}")
                games = scraper.scrape_season(
                    season,
                    resume=resume,
                    max_pages=args.max_pages,
                    fetch_details=args.fetch_details
                )
                all_games.extend(games)
        else:
            # Scrape all seasons
            results = scraper.scrape_all_seasons(resume=resume, fetch_details=args.fetch_details)
            for season, games in results.items():
                all_games.extend(games)

    except KeyboardInterrupt:
        logger.warning("Scraping interrupted by user")
    except Exception as e:
        logger.error(f"Scraping failed: {e}", exc_info=True)
        raise

    # Export results
    if all_games:
        # Export to CSV (unless --no-csv is specified)
        if not args.no_csv:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = args.output.replace('.csv', f'_{timestamp}.csv')
            export_to_csv(all_games, output_path)

            # Also save to the default path without timestamp
            export_to_csv(all_games, args.output)

        # Export to MySQL if requested
        if args.mysql:
            mysql_results = export_to_mysql(all_games, scraper_name='oddsportal_nba')
            logger.info(f"MySQL export: {mysql_results['inserted']} inserted, {mysql_results['updated']} updated")

        # Final validation
        validator = DataValidator()
        result = validator.validate_batch(all_games)
        logger.info(f"Final validation: {result['valid']}/{result['total']} valid games")
    else:
        logger.warning("No games were scraped")


if __name__ == '__main__':
    main()
