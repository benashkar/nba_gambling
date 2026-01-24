"""
OddsPortal NBA scraper using Selenium for JavaScript-rendered content.
"""

import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

from utils.date_parser import DateParser
from utils.validators import DataValidator

logger = logging.getLogger(__name__)


class OddsPortalScraper:
    """Scraper for NBA odds data from OddsPortal.com"""

    BASE_URL = "https://www.oddsportal.com"

    SEASON_URLS = {
        "2021-2022": "/basketball/usa/nba-2021-2022/results/",
        "2022-2023": "/basketball/usa/nba-2022-2023/results/",
        "2023-2024": "/basketball/usa/nba-2023-2024/results/",
        "2024-2025": "/basketball/usa/nba-2024-2025/results/",
        "2025-2026": "/basketball/usa/nba/results/",
    }

    # Delays (seconds)
    MIN_PAGE_DELAY = 2.0
    MAX_PAGE_DELAY = 4.0
    MIN_SEASON_DELAY = 10.0
    MAX_SEASON_DELAY = 15.0

    def __init__(
        self,
        headless: bool = True,
        checkpoint_dir: Optional[str] = None,
        team_mappings_path: Optional[str] = None
    ):
        """
        Initialize the scraper.

        Args:
            headless: Run Chrome in headless mode
            checkpoint_dir: Directory for saving checkpoints
            team_mappings_path: Path to team mappings JSON
        """
        self.headless = headless
        self.driver: Optional[webdriver.Chrome] = None
        self.validator = DataValidator(team_mappings_path)

        # Load team mappings for standardization
        self.team_mappings = self._load_team_mappings(team_mappings_path)

        # Checkpoint handling
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else Path("checkpoints")
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # Current scraping state
        self.current_season: Optional[str] = None
        self.current_page: int = 1
        self.scraped_games: List[Dict[str, Any]] = []

    def _load_team_mappings(self, path: Optional[str]) -> Dict[str, str]:
        """Load team name to abbreviation mappings."""
        if path is None:
            path = Path(__file__).parent.parent / 'config' / 'team_mappings.json'
        else:
            path = Path(path)

        try:
            with open(path, 'r') as f:
                data = json.load(f)
                return data.get('team_mappings', {})
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Could not load team mappings: {e}")
            return {}

    def _standardize_team(self, team_name: str) -> str:
        """Convert team name to standard abbreviation."""
        if not team_name:
            return team_name

        # Clean up the team name
        team_name = team_name.strip()

        # Direct lookup
        if team_name in self.team_mappings:
            return self.team_mappings[team_name]

        # Try case-insensitive lookup
        for key, value in self.team_mappings.items():
            if key.lower() == team_name.lower():
                return value

        # If not found, return original (will be flagged by validator)
        logger.warning(f"Could not standardize team name: {team_name}")
        return team_name

    def _setup_driver(self):
        """Configure and start Chrome WebDriver."""
        options = Options()

        if self.headless:
            options.add_argument("--headless=new")

        # Anti-detection measures
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        # Disable automation flags
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)

        # Additional anti-detection
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })

        logger.info("Chrome WebDriver initialized")

    def _close_driver(self):
        """Close the WebDriver."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("Chrome WebDriver closed")

    def _random_delay(self, min_sec: float, max_sec: float):
        """Sleep for a random duration."""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)

    def _wait_for_page_load(self, timeout: int = 15):
        """Wait for the page to fully load."""
        try:
            # Wait for eventRow elements (game data)
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.eventRow"))
            )
            # Small additional wait for JavaScript rendering
            time.sleep(1)
        except TimeoutException:
            logger.warning("Timeout waiting for eventRow elements")

    def _get_page_html(self) -> str:
        """Get current page HTML after JavaScript execution."""
        return self.driver.page_source

    def _navigate_to_page(self, url: str, retries: int = 3) -> bool:
        """
        Navigate to URL with retry logic.

        Args:
            url: Full URL to navigate to
            retries: Number of retry attempts

        Returns:
            True if successful, False otherwise
        """
        for attempt in range(retries):
            try:
                self.driver.get(url)
                self._wait_for_page_load()
                return True
            except WebDriverException as e:
                logger.warning(f"Navigation failed (attempt {attempt + 1}): {e}")
                if attempt < retries - 1:
                    self._random_delay(5, 10)  # Longer delay before retry
                continue

        return False

    def _parse_games_from_html(self, html: str, season: str) -> List[Dict[str, Any]]:
        """
        Parse game data from HTML.

        Args:
            html: Page HTML content
            season: Current season string

        Returns:
            List of game dictionaries
        """
        soup = BeautifulSoup(html, 'lxml')
        games = []

        # Get all game rows using the discovered selector
        game_rows = soup.select('div.eventRow')

        current_date = None

        for row in game_rows:
            try:
                game_data, new_date = self._parse_game_row(row, season, current_date)
                if new_date:
                    current_date = new_date
                if game_data:
                    games.append(game_data)
            except Exception as e:
                logger.error(f"Error parsing game row: {e}")
                continue

        return games

    def _parse_game_row(self, row, season: str, current_date: Optional[str]) -> tuple:
        """
        Parse a single game row.

        Args:
            row: BeautifulSoup element for the row
            season: Current season
            current_date: Last known date (for rows without dates)

        Returns:
            Tuple of (game dictionary or None, new_date or None)
        """
        game = {
            'game_date': None,
            'season': season,
            'home_team': None,
            'away_team': None,
            'home_score': None,
            'away_score': None,
            'closing_spread': None,
            'closing_over_under': None,
            'closing_moneyline_home': None,
            'closing_moneyline_away': None,
            'scraped_at': datetime.now().isoformat()
        }

        new_date = None

        # Extract date from header div (bg-gray-light) if present
        date_header = row.select_one('div.bg-gray-light')
        if date_header:
            date_text = date_header.get_text(strip=True)
            # Extract date pattern like "Yesterday, 22 Jan" or "Today, 23 Jan" or "21 Jan"
            date_match = re.search(r'(?:Today|Yesterday)?,?\s*(\d{1,2}\s+[A-Za-z]{3})', date_text)
            if date_match:
                date_str = date_match.group(0)
                ref_year = DateParser.get_reference_year_for_season(season)
                parsed_date = DateParser.parse(date_str, ref_year)
                if parsed_date:
                    new_date = parsed_date
                    game['game_date'] = parsed_date

        # Use current_date if no date header found
        if not game['game_date']:
            game['game_date'] = current_date

        # Extract teams and scores using participant-name class
        # Each team's score is in a font-bold div within the same <a> parent
        team_elems = row.select('p.participant-name')
        if len(team_elems) >= 2:
            # First team is away, second is home (based on OddsPortal layout)
            game['away_team'] = self._standardize_team(team_elems[0].get_text(strip=True))
            game['home_team'] = self._standardize_team(team_elems[1].get_text(strip=True))

            # Extract scores from the parent <a> elements containing each team
            for i, team_elem in enumerate(team_elems[:2]):
                parent = team_elem.find_parent('a')
                if parent:
                    # Find font-bold div with score
                    bold_divs = parent.select('div.font-bold')
                    for bd in bold_divs:
                        text = bd.get_text(strip=True)
                        if text.isdigit():
                            score = int(text)
                            if 50 <= score <= 200:  # Valid NBA score range
                                if i == 0:
                                    game['away_score'] = score
                                else:
                                    game['home_score'] = score
                                break

        # Extract odds using default-odds-bg-bgcolor class
        odds_elems = row.select('p.default-odds-bg-bgcolor')
        if len(odds_elems) >= 2:
            try:
                # First two odds are moneylines (away, home)
                ml_away = odds_elems[0].get_text(strip=True)
                ml_home = odds_elems[1].get_text(strip=True)

                # Parse moneyline values (handle +/- format)
                if ml_away and ml_away not in ['-', '']:
                    game['closing_moneyline_away'] = int(ml_away.replace('+', ''))
                if ml_home and ml_home not in ['-', '']:
                    game['closing_moneyline_home'] = int(ml_home.replace('+', ''))
            except (ValueError, AttributeError) as e:
                logger.debug(f"Could not parse moneylines: {e}")

        # Extract game detail URL for spread/O/U scraping
        # Look for links that end with a game ID pattern (8 chars alphanumeric)
        for link in row.select('a[href*="/basketball/usa/nba"]'):
            href = link.get('href', '')
            # Game URLs end with team-names-GAMEID/ pattern
            if href and re.search(r'-[A-Za-z0-9]{8}/$', href):
                game['detail_url'] = href
                break

        # Generate game_id
        if game['game_date'] and game['home_team'] and game['away_team']:
            date_part = game['game_date'].replace('-', '')
            game['game_id'] = f"{date_part}_{game['away_team']}_{game['home_team']}"
        else:
            return (None, new_date)

        return (game, new_date)

    def _scrape_game_details(self, game: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scrape spread and O/U from the game detail page.

        Args:
            game: Game dictionary with detail_url

        Returns:
            Updated game dictionary with spread and O/U
        """
        detail_url = game.get('detail_url')
        if not detail_url:
            return game

        base_url = self.BASE_URL + detail_url

        # Load the base game page first
        try:
            self.driver.get(base_url)
            time.sleep(3)
        except Exception as e:
            logger.debug(f"Error loading game page: {e}")
            game.pop('detail_url', None)
            return game

        # Scrape Over/Under by clicking tab with JavaScript
        try:
            clicked = self.driver.execute_script('''
                const tabs = document.querySelectorAll('ul.hide-menu li');
                for (const tab of tabs) {
                    if (tab.textContent.includes('Over/Under')) {
                        tab.click();
                        return true;
                    }
                }
                return false;
            ''')

            if clicked:
                time.sleep(2)
                soup = BeautifulSoup(self.driver.page_source, 'lxml')

                # Find O/U line with most bookmakers (the main line)
                best_total = None
                max_bookmakers = 0

                for elem in soup.find_all('p', string=lambda s: s and ('O/U' in str(s) or 'Over/Under' in str(s))):
                    text = elem.get_text(strip=True)
                    total_match = re.search(r'(\d{3}\.5)', text)
                    if total_match:
                        total = float(total_match.group(1))
                        # Get parent row to find bookmaker count
                        row = elem.find_parent('div', class_=lambda c: c and 'flex' in str(c))
                        if row:
                            row_text = row.get_text(' ', strip=True)
                            count_match = re.search(r'(\d+)\s*$', row_text)
                            if count_match:
                                count = int(count_match.group(1))
                                if count > max_bookmakers:
                                    max_bookmakers = count
                                    best_total = total

                if best_total is not None:
                    game['closing_over_under'] = best_total

        except Exception as e:
            logger.debug(f"Error scraping O/U for {game.get('game_id')}: {e}")

        self._random_delay(1.0, 2.0)

        # Scrape Asian Handicap (Spread) by clicking tab with JavaScript
        try:
            clicked = self.driver.execute_script('''
                const tabs = document.querySelectorAll('ul.hide-menu li');
                for (const tab of tabs) {
                    if (tab.textContent.includes('Asian Handicap')) {
                        tab.click();
                        return true;
                    }
                }
                return false;
            ''')

            if clicked:
                time.sleep(2)
                soup = BeautifulSoup(self.driver.page_source, 'lxml')

                # Find spread line with most bookmakers (the main/consensus line)
                best_spread = None
                max_bookmakers = 0

                for elem in soup.find_all('p', string=lambda s: s and 'Asian Handicap' in str(s)):
                    text = elem.get_text(strip=True)
                    spread_match = re.search(r'Asian Handicap\s*([+-]?\d+\.?\d*)', text)
                    if spread_match:
                        spread = float(spread_match.group(1))
                        # Get parent row to find bookmaker count
                        row = elem.find_parent('div', class_=lambda c: c and 'flex' in str(c))
                        if row:
                            row_text = row.get_text(' ', strip=True)
                            # Bookmaker count is typically the last number in the row
                            count_match = re.search(r'(\d+)\s*$', row_text)
                            if count_match:
                                count = int(count_match.group(1))
                                if count > max_bookmakers:
                                    max_bookmakers = count
                                    best_spread = spread

                if best_spread is not None:
                    game['closing_spread'] = best_spread

        except Exception as e:
            logger.debug(f"Error scraping spread for {game.get('game_id')}: {e}")

        # Remove detail_url from final output
        game.pop('detail_url', None)

        return game

    def _get_total_pages(self) -> int:
        """Determine total number of result pages."""
        try:
            html = self._get_page_html()
            soup = BeautifulSoup(html, 'lxml')

            # Use discovered selector for pagination links
            pagination = soup.select('a.pagination-link')

            max_page = 1
            for elem in pagination:
                try:
                    page_num = int(elem.get_text(strip=True))
                    max_page = max(max_page, page_num)
                except ValueError:
                    continue

            logger.info(f"Found {max_page} total pages")
            return max_page
        except Exception as e:
            logger.error(f"Error getting total pages: {e}")
            return 1

    def _save_checkpoint(self, season: str, page: int, games: List[Dict]):
        """Save current progress to checkpoint file."""
        checkpoint = {
            'season': season,
            'page': page,
            'games_count': len(games),
            'timestamp': datetime.now().isoformat(),
            'games': games
        }

        checkpoint_file = self.checkpoint_dir / f"checkpoint_{season}.json"
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint, f, indent=2)

        logger.info(f"Checkpoint saved: {season} page {page}, {len(games)} games")

    def _load_checkpoint(self, season: str) -> Optional[Dict]:
        """Load checkpoint for a season if it exists."""
        checkpoint_file = self.checkpoint_dir / f"checkpoint_{season}.json"

        if checkpoint_file.exists():
            try:
                with open(checkpoint_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.warning(f"Corrupted checkpoint file: {checkpoint_file}")

        return None

    def scrape_season(
        self,
        season: str,
        resume: bool = True,
        max_pages: Optional[int] = None,
        fetch_details: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Scrape all games for a single season.

        Args:
            season: Season string like '2024-2025'
            resume: Whether to resume from checkpoint
            max_pages: Maximum pages to scrape (None for all)
            fetch_details: Whether to fetch spread/O/U from detail pages (slower)

        Returns:
            List of game dictionaries
        """
        self.fetch_details = fetch_details
        if season not in self.SEASON_URLS:
            raise ValueError(f"Unknown season: {season}")

        self.current_season = season
        self.scraped_games = []

        # Check for checkpoint
        start_page = 1
        if resume:
            checkpoint = self._load_checkpoint(season)
            if checkpoint:
                start_page = checkpoint['page'] + 1
                self.scraped_games = checkpoint['games']
                logger.info(f"Resuming {season} from page {start_page}")

        # Navigate to first results page
        url = self.BASE_URL + self.SEASON_URLS[season]
        if not self._navigate_to_page(url):
            raise Exception(f"Failed to load season URL: {url}")

        # Get total pages
        total_pages = self._get_total_pages()
        if max_pages:
            total_pages = min(total_pages, max_pages)

        logger.info(f"Scraping {season}: pages {start_page} to {total_pages}")

        # Scrape each page
        for page in range(start_page, total_pages + 1):
            self.current_page = page

            # Navigate to page if not first
            if page > 1:
                page_url = f"{url}#/page/{page}/"
                if not self._navigate_to_page(page_url):
                    logger.error(f"Failed to load page {page}")
                    continue

            # Parse games
            html = self._get_page_html()
            page_games = self._parse_games_from_html(html, season)

            # Fetch spread/O/U from detail pages if enabled
            if self.fetch_details:
                games_with_details = [g for g in page_games if g.get('detail_url') and g.get('home_score')]
                logger.info(f"Fetching details for {len(games_with_details)} completed games on this page")
                for i, game in enumerate(page_games):
                    if game.get('detail_url') and game.get('home_score'):  # Only completed games
                        logger.info(f"Fetching details for {game.get('game_id')} ({i+1}/{len(page_games)})")
                        page_games[i] = self._scrape_game_details(game)
                        self._random_delay(1.5, 3.0)

            self.scraped_games.extend(page_games)

            logger.info(f"Page {page}: scraped {len(page_games)} games "
                       f"(total: {len(self.scraped_games)})")

            # Save checkpoint after each page
            self._save_checkpoint(season, page, self.scraped_games)

            # Random delay between pages
            if page < total_pages:
                self._random_delay(self.MIN_PAGE_DELAY, self.MAX_PAGE_DELAY)

        return self.scraped_games

    def scrape_all_seasons(
        self,
        seasons: Optional[List[str]] = None,
        resume: bool = True,
        fetch_details: bool = False
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Scrape multiple seasons.

        Args:
            seasons: List of seasons to scrape (default: all)
            resume: Whether to resume from checkpoints
            fetch_details: Whether to fetch spread/O/U from detail pages

        Returns:
            Dictionary mapping season to list of games
        """
        if seasons is None:
            seasons = list(self.SEASON_URLS.keys())

        results = {}

        try:
            self._setup_driver()

            for i, season in enumerate(seasons):
                logger.info(f"Starting season {season} ({i+1}/{len(seasons)})")

                try:
                    games = self.scrape_season(season, resume=resume, fetch_details=fetch_details)
                    results[season] = games

                    # Validate results
                    validation = self.validator.validate_batch(games)
                    logger.info(f"Season {season} validation: "
                               f"{validation['valid']}/{validation['total']} valid")

                except Exception as e:
                    logger.error(f"Error scraping season {season}: {e}")
                    results[season] = []

                # Delay between seasons
                if i < len(seasons) - 1:
                    self._random_delay(self.MIN_SEASON_DELAY, self.MAX_SEASON_DELAY)

        finally:
            self._close_driver()

        return results

    def scrape_single_page(self, url: str, fetch_details: bool = False) -> List[Dict[str, Any]]:
        """
        Scrape a single page (useful for testing).

        Args:
            url: Full URL to scrape
            fetch_details: Whether to fetch spread/O/U from detail pages

        Returns:
            List of game dictionaries
        """
        try:
            self._setup_driver()

            if not self._navigate_to_page(url):
                raise Exception(f"Failed to load URL: {url}")

            html = self._get_page_html()
            season = "unknown"

            # Try to detect season from URL
            for s, path in self.SEASON_URLS.items():
                if path in url:
                    season = s
                    break

            games = self._parse_games_from_html(html, season)

            # Fetch spread/O/U from detail pages if enabled
            if fetch_details:
                for i, game in enumerate(games):
                    if game.get('detail_url') and game.get('home_score'):
                        logger.info(f"Fetching details for {game.get('game_id')}")
                        games[i] = self._scrape_game_details(game)
                        self._random_delay(1.5, 3.0)

            return games

        finally:
            self._close_driver()
