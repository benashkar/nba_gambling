"""
OddsPortal NBA Player Props scraper using Selenium.

Scrapes player prop lines (points, rebounds, assists O/U) from OddsPortal.
"""

import json
import logging
import random
import re
import time
from datetime import datetime, timedelta
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

logger = logging.getLogger(__name__)


class PlayerPropsScraper:
    """Scraper for NBA player props from OddsPortal.com"""

    BASE_URL = "https://www.oddsportal.com"

    # URLs for upcoming/today's games
    UPCOMING_URL = "/basketball/usa/nba/"

    # Prop types to scrape
    PROP_TYPES = {
        'points': 'Player Points',
        'rebounds': 'Player Rebounds',
        'assists': 'Player Assists',
        'pts_rebs_asts': 'Pts + Rebs + Asts',
        'three_pointers': 'Player Threes',
    }

    # Delays (seconds)
    MIN_DELAY = 1.5
    MAX_DELAY = 3.0

    def __init__(
        self,
        headless: bool = True,
        output_dir: Optional[str] = None
    ):
        """
        Initialize the player props scraper.

        Args:
            headless: Run Chrome in headless mode
            output_dir: Directory for saving output data
        """
        self.headless = headless
        self.driver: Optional[webdriver.Chrome] = None

        # Output directory
        self.output_dir = Path(output_dir) if output_dir else Path("data/output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

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

        # Disable images for faster loading
        prefs = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)

        # Disable automation flags
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Try to use cached driver, fall back to download
        try:
            service = Service(ChromeDriverManager().install())
        except Exception as e:
            # Use known cached path as fallback
            import os
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

        # Additional anti-detection
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })

        logger.info("Chrome WebDriver initialized for player props")

    def _close_driver(self):
        """Close the WebDriver."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("Chrome WebDriver closed")

    def _random_delay(self, min_sec: float = None, max_sec: float = None):
        """Add a random delay to avoid detection."""
        min_sec = min_sec or self.MIN_DELAY
        max_sec = max_sec or self.MAX_DELAY
        time.sleep(random.uniform(min_sec, max_sec))

    def get_todays_games(self) -> List[Dict[str, Any]]:
        """
        Get list of today's NBA games with their URLs.

        Returns:
            List of game dictionaries with game_url, home_team, away_team, game_time
        """
        self._setup_driver()

        url = f"{self.BASE_URL}{self.UPCOMING_URL}"
        logger.info(f"Fetching today's games from {url}")

        self.driver.get(url)
        self._random_delay(2, 4)

        # Wait for games to load
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.eventRow"))
            )
        except TimeoutException:
            logger.warning("Timeout waiting for games to load")
            return []

        html = self.driver.page_source
        soup = BeautifulSoup(html, 'lxml')

        games = []
        game_rows = soup.select('div.eventRow')

        for row in game_rows:
            try:
                game = self._parse_upcoming_game(row)
                if game:
                    games.append(game)
            except Exception as e:
                logger.error(f"Error parsing game row: {e}")
                continue

        logger.info(f"Found {len(games)} upcoming games")
        return games

    def _parse_upcoming_game(self, row) -> Optional[Dict[str, Any]]:
        """Parse an upcoming game row."""
        game = {
            'game_url': None,
            'home_team': None,
            'away_team': None,
            'game_time': None,
            'game_date': datetime.now().strftime('%Y-%m-%d')
        }

        # Extract teams
        team_elems = row.select('p.participant-name')
        if len(team_elems) >= 2:
            game['away_team'] = team_elems[0].get_text(strip=True)
            game['home_team'] = team_elems[1].get_text(strip=True)

        # Extract game URL
        for link in row.select('a[href*="/basketball/usa/nba"]'):
            href = link.get('href', '')
            if href and re.search(r'-[A-Za-z0-9]{8}/$', href):
                game['game_url'] = href
                break

        # Extract game time
        time_elem = row.select_one('p.whitespace-nowrap')
        if time_elem:
            game['game_time'] = time_elem.get_text(strip=True)

        if game['game_url'] and game['home_team'] and game['away_team']:
            return game
        return None

    def scrape_game_player_props(self, game_url: str) -> List[Dict[str, Any]]:
        """
        Scrape player props for a specific game.

        Args:
            game_url: OddsPortal game URL (relative or absolute)

        Returns:
            List of player prop dictionaries
        """
        # Reuse existing driver if available
        if not self.driver:
            self._setup_driver()

        # Ensure absolute URL
        if not game_url.startswith('http'):
            game_url = f"{self.BASE_URL}{game_url}"

        # Navigate to player props tab
        # OddsPortal player props are typically at game_url + #player-props or similar
        props_url = game_url.rstrip('/') + '/#player-props;pn=1'

        logger.info(f"Fetching player props from {props_url}")
        self.driver.get(props_url)
        self._random_delay(2, 4)

        all_props = []

        # Try to find and click on different prop categories
        for prop_type, prop_name in self.PROP_TYPES.items():
            try:
                props = self._scrape_prop_category(prop_type, prop_name, game_url)
                all_props.extend(props)
            except Exception as e:
                logger.error(f"Error scraping {prop_type}: {e}")
                continue

        return all_props

    def _scrape_prop_category(
        self,
        prop_type: str,
        prop_name: str,
        game_url: str
    ) -> List[Dict[str, Any]]:
        """
        Scrape a specific prop category (points, rebounds, etc.)

        Args:
            prop_type: Internal prop type key
            prop_name: Display name to search for
            game_url: Game URL for reference

        Returns:
            List of prop dictionaries
        """
        props = []

        # Try to find the prop category tab/link
        try:
            # Look for tabs or links containing the prop name
            prop_links = self.driver.find_elements(
                By.XPATH,
                f"//a[contains(text(), '{prop_name}')] | //span[contains(text(), '{prop_name}')]"
            )

            if prop_links:
                prop_links[0].click()
                self._random_delay(1, 2)
        except Exception as e:
            logger.debug(f"Could not find/click {prop_name} tab: {e}")

        # Parse the current page for player props
        html = self.driver.page_source
        soup = BeautifulSoup(html, 'lxml')

        # Look for player prop rows
        # OddsPortal structure varies, try multiple selectors
        prop_rows = soup.select('div.player-prop-row, div[class*="player"], tr[class*="prop"]')

        if not prop_rows:
            # Try alternate structure - look for player names with odds
            prop_rows = soup.select('div.flex.items-center')

        for row in prop_rows:
            try:
                prop = self._parse_prop_row(row, prop_type, game_url)
                if prop:
                    props.append(prop)
            except Exception as e:
                logger.debug(f"Error parsing prop row: {e}")
                continue

        logger.info(f"  Found {len(props)} {prop_type} props")
        return props

    def _parse_prop_row(
        self,
        row,
        prop_type: str,
        game_url: str
    ) -> Optional[Dict[str, Any]]:
        """Parse a single player prop row."""
        prop = {
            'player_name': None,
            'prop_type': prop_type,
            'line': None,
            'over_odds': None,
            'under_odds': None,
            'game_url': game_url,
            'scraped_at': datetime.now().isoformat()
        }

        # Try to extract player name
        name_elem = row.select_one('span.player-name, a.player-name, span[class*="participant"]')
        if name_elem:
            prop['player_name'] = name_elem.get_text(strip=True)
        else:
            # Try to find any text that looks like a player name
            text_elems = row.select('span, a')
            for elem in text_elems:
                text = elem.get_text(strip=True)
                # Player names typically have format "First Last" or "F. Last"
                if re.match(r'^[A-Z][a-z]*\.?\s+[A-Z][a-z]+$', text):
                    prop['player_name'] = text
                    break

        if not prop['player_name']:
            return None

        # Try to extract line (e.g., "24.5")
        line_elems = row.select('span[class*="line"], span[class*="handicap"]')
        for elem in line_elems:
            text = elem.get_text(strip=True)
            try:
                prop['line'] = float(text.replace('O ', '').replace('U ', ''))
                break
            except ValueError:
                continue

        # Try to extract odds
        odds_elems = row.select('span[class*="odds"], p[class*="odds"]')
        if len(odds_elems) >= 2:
            try:
                prop['over_odds'] = self._parse_odds(odds_elems[0].get_text(strip=True))
                prop['under_odds'] = self._parse_odds(odds_elems[1].get_text(strip=True))
            except (ValueError, IndexError):
                pass

        # Only return if we have meaningful data
        if prop['player_name'] and (prop['line'] or prop['over_odds']):
            return prop
        return None

    def _parse_odds(self, odds_str: str) -> Optional[float]:
        """Parse odds string to numeric value."""
        if not odds_str or odds_str in ['-', '']:
            return None
        try:
            # Handle American odds format (+110, -115)
            odds_str = odds_str.strip()
            if odds_str.startswith('+'):
                return float(odds_str)
            elif odds_str.startswith('-'):
                return float(odds_str)
            else:
                # Might be decimal odds
                return float(odds_str)
        except ValueError:
            return None

    def scrape_todays_props(self) -> List[Dict[str, Any]]:
        """
        Scrape all player props for today's games.

        Returns:
            List of all player prop dictionaries
        """
        all_props = []

        try:
            self._setup_driver()

            # Get today's games
            games = self.get_todays_games()
            logger.info(f"Scraping props for {len(games)} games")

            for i, game in enumerate(games):
                logger.info(f"Scraping game {i+1}/{len(games)}: {game['away_team']} @ {game['home_team']}")

                try:
                    props = self.scrape_game_player_props(game['game_url'])

                    # Add game context to each prop
                    for prop in props:
                        prop['home_team'] = game['home_team']
                        prop['away_team'] = game['away_team']
                        prop['game_date'] = game['game_date']
                        prop['game_time'] = game.get('game_time')

                    all_props.extend(props)

                except Exception as e:
                    logger.error(f"Error scraping props for {game['away_team']} @ {game['home_team']}: {e}")
                    continue

                self._random_delay(2, 4)

        finally:
            self._close_driver()

        return all_props

    def save_props(self, props: List[Dict[str, Any]], filename: str = None):
        """
        Save props to CSV file.

        Args:
            props: List of prop dictionaries
            filename: Output filename (default: player_props_YYYYMMDD.csv)
        """
        if not props:
            logger.warning("No props to save")
            return

        import pandas as pd

        if filename is None:
            filename = f"player_props_{datetime.now().strftime('%Y%m%d')}.csv"

        output_path = self.output_dir / filename

        df = pd.DataFrame(props)
        df.to_csv(output_path, index=False)

        logger.info(f"Saved {len(props)} props to {output_path}")

        return output_path


def main():
    """Main entry point for player props scraper."""
    import argparse

    parser = argparse.ArgumentParser(description='Scrape NBA player props from OddsPortal')
    parser.add_argument('--headless', action='store_true', default=True,
                        help='Run in headless mode (default: True)')
    parser.add_argument('--no-headless', action='store_true',
                        help='Run with visible browser')
    parser.add_argument('--output', type=str, default='data/output',
                        help='Output directory')
    parser.add_argument('--game-url', type=str,
                        help='Scrape props for a specific game URL')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    headless = args.headless and not args.no_headless

    scraper = PlayerPropsScraper(
        headless=headless,
        output_dir=args.output
    )

    if args.game_url:
        # Scrape specific game
        props = scraper.scrape_game_player_props(args.game_url)
    else:
        # Scrape all today's games
        props = scraper.scrape_todays_props()

    if props:
        scraper.save_props(props)
        print(f"Scraped {len(props)} player props")
    else:
        print("No props found")


if __name__ == "__main__":
    main()
