"""Repository for NBA games database operations."""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from mysql.connector import Error as MySQLError

from .connection import DatabaseConnection, get_connection

logger = logging.getLogger(__name__)


class GamesRepository:
    """Repository for CRUD operations on NBA games."""

    def __init__(self, db: DatabaseConnection = None):
        """
        Initialize the repository.

        Args:
            db: DatabaseConnection instance (uses global if not provided)
        """
        self.db = db or get_connection()

    def upsert_game(self, game: Dict[str, Any]) -> Tuple[bool, bool]:
        """
        Insert or update a single game.

        Args:
            game: Dictionary with game data

        Returns:
            Tuple of (success, was_insert)
        """
        sql = """
            INSERT INTO games (
                game_id, game_date, season, home_team, away_team,
                home_score, away_score, closing_spread, closing_over_under,
                closing_moneyline_home, closing_moneyline_away, scraped_at
            ) VALUES (
                %(game_id)s, %(game_date)s, %(season)s, %(home_team)s, %(away_team)s,
                %(home_score)s, %(away_score)s, %(closing_spread)s, %(closing_over_under)s,
                %(closing_moneyline_home)s, %(closing_moneyline_away)s, %(scraped_at)s
            )
            ON DUPLICATE KEY UPDATE
                home_score = VALUES(home_score),
                away_score = VALUES(away_score),
                closing_spread = VALUES(closing_spread),
                closing_over_under = VALUES(closing_over_under),
                closing_moneyline_home = VALUES(closing_moneyline_home),
                closing_moneyline_away = VALUES(closing_moneyline_away),
                scraped_at = VALUES(scraped_at)
        """

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(sql, self._prepare_game_params(game))
                was_insert = cursor.rowcount == 1
                return True, was_insert
        except MySQLError as e:
            logger.error(f"Failed to upsert game {game.get('game_id')}: {e}")
            return False, False

    def upsert_games_batch(self, games: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Insert or update multiple games in a batch.

        Args:
            games: List of game dictionaries

        Returns:
            Dictionary with counts: inserted, updated, failed
        """
        if not games:
            return {'inserted': 0, 'updated': 0, 'failed': 0}

        sql = """
            INSERT INTO games (
                game_id, game_date, season, home_team, away_team,
                home_score, away_score, closing_spread, closing_over_under,
                closing_moneyline_home, closing_moneyline_away, scraped_at
            ) VALUES (
                %(game_id)s, %(game_date)s, %(season)s, %(home_team)s, %(away_team)s,
                %(home_score)s, %(away_score)s, %(closing_spread)s, %(closing_over_under)s,
                %(closing_moneyline_home)s, %(closing_moneyline_away)s, %(scraped_at)s
            )
            ON DUPLICATE KEY UPDATE
                home_score = VALUES(home_score),
                away_score = VALUES(away_score),
                closing_spread = VALUES(closing_spread),
                closing_over_under = VALUES(closing_over_under),
                closing_moneyline_home = VALUES(closing_moneyline_home),
                closing_moneyline_away = VALUES(closing_moneyline_away),
                scraped_at = VALUES(scraped_at)
        """

        results = {'inserted': 0, 'updated': 0, 'failed': 0}

        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    for game in games:
                        try:
                            params = self._prepare_game_params(game)
                            cursor.execute(sql, params)
                            if cursor.rowcount == 1:
                                results['inserted'] += 1
                            elif cursor.rowcount == 2:
                                # ON DUPLICATE KEY UPDATE counts as 2 affected rows
                                results['updated'] += 1
                        except MySQLError as e:
                            logger.warning(f"Failed to upsert game {game.get('game_id')}: {e}")
                            results['failed'] += 1

                    conn.commit()
                    logger.info(f"Batch upsert complete: {results['inserted']} inserted, {results['updated']} updated, {results['failed']} failed")
                finally:
                    cursor.close()
        except MySQLError as e:
            logger.error(f"Batch upsert failed: {e}")
            results['failed'] = len(games)

        return results

    def _prepare_game_params(self, game: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare game parameters for SQL execution."""
        # Handle scraped_at - convert string to datetime if needed
        scraped_at = game.get('scraped_at')
        if isinstance(scraped_at, str):
            try:
                scraped_at = datetime.fromisoformat(scraped_at.replace('Z', '+00:00'))
            except ValueError:
                scraped_at = datetime.now()
        elif scraped_at is None:
            scraped_at = datetime.now()

        return {
            'game_id': game.get('game_id'),
            'game_date': game.get('game_date'),
            'season': game.get('season'),
            'home_team': game.get('home_team'),
            'away_team': game.get('away_team'),
            'home_score': self._to_decimal(game.get('home_score')),
            'away_score': self._to_decimal(game.get('away_score')),
            'closing_spread': self._to_decimal(game.get('closing_spread')),
            'closing_over_under': self._to_decimal(game.get('closing_over_under')),
            'closing_moneyline_home': self._to_decimal(game.get('closing_moneyline_home')),
            'closing_moneyline_away': self._to_decimal(game.get('closing_moneyline_away')),
            'scraped_at': scraped_at,
        }

    def _to_decimal(self, value) -> Optional[float]:
        """Convert value to decimal/float, handling empty strings and None."""
        if value is None or value == '' or value == 'None':
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def get_game_by_id(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Get a single game by its ID."""
        sql = "SELECT * FROM games WHERE game_id = %s"

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(sql, (game_id,))
                return cursor.fetchone()
        except MySQLError as e:
            logger.error(f"Failed to get game {game_id}: {e}")
            return None

    def get_games_by_date(self, game_date: str) -> List[Dict[str, Any]]:
        """Get all games for a specific date."""
        sql = "SELECT * FROM games WHERE game_date = %s ORDER BY game_id"

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(sql, (game_date,))
                return cursor.fetchall()
        except MySQLError as e:
            logger.error(f"Failed to get games for date {game_date}: {e}")
            return []

    def get_games_by_season(self, season: str) -> List[Dict[str, Any]]:
        """Get all games for a specific season."""
        sql = "SELECT * FROM games WHERE season = %s ORDER BY game_date, game_id"

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(sql, (season,))
                return cursor.fetchall()
        except MySQLError as e:
            logger.error(f"Failed to get games for season {season}: {e}")
            return []

    def get_latest_game_date(self, season: str = None) -> Optional[str]:
        """Get the most recent game date, optionally filtered by season."""
        if season:
            sql = "SELECT MAX(game_date) as latest FROM games WHERE season = %s AND home_score IS NOT NULL"
            params = (season,)
        else:
            sql = "SELECT MAX(game_date) as latest FROM games WHERE home_score IS NOT NULL"
            params = ()

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(sql, params)
                result = cursor.fetchone()
                return str(result['latest']) if result and result['latest'] else None
        except MySQLError as e:
            logger.error(f"Failed to get latest game date: {e}")
            return None

    def get_game_count(self, season: str = None) -> int:
        """Get total game count, optionally filtered by season."""
        if season:
            sql = "SELECT COUNT(*) as count FROM games WHERE season = %s"
            params = (season,)
        else:
            sql = "SELECT COUNT(*) as count FROM games"
            params = ()

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(sql, params)
                result = cursor.fetchone()
                return result['count'] if result else 0
        except MySQLError as e:
            logger.error(f"Failed to get game count: {e}")
            return 0

    def get_seasons(self) -> List[str]:
        """Get list of all seasons in the database."""
        sql = "SELECT DISTINCT season FROM games ORDER BY season"

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(sql)
                results = cursor.fetchall()
                return [r['season'] for r in results]
        except MySQLError as e:
            logger.error(f"Failed to get seasons: {e}")
            return []


class ScrapeRunsRepository:
    """Repository for tracking scrape runs."""

    def __init__(self, db: DatabaseConnection = None):
        self.db = db or get_connection()

    def start_run(self, scraper_name: str, season: str = None) -> Optional[int]:
        """Record the start of a scrape run."""
        sql = """
            INSERT INTO scrape_runs (scraper_name, season, started_at, status)
            VALUES (%s, %s, %s, 'running')
        """

        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (scraper_name, season, datetime.now()))
                conn.commit()
                run_id = cursor.lastrowid
                cursor.close()
                logger.info(f"Started scrape run {run_id} for {scraper_name}")
                return run_id
        except MySQLError as e:
            logger.error(f"Failed to start scrape run: {e}")
            return None

    def complete_run(
        self,
        run_id: int,
        games_scraped: int,
        games_inserted: int,
        games_updated: int
    ):
        """Record successful completion of a scrape run."""
        sql = """
            UPDATE scrape_runs
            SET completed_at = %s, games_scraped = %s, games_inserted = %s,
                games_updated = %s, status = 'completed'
            WHERE id = %s
        """

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(sql, (
                    datetime.now(), games_scraped, games_inserted, games_updated, run_id
                ))
                logger.info(f"Completed scrape run {run_id}: {games_scraped} scraped, {games_inserted} inserted, {games_updated} updated")
        except MySQLError as e:
            logger.error(f"Failed to complete scrape run: {e}")

    def fail_run(self, run_id: int, error_message: str):
        """Record failure of a scrape run."""
        sql = """
            UPDATE scrape_runs
            SET completed_at = %s, status = 'failed', error_message = %s
            WHERE id = %s
        """

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(sql, (datetime.now(), error_message, run_id))
                logger.error(f"Failed scrape run {run_id}: {error_message}")
        except MySQLError as e:
            logger.error(f"Failed to record run failure: {e}")

    def get_last_run(self, scraper_name: str) -> Optional[Dict[str, Any]]:
        """Get the most recent run for a scraper."""
        sql = """
            SELECT * FROM scrape_runs
            WHERE scraper_name = %s
            ORDER BY started_at DESC
            LIMIT 1
        """

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(sql, (scraper_name,))
                return cursor.fetchone()
        except MySQLError as e:
            logger.error(f"Failed to get last run: {e}")
            return None
