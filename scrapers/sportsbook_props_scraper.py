"""
Selenium-based NBA Player Props Scraper for Multiple Sportsbooks

Scrapes player prop lines from FanDuel, DraftKings, BetMGM, and Fanatics
using Selenium to access the actual sportsbook pages.

Includes both standard O/U lines and alternative lines (10, 15, 20, 25, 30, 35, 40 points).
"""

import json
import logging
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)


@dataclass
class PlayerProp:
    """Represents a single player prop line."""
    player_name: str
    team: str
    opponent: str
    game_date: str
    game_time: Optional[str]
    prop_type: str  # 'points', 'rebounds', 'assists', 'pts_rebs_asts', 'threes'
    line: float
    over_odds: Optional[int]  # American odds (-110, +120, etc.)
    under_odds: Optional[int]
    is_alt_line: bool  # True if this is an alternative line
    sportsbook: str
    scraped_at: str


class BaseSportsbookScraper:
    """Base class for sportsbook scrapers using Selenium."""

    SPORTSBOOK_NAME = "base"
    BASE_URL = ""

    # Standard alt lines we want to capture
    ALT_LINES = [10.5, 15.5, 20.5, 25.5, 30.5, 35.5, 40.5]

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver: Optional[webdriver.Chrome] = None

    def _setup_driver(self):
        """Initialize Chrome WebDriver."""
        if self.driver:
            return

        options = Options()
        if self.headless:
            options.add_argument('--headless=new')

        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        # Disable automation flags
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Try cached driver first
        try:
            service = Service(ChromeDriverManager().install())
        except Exception as e:
            cached_driver = os.path.expanduser(
                "~/.wdm/drivers/chromedriver/win64/143.0.7499.192/chromedriver-win32/chromedriver.exe"
            )
            if os.path.exists(cached_driver):
                logger.info(f"Using cached driver: {cached_driver}")
                service = Service(cached_driver)
            else:
                raise e

        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.implicitly_wait(5)

        # Anti-detection
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })

        logger.info(f"{self.SPORTSBOOK_NAME}: WebDriver initialized")

    def _close_driver(self):
        """Close the WebDriver."""
        if self.driver:
            self.driver.quit()
            self.driver = None

    def _random_delay(self, min_sec: float = 1.0, max_sec: float = 2.5):
        """Add a random delay."""
        time.sleep(random.uniform(min_sec, max_sec))

    def scrape_props(self) -> List[PlayerProp]:
        """Scrape all player props. Override in subclass."""
        raise NotImplementedError


class FanDuelScraper(BaseSportsbookScraper):
    """Scraper for FanDuel player props."""

    SPORTSBOOK_NAME = "fanduel"
    BASE_URL = "https://sportsbook.fanduel.com"
    NBA_PROPS_URL = "https://sportsbook.fanduel.com/navigation/nba?tab=player-props"

    def scrape_props(self) -> List[PlayerProp]:
        """Scrape FanDuel NBA player props."""
        props = []

        try:
            self._setup_driver()

            logger.info(f"{self.SPORTSBOOK_NAME}: Navigating to NBA player props...")
            self.driver.get(self.NBA_PROPS_URL)
            self._random_delay(3, 5)

            # Wait for content to load
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-test-id='market-group']"))
                )
            except TimeoutException:
                logger.warning(f"{self.SPORTSBOOK_NAME}: Timeout waiting for props to load")

            # Get page source and parse
            html = self.driver.page_source
            soup = BeautifulSoup(html, 'lxml')

            # Also try to extract embedded JSON data
            props.extend(self._parse_embedded_data(soup))

            # Parse visible prop cards
            props.extend(self._parse_prop_cards(soup))

            logger.info(f"{self.SPORTSBOOK_NAME}: Found {len(props)} props")

        except Exception as e:
            logger.error(f"{self.SPORTSBOOK_NAME}: Error: {e}")
        finally:
            self._close_driver()

        return props

    def _parse_embedded_data(self, soup: BeautifulSoup) -> List[PlayerProp]:
        """Try to parse any embedded JSON data."""
        props = []

        # Look for __NEXT_DATA__ or similar script tags
        for script in soup.find_all('script', type='application/json'):
            try:
                data = json.loads(script.string)
                # Parse the data structure for props
                props.extend(self._extract_props_from_json(data))
            except (json.JSONDecodeError, TypeError):
                continue

        return props

    def _extract_props_from_json(self, data: Any, path: str = "") -> List[PlayerProp]:
        """Recursively extract props from JSON data."""
        props = []

        if isinstance(data, dict):
            # Check if this looks like a player prop
            if 'marketName' in data and 'runners' in data:
                prop = self._parse_market_data(data)
                if prop:
                    props.append(prop)
            else:
                for key, value in data.items():
                    props.extend(self._extract_props_from_json(value, f"{path}.{key}"))

        elif isinstance(data, list):
            for i, item in enumerate(data):
                props.extend(self._extract_props_from_json(item, f"{path}[{i}]"))

        return props

    def _parse_market_data(self, market: Dict) -> Optional[PlayerProp]:
        """Parse a market object into a PlayerProp."""
        try:
            market_name = market.get('marketName', '')

            # Check if it's a player prop we want
            prop_type = self._identify_prop_type(market_name)
            if not prop_type:
                return None

            player_name = self._extract_player_name(market_name)
            if not player_name:
                return None

            line = market.get('line', 0)
            is_alt = 'alt' in market_name.lower() or float(line) in self.ALT_LINES

            runners = market.get('runners', [])
            over_odds = None
            under_odds = None

            for runner in runners:
                runner_name = runner.get('runnerName', '').lower()
                odds = runner.get('winRunnerOdds', {}).get('americanOdds')

                if 'over' in runner_name:
                    over_odds = self._parse_odds(odds)
                elif 'under' in runner_name:
                    under_odds = self._parse_odds(odds)

            return PlayerProp(
                player_name=player_name,
                team='',
                opponent='',
                game_date=datetime.now().strftime('%Y-%m-%d'),
                game_time=None,
                prop_type=prop_type,
                line=float(line) if line else 0,
                over_odds=over_odds,
                under_odds=under_odds,
                is_alt_line=is_alt,
                sportsbook=self.SPORTSBOOK_NAME,
                scraped_at=datetime.now().isoformat()
            )

        except Exception as e:
            logger.debug(f"Error parsing market: {e}")
            return None

    def _parse_prop_cards(self, soup: BeautifulSoup) -> List[PlayerProp]:
        """Parse prop cards from the page HTML."""
        props = []

        # FanDuel uses various class patterns for props
        prop_containers = soup.select('[class*="market-group"], [class*="player-prop"]')

        for container in prop_containers:
            try:
                # Look for player name and line info
                name_elem = container.select_one('[class*="participant"], [class*="player-name"]')
                if not name_elem:
                    continue

                player_name = name_elem.get_text(strip=True)

                # Find line and odds
                line_elem = container.select_one('[class*="line"], [class*="handicap"]')
                line = self._parse_line(line_elem.get_text(strip=True)) if line_elem else None

                odds_elems = container.select('[class*="odds"], [class*="price"]')
                over_odds = None
                under_odds = None

                if len(odds_elems) >= 2:
                    over_odds = self._parse_odds(odds_elems[0].get_text(strip=True))
                    under_odds = self._parse_odds(odds_elems[1].get_text(strip=True))

                if player_name and line:
                    prop = PlayerProp(
                        player_name=player_name,
                        team='',
                        opponent='',
                        game_date=datetime.now().strftime('%Y-%m-%d'),
                        game_time=None,
                        prop_type='points',  # Default, would need more context
                        line=line,
                        over_odds=over_odds,
                        under_odds=under_odds,
                        is_alt_line=line in self.ALT_LINES,
                        sportsbook=self.SPORTSBOOK_NAME,
                        scraped_at=datetime.now().isoformat()
                    )
                    props.append(prop)

            except Exception as e:
                logger.debug(f"Error parsing prop card: {e}")
                continue

        return props

    def _identify_prop_type(self, name: str) -> Optional[str]:
        """Identify prop type from market name."""
        name_lower = name.lower()
        if 'points' in name_lower and 'rebound' not in name_lower and 'assist' not in name_lower:
            return 'points'
        elif 'rebound' in name_lower and 'points' not in name_lower:
            return 'rebounds'
        elif 'assist' in name_lower and 'points' not in name_lower:
            return 'assists'
        elif 'pts' in name_lower and ('reb' in name_lower or 'ast' in name_lower):
            return 'pts_rebs_asts'
        elif 'three' in name_lower or '3pt' in name_lower:
            return 'threes'
        return None

    def _extract_player_name(self, name: str) -> Optional[str]:
        """Extract player name from market name."""
        patterns = [
            r'^([A-Z][a-z]+\.?\s+[A-Z][a-z]+(?:\s+(?:Jr\.|Sr\.|III|IV))?)',
            r'([A-Z]\.\s+[A-Z][a-z]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, name)
            if match:
                return match.group(1).strip()
        return None

    def _parse_line(self, line_str: str) -> Optional[float]:
        """Parse line from string."""
        match = re.search(r'(\d+\.?\d*)', str(line_str))
        if match:
            return float(match.group(1))
        return None

    def _parse_odds(self, odds) -> Optional[int]:
        """Parse odds to integer."""
        if odds is None:
            return None
        try:
            odds_str = str(odds).strip()
            if odds_str.startswith('+'):
                return int(float(odds_str[1:]))
            elif odds_str.startswith('-'):
                return -int(float(odds_str[1:]))
            else:
                return int(float(odds_str))
        except (ValueError, TypeError):
            return None


class DraftKingsScraper(BaseSportsbookScraper):
    """Scraper for DraftKings player props."""

    SPORTSBOOK_NAME = "draftkings"
    BASE_URL = "https://sportsbook.draftkings.com"
    NBA_PROPS_URL = "https://sportsbook.draftkings.com/leagues/basketball/nba?category=player-props&subcategory=points"

    def scrape_props(self) -> List[PlayerProp]:
        """Scrape DraftKings NBA player props."""
        props = []

        try:
            self._setup_driver()

            # Scrape each prop type
            prop_urls = {
                'points': f"{self.BASE_URL}/leagues/basketball/nba?category=player-props&subcategory=points",
                'rebounds': f"{self.BASE_URL}/leagues/basketball/nba?category=player-props&subcategory=rebounds",
                'assists': f"{self.BASE_URL}/leagues/basketball/nba?category=player-props&subcategory=assists",
                'threes': f"{self.BASE_URL}/leagues/basketball/nba?category=player-props&subcategory=3-pointers",
            }

            for prop_type, url in prop_urls.items():
                logger.info(f"{self.SPORTSBOOK_NAME}: Scraping {prop_type}...")
                self.driver.get(url)
                self._random_delay(2, 4)

                # Wait for content
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='sportsbook-outcome']"))
                    )
                except TimeoutException:
                    logger.warning(f"{self.SPORTSBOOK_NAME}: Timeout for {prop_type}")
                    continue

                html = self.driver.page_source
                soup = BeautifulSoup(html, 'lxml')

                props.extend(self._parse_props_page(soup, prop_type))

                # Also try alternate lines
                alt_url = url + "&alternates=true"
                self.driver.get(alt_url)
                self._random_delay(1, 2)

                alt_html = self.driver.page_source
                alt_soup = BeautifulSoup(alt_html, 'lxml')
                alt_props = self._parse_props_page(alt_soup, prop_type)
                for p in alt_props:
                    p.is_alt_line = True
                props.extend(alt_props)

            logger.info(f"{self.SPORTSBOOK_NAME}: Found {len(props)} props")

        except Exception as e:
            logger.error(f"{self.SPORTSBOOK_NAME}: Error: {e}")
        finally:
            self._close_driver()

        return props

    def _parse_props_page(self, soup: BeautifulSoup, prop_type: str) -> List[PlayerProp]:
        """Parse props from a DraftKings page."""
        props = []

        # DraftKings structure: tables with player rows
        tables = soup.select('[class*="sportsbook-table"], [class*="parlay-card"]')

        for table in tables:
            rows = table.select('[class*="sportsbook-row"], tr')

            for row in rows:
                try:
                    # Player name
                    name_elem = row.select_one('[class*="participant"], [class*="player-name"], a')
                    if not name_elem:
                        continue

                    player_name = name_elem.get_text(strip=True)
                    if not player_name or len(player_name) < 3:
                        continue

                    # Line
                    line_elem = row.select_one('[class*="line"], [class*="handicap"]')
                    line = None
                    if line_elem:
                        line = self._parse_line(line_elem.get_text(strip=True))

                    # Odds (Over/Under)
                    odds_elems = row.select('[class*="odds"], [class*="american"]')
                    over_odds = None
                    under_odds = None

                    if len(odds_elems) >= 2:
                        over_odds = self._parse_odds(odds_elems[0].get_text(strip=True))
                        under_odds = self._parse_odds(odds_elems[1].get_text(strip=True))

                    if player_name and (line or over_odds):
                        prop = PlayerProp(
                            player_name=player_name,
                            team='',
                            opponent='',
                            game_date=datetime.now().strftime('%Y-%m-%d'),
                            game_time=None,
                            prop_type=prop_type,
                            line=line if line else 0,
                            over_odds=over_odds,
                            under_odds=under_odds,
                            is_alt_line=False,
                            sportsbook=self.SPORTSBOOK_NAME,
                            scraped_at=datetime.now().isoformat()
                        )
                        props.append(prop)

                except Exception as e:
                    logger.debug(f"Error parsing row: {e}")
                    continue

        return props

    def _parse_line(self, line_str: str) -> Optional[float]:
        """Parse line from string."""
        match = re.search(r'[OUou]?\s*(\d+\.?\d*)', str(line_str))
        if match:
            return float(match.group(1))
        return None

    def _parse_odds(self, odds) -> Optional[int]:
        """Parse odds to integer."""
        if odds is None:
            return None
        try:
            odds_str = str(odds).strip().replace('\u2212', '-')  # Handle unicode minus
            match = re.search(r'([+-]?\d+)', odds_str)
            if match:
                return int(match.group(1))
        except (ValueError, TypeError):
            pass
        return None


class BetMGMScraper(BaseSportsbookScraper):
    """Scraper for BetMGM player props."""

    SPORTSBOOK_NAME = "betmgm"
    BASE_URL = "https://sports.nj.betmgm.com"
    NBA_PROPS_URL = "https://sports.nj.betmgm.com/en/sports/basketball-7/betting/usa-9/nba-6004?tab=player-props"

    def scrape_props(self) -> List[PlayerProp]:
        """Scrape BetMGM NBA player props."""
        props = []

        try:
            self._setup_driver()

            logger.info(f"{self.SPORTSBOOK_NAME}: Navigating to NBA player props...")
            self.driver.get(self.NBA_PROPS_URL)
            self._random_delay(3, 5)

            # Wait for content
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='option-indicator']"))
                )
            except TimeoutException:
                logger.warning(f"{self.SPORTSBOOK_NAME}: Timeout waiting for props")

            html = self.driver.page_source
            soup = BeautifulSoup(html, 'lxml')

            props.extend(self._parse_props_page(soup))

            logger.info(f"{self.SPORTSBOOK_NAME}: Found {len(props)} props")

        except Exception as e:
            logger.error(f"{self.SPORTSBOOK_NAME}: Error: {e}")
        finally:
            self._close_driver()

        return props

    def _parse_props_page(self, soup: BeautifulSoup) -> List[PlayerProp]:
        """Parse props from BetMGM page."""
        props = []

        # BetMGM uses option-panel class for prop groups
        prop_groups = soup.select('[class*="option-panel"], [class*="participant-border"]')

        for group in prop_groups:
            try:
                # Get player name
                name_elem = group.select_one('[class*="participant-name"], [class*="player-name"]')
                if not name_elem:
                    continue

                player_name = name_elem.get_text(strip=True)

                # Get prop type from header
                prop_type = 'points'  # Default
                header = group.find_previous('[class*="header"]')
                if header:
                    header_text = header.get_text(strip=True).lower()
                    if 'rebound' in header_text:
                        prop_type = 'rebounds'
                    elif 'assist' in header_text:
                        prop_type = 'assists'
                    elif 'three' in header_text:
                        prop_type = 'threes'

                # Get line and odds
                line_elem = group.select_one('[class*="line"], [class*="handicap"]')
                line = self._parse_line(line_elem.get_text(strip=True)) if line_elem else None

                odds_elems = group.select('[class*="odds"], [class*="price"]')
                over_odds = None
                under_odds = None

                for elem in odds_elems:
                    text = elem.get_text(strip=True)
                    parent_text = elem.parent.get_text(strip=True).lower() if elem.parent else ''

                    if 'over' in parent_text:
                        over_odds = self._parse_odds(text)
                    elif 'under' in parent_text:
                        under_odds = self._parse_odds(text)
                    elif over_odds is None:
                        over_odds = self._parse_odds(text)
                    elif under_odds is None:
                        under_odds = self._parse_odds(text)

                if player_name and (line or over_odds):
                    prop = PlayerProp(
                        player_name=player_name,
                        team='',
                        opponent='',
                        game_date=datetime.now().strftime('%Y-%m-%d'),
                        game_time=None,
                        prop_type=prop_type,
                        line=line if line else 0,
                        over_odds=over_odds,
                        under_odds=under_odds,
                        is_alt_line=False,
                        sportsbook=self.SPORTSBOOK_NAME,
                        scraped_at=datetime.now().isoformat()
                    )
                    props.append(prop)

            except Exception as e:
                logger.debug(f"Error parsing group: {e}")
                continue

        return props

    def _parse_line(self, line_str: str) -> Optional[float]:
        """Parse line from string."""
        match = re.search(r'(\d+\.?\d*)', str(line_str))
        if match:
            return float(match.group(1))
        return None

    def _parse_odds(self, odds) -> Optional[int]:
        """Parse odds to integer."""
        if odds is None:
            return None
        try:
            odds_str = str(odds).strip().replace('\u2212', '-')
            match = re.search(r'([+-]?\d+)', odds_str)
            if match:
                return int(match.group(1))
        except (ValueError, TypeError):
            pass
        return None


class FanaticsScraper(BaseSportsbookScraper):
    """Scraper for Fanatics Sportsbook player props."""

    SPORTSBOOK_NAME = "fanatics"
    BASE_URL = "https://sportsbook.fanatics.com"
    NBA_PROPS_URL = "https://sportsbook.fanatics.com/basketball/nba?tab=player-props"

    def scrape_props(self) -> List[PlayerProp]:
        """Scrape Fanatics NBA player props."""
        props = []

        try:
            self._setup_driver()

            logger.info(f"{self.SPORTSBOOK_NAME}: Navigating to NBA player props...")
            self.driver.get(self.NBA_PROPS_URL)
            self._random_delay(3, 5)

            # Wait for content
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='market'], [class*='bet-button']"))
                )
            except TimeoutException:
                logger.warning(f"{self.SPORTSBOOK_NAME}: Timeout waiting for props")

            html = self.driver.page_source
            soup = BeautifulSoup(html, 'lxml')

            props.extend(self._parse_props_page(soup))

            logger.info(f"{self.SPORTSBOOK_NAME}: Found {len(props)} props")

        except Exception as e:
            logger.error(f"{self.SPORTSBOOK_NAME}: Error: {e}")
        finally:
            self._close_driver()

        return props

    def _parse_props_page(self, soup: BeautifulSoup) -> List[PlayerProp]:
        """Parse props from Fanatics page."""
        props = []

        # Fanatics structure similar to FanDuel
        prop_rows = soup.select('[class*="market-row"], [class*="player-prop"]')

        for row in prop_rows:
            try:
                name_elem = row.select_one('[class*="player-name"], [class*="participant"]')
                if not name_elem:
                    continue

                player_name = name_elem.get_text(strip=True)

                line_elem = row.select_one('[class*="line"], [class*="handicap"]')
                line = self._parse_line(line_elem.get_text(strip=True)) if line_elem else None

                odds_elems = row.select('[class*="odds"], [class*="price"]')
                over_odds = None
                under_odds = None

                if len(odds_elems) >= 2:
                    over_odds = self._parse_odds(odds_elems[0].get_text(strip=True))
                    under_odds = self._parse_odds(odds_elems[1].get_text(strip=True))

                if player_name and (line or over_odds):
                    prop = PlayerProp(
                        player_name=player_name,
                        team='',
                        opponent='',
                        game_date=datetime.now().strftime('%Y-%m-%d'),
                        game_time=None,
                        prop_type='points',
                        line=line if line else 0,
                        over_odds=over_odds,
                        under_odds=under_odds,
                        is_alt_line=False,
                        sportsbook=self.SPORTSBOOK_NAME,
                        scraped_at=datetime.now().isoformat()
                    )
                    props.append(prop)

            except Exception as e:
                logger.debug(f"Error parsing row: {e}")
                continue

        return props

    def _parse_line(self, line_str: str) -> Optional[float]:
        match = re.search(r'(\d+\.?\d*)', str(line_str))
        if match:
            return float(match.group(1))
        return None

    def _parse_odds(self, odds) -> Optional[int]:
        if odds is None:
            return None
        try:
            odds_str = str(odds).strip().replace('\u2212', '-')
            match = re.search(r'([+-]?\d+)', odds_str)
            if match:
                return int(match.group(1))
        except (ValueError, TypeError):
            pass
        return None


class MultiBookPropsScraper:
    """
    Aggregates player props from multiple sportsbooks.
    """

    SCRAPERS = {
        'fanduel': FanDuelScraper,
        'draftkings': DraftKingsScraper,
        'betmgm': BetMGMScraper,
        'fanatics': FanaticsScraper,
    }

    def __init__(self, output_dir: str = None, books: List[str] = None, headless: bool = True):
        """
        Initialize the multi-book scraper.

        Args:
            output_dir: Directory for output files
            books: List of sportsbooks to scrape (default: all)
            headless: Run browsers in headless mode
        """
        self.output_dir = Path(output_dir) if output_dir else Path("data/output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless

        self.books = books or list(self.SCRAPERS.keys())
        self.books = [b.lower() for b in self.books if b.lower() in self.SCRAPERS]

        logger.info(f"MultiBook scraper initialized with: {self.books}")

    def scrape_all(self) -> Dict[str, List[PlayerProp]]:
        """
        Scrape player props from all configured sportsbooks.

        Note: Runs sequentially to avoid overwhelming resources.
        """
        results = {}

        for book in self.books:
            try:
                logger.info(f"\n{'='*50}")
                logger.info(f"Scraping {book.upper()}...")
                logger.info('='*50)

                scraper_class = self.SCRAPERS[book]
                scraper = scraper_class(headless=self.headless)
                props = scraper.scrape_props()
                results[book] = props

                logger.info(f"{book}: Got {len(props)} props")

            except Exception as e:
                logger.error(f"{book}: Failed with error: {e}")
                results[book] = []

        return results

    def create_comparison_df(self, results: Dict[str, List[PlayerProp]]):
        """Create comparison DataFrame across books."""
        import pandas as pd

        all_props = []
        for book, props in results.items():
            for prop in props:
                all_props.append(asdict(prop))

        if not all_props:
            return pd.DataFrame()

        df = pd.DataFrame(all_props)

        # Normalize player names for matching
        df['player_normalized'] = df['player_name'].str.lower().str.strip()

        # Create pivot for comparison
        pivot = df.pivot_table(
            index=['player_normalized', 'prop_type', 'line', 'game_date'],
            columns='sportsbook',
            values=['over_odds', 'under_odds'],
            aggfunc='first'
        )

        pivot.columns = [f'{col[1]}_{col[0]}' for col in pivot.columns]
        pivot = pivot.reset_index()

        return pivot

    def find_best_odds(self, results: Dict[str, List[PlayerProp]]):
        """Find best odds across all books."""
        comparison = self.create_comparison_df(results)

        if comparison.empty:
            return comparison

        over_cols = [c for c in comparison.columns if 'over_odds' in c]
        under_cols = [c for c in comparison.columns if 'under_odds' in c]

        if over_cols:
            comparison['best_over'] = comparison[over_cols].max(axis=1)
            comparison['best_over_book'] = comparison[over_cols].idxmax(axis=1).str.replace('_over_odds', '')

        if under_cols:
            comparison['best_under'] = comparison[under_cols].max(axis=1)
            comparison['best_under_book'] = comparison[under_cols].idxmax(axis=1).str.replace('_under_odds', '')

        return comparison

    def save_results(self, results: Dict[str, List[PlayerProp]], filename: str = None) -> Path:
        """Save all props to CSV."""
        import pandas as pd

        if filename is None:
            filename = f"player_props_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        all_props = []
        for book, props in results.items():
            for prop in props:
                all_props.append(asdict(prop))

        if not all_props:
            logger.warning("No props to save")
            return None

        df = pd.DataFrame(all_props)
        output_path = self.output_dir / filename
        df.to_csv(output_path, index=False)

        logger.info(f"Saved {len(all_props)} props to {output_path}")
        return output_path


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Scrape NBA player props from multiple sportsbooks')
    parser.add_argument('--books', nargs='+',
                        choices=['fanduel', 'draftkings', 'betmgm', 'fanatics'],
                        default=['fanduel', 'draftkings', 'betmgm', 'fanatics'],
                        help='Sportsbooks to scrape')
    parser.add_argument('--output', type=str, default='data/output',
                        help='Output directory')
    parser.add_argument('--no-headless', action='store_true',
                        help='Run with visible browser')
    parser.add_argument('--compare', action='store_true',
                        help='Also save comparison file')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    scraper = MultiBookPropsScraper(
        output_dir=args.output,
        books=args.books,
        headless=not args.no_headless
    )

    print(f"\nScraping player props from: {scraper.books}")
    print("-" * 50)

    results = scraper.scrape_all()

    # Summary
    print("\n" + "=" * 50)
    print("SCRAPING SUMMARY")
    print("=" * 50)

    total = 0
    for book, props in results.items():
        print(f"  {book.upper()}: {len(props)} props")
        total += len(props)

    print(f"\n  TOTAL: {total} props")

    if total > 0:
        output_path = scraper.save_results(results)
        print(f"\n  Saved to: {output_path}")

        if args.compare:
            import pandas as pd
            comparison = scraper.find_best_odds(results)
            compare_path = scraper.output_dir / f"props_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            comparison.to_csv(compare_path, index=False)
            print(f"  Comparison: {compare_path}")


if __name__ == "__main__":
    main()
