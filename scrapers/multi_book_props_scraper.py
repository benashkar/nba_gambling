"""
Multi-Sportsbook NBA Player Props Scraper

Scrapes player prop lines from:
- FanDuel
- DraftKings
- BetMGM
- Fanatics

Includes both standard O/U lines and alternative lines (10, 15, 20, 25, 30, 35, 40 points).
"""

import json
import logging
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

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


class FanDuelScraper:
    """Scraper for FanDuel player props using their public API."""

    BASE_URL = "https://sportsbook.fanduel.com"
    API_URL = "https://sbapi.nj.sportsbook.fanduel.com/api"

    # FanDuel market types for player props
    MARKET_TYPES = {
        'points': 'Player Points',
        'rebounds': 'Player Rebounds',
        'assists': 'Player Assists',
        'pts_rebs_asts': 'Pts + Rebs + Asts',
        'threes': 'Player Threes Made',
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
        })

    def get_nba_events(self) -> List[Dict]:
        """Get today's NBA games from FanDuel."""
        try:
            # FanDuel API endpoint for NBA
            url = f"{self.API_URL}/content-managed-page"
            params = {
                'page': 'SPORT',
                'sportId': '5',  # Basketball
                '_ak': 'FhMFpcPWXMeyZxOx',
                'timezone': 'America/Chicago',
            }

            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            events = []
            # Parse the response structure for NBA events
            if 'attachments' in data and 'events' in data['attachments']:
                for event_id, event in data['attachments']['events'].items():
                    if 'NBA' in event.get('competitionName', ''):
                        events.append({
                            'event_id': event_id,
                            'name': event.get('name'),
                            'openDate': event.get('openDate'),
                            'home_team': event.get('homeTeamName'),
                            'away_team': event.get('awayTeamName'),
                        })

            logger.info(f"FanDuel: Found {len(events)} NBA events")
            return events

        except Exception as e:
            logger.error(f"FanDuel: Error getting events: {e}")
            return []

    def get_player_props(self, event_id: str) -> List[PlayerProp]:
        """Get player props for a specific game."""
        props = []

        try:
            url = f"{self.API_URL}/event-page"
            params = {
                'eventId': event_id,
                '_ak': 'FhMFpcPWXMeyZxOx',
                'timezone': 'America/Chicago',
            }

            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # Parse markets from response
            markets = data.get('attachments', {}).get('markets', {})

            for market_id, market in markets.items():
                market_name = market.get('marketName', '')

                # Check if it's a player prop market we want
                prop_type = self._identify_prop_type(market_name)
                if not prop_type:
                    continue

                # Extract runners (over/under options)
                runners = market.get('runners', [])
                if len(runners) >= 2:
                    player_name = self._extract_player_name(market_name)
                    if not player_name:
                        continue

                    line = market.get('line', 0)
                    is_alt = 'alt' in market_name.lower() or 'alternative' in market_name.lower()

                    # Get over/under odds
                    over_odds = None
                    under_odds = None

                    for runner in runners:
                        if 'over' in runner.get('runnerName', '').lower():
                            over_odds = self._decimal_to_american(runner.get('winRunnerOdds', {}).get('americanOdds'))
                        elif 'under' in runner.get('runnerName', '').lower():
                            under_odds = self._decimal_to_american(runner.get('winRunnerOdds', {}).get('americanOdds'))

                    prop = PlayerProp(
                        player_name=player_name,
                        team='',  # Will be filled from event data
                        opponent='',
                        game_date=datetime.now().strftime('%Y-%m-%d'),
                        game_time=None,
                        prop_type=prop_type,
                        line=float(line) if line else 0,
                        over_odds=over_odds,
                        under_odds=under_odds,
                        is_alt_line=is_alt,
                        sportsbook='fanduel',
                        scraped_at=datetime.now().isoformat()
                    )
                    props.append(prop)

            logger.info(f"FanDuel: Found {len(props)} props for event {event_id}")

        except Exception as e:
            logger.error(f"FanDuel: Error getting props for event {event_id}: {e}")

        return props

    def _identify_prop_type(self, market_name: str) -> Optional[str]:
        """Identify the prop type from market name."""
        market_lower = market_name.lower()

        if 'points' in market_lower and 'rebound' not in market_lower and 'assist' not in market_lower:
            return 'points'
        elif 'rebound' in market_lower and 'points' not in market_lower:
            return 'rebounds'
        elif 'assist' in market_lower and 'points' not in market_lower:
            return 'assists'
        elif 'pts' in market_lower and 'reb' in market_lower and 'ast' in market_lower:
            return 'pts_rebs_asts'
        elif 'three' in market_lower or '3-pointer' in market_lower or '3pt' in market_lower:
            return 'threes'

        return None

    def _extract_player_name(self, market_name: str) -> Optional[str]:
        """Extract player name from market name."""
        # Common patterns: "LeBron James - Points O/U", "J. Brunson Points"
        patterns = [
            r'^([A-Z][a-z]+\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*[-–]',
            r'^([A-Z][a-z]+\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:Points|Rebounds|Assists)',
        ]

        for pattern in patterns:
            match = re.search(pattern, market_name)
            if match:
                return match.group(1).strip()

        return None

    def _decimal_to_american(self, odds) -> Optional[int]:
        """Convert decimal/raw odds to American format."""
        if odds is None:
            return None
        try:
            if isinstance(odds, (int, float)):
                return int(odds)
            return int(float(odds))
        except (ValueError, TypeError):
            return None

    def scrape_all_props(self) -> List[PlayerProp]:
        """Scrape all player props for today's games."""
        all_props = []

        events = self.get_nba_events()

        for event in events:
            props = self.get_player_props(event['event_id'])

            # Add team info to props
            for prop in props:
                prop.team = event.get('home_team', '') or event.get('away_team', '')
                prop.opponent = event.get('away_team', '') or event.get('home_team', '')

            all_props.extend(props)
            time.sleep(random.uniform(0.5, 1.5))  # Rate limiting

        return all_props


class DraftKingsScraper:
    """Scraper for DraftKings player props using their API."""

    API_URL = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1/leagues/42648"  # NBA

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
        })

    def get_nba_events(self) -> List[Dict]:
        """Get today's NBA games from DraftKings."""
        try:
            url = f"{self.API_URL}/events"
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            events = []
            for event in data.get('events', []):
                events.append({
                    'event_id': event.get('eventId'),
                    'name': event.get('name'),
                    'startDate': event.get('startDate'),
                    'home_team': event.get('homeTeamName'),
                    'away_team': event.get('awayTeamName'),
                })

            logger.info(f"DraftKings: Found {len(events)} NBA events")
            return events

        except Exception as e:
            logger.error(f"DraftKings: Error getting events: {e}")
            return []

    def get_player_props(self, event_id: str) -> List[PlayerProp]:
        """Get player props for a specific game."""
        props = []

        try:
            # DraftKings player props endpoint
            url = f"https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1/events/{event_id}/categories/1215"  # Player Props category

            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # Parse subcategories and offers
            for subcategory in data.get('subcategories', []):
                subcat_name = subcategory.get('name', '')
                prop_type = self._identify_prop_type(subcat_name)

                if not prop_type:
                    continue

                for offer in subcategory.get('offers', []):
                    player_name = offer.get('label', '')
                    line = offer.get('line', 0)
                    is_alt = 'alt' in subcat_name.lower()

                    outcomes = offer.get('outcomes', [])
                    over_odds = None
                    under_odds = None

                    for outcome in outcomes:
                        if outcome.get('label', '').lower() == 'over':
                            over_odds = outcome.get('oddsAmerican')
                        elif outcome.get('label', '').lower() == 'under':
                            under_odds = outcome.get('oddsAmerican')

                    if player_name and line:
                        prop = PlayerProp(
                            player_name=player_name,
                            team='',
                            opponent='',
                            game_date=datetime.now().strftime('%Y-%m-%d'),
                            game_time=None,
                            prop_type=prop_type,
                            line=float(line),
                            over_odds=self._parse_odds(over_odds),
                            under_odds=self._parse_odds(under_odds),
                            is_alt_line=is_alt,
                            sportsbook='draftkings',
                            scraped_at=datetime.now().isoformat()
                        )
                        props.append(prop)

            logger.info(f"DraftKings: Found {len(props)} props for event {event_id}")

        except Exception as e:
            logger.error(f"DraftKings: Error getting props for event {event_id}: {e}")

        return props

    def _identify_prop_type(self, name: str) -> Optional[str]:
        """Identify prop type from subcategory name."""
        name_lower = name.lower()

        if 'points' in name_lower and 'rebound' not in name_lower:
            return 'points'
        elif 'rebound' in name_lower:
            return 'rebounds'
        elif 'assist' in name_lower:
            return 'assists'
        elif 'combo' in name_lower or 'pts+' in name_lower:
            return 'pts_rebs_asts'
        elif 'three' in name_lower or '3pt' in name_lower:
            return 'threes'

        return None

    def _parse_odds(self, odds) -> Optional[int]:
        """Parse odds to integer."""
        if odds is None:
            return None
        try:
            if isinstance(odds, str):
                odds = odds.replace('+', '')
            return int(float(odds))
        except (ValueError, TypeError):
            return None

    def scrape_all_props(self) -> List[PlayerProp]:
        """Scrape all player props for today's games."""
        all_props = []

        events = self.get_nba_events()

        for event in events:
            props = self.get_player_props(event['event_id'])

            for prop in props:
                prop.team = event.get('home_team', '')
                prop.opponent = event.get('away_team', '')

            all_props.extend(props)
            time.sleep(random.uniform(0.5, 1.5))

        return all_props


class BetMGMScraper:
    """Scraper for BetMGM player props using their API."""

    API_URL = "https://sports.nj.betmgm.com/cds-api/bettingoffer/fixtures"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
        })

    def get_nba_events(self) -> List[Dict]:
        """Get today's NBA games from BetMGM."""
        try:
            params = {
                'x-bwin-accessid': 'NjJkNTIxMzgtYjkxMS00MzY3LWEyODYtZWFlZGE5MWJhODE1',
                'lang': 'en-us',
                'country': 'US',
                'userCountry': 'US',
                'state': 'NJ',
                'offerMapping': 'All',
                'sportIds': '7',  # Basketball
                'regionIds': '9',  # USA
                'competitionIds': '6004',  # NBA
            }

            resp = self.session.get(self.API_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            events = []
            for fixture in data.get('fixtures', []):
                events.append({
                    'event_id': fixture.get('id'),
                    'name': fixture.get('name', {}).get('value'),
                    'startDate': fixture.get('startDate'),
                    'participants': fixture.get('participants', []),
                })

            logger.info(f"BetMGM: Found {len(events)} NBA events")
            return events

        except Exception as e:
            logger.error(f"BetMGM: Error getting events: {e}")
            return []

    def get_player_props(self, event_id: str) -> List[PlayerProp]:
        """Get player props for a specific game."""
        props = []

        try:
            url = f"https://sports.nj.betmgm.com/cds-api/bettingoffer/fixture-view"
            params = {
                'x-bwin-accessid': 'NjJkNTIxMzgtYjkxMS00MzY3LWEyODYtZWFlZGE5MWJhODE1',
                'lang': 'en-us',
                'country': 'US',
                'state': 'NJ',
                'fixtureIds': event_id,
            }

            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # Parse games array for player props
            for fixture in data.get('fixture', []):
                for game in fixture.get('games', []):
                    game_name = game.get('name', {}).get('value', '')
                    prop_type = self._identify_prop_type(game_name)

                    if not prop_type:
                        continue

                    player_name = self._extract_player_name(game_name)
                    if not player_name:
                        continue

                    is_alt = 'alt' in game_name.lower()

                    for result in game.get('results', []):
                        line = result.get('name', {}).get('value', '')
                        odds = result.get('americanOdds')

                        # Parse line value
                        line_val = self._parse_line(line)
                        if line_val is None:
                            continue

                        # Determine over/under
                        is_over = 'over' in line.lower() or '+' in line

                        # For BetMGM, we might get separate over/under results
                        # Group them together
                        existing_prop = next(
                            (p for p in props if p.player_name == player_name
                             and p.prop_type == prop_type and p.line == line_val),
                            None
                        )

                        if existing_prop:
                            if is_over:
                                existing_prop.over_odds = self._parse_odds(odds)
                            else:
                                existing_prop.under_odds = self._parse_odds(odds)
                        else:
                            prop = PlayerProp(
                                player_name=player_name,
                                team='',
                                opponent='',
                                game_date=datetime.now().strftime('%Y-%m-%d'),
                                game_time=None,
                                prop_type=prop_type,
                                line=line_val,
                                over_odds=self._parse_odds(odds) if is_over else None,
                                under_odds=self._parse_odds(odds) if not is_over else None,
                                is_alt_line=is_alt,
                                sportsbook='betmgm',
                                scraped_at=datetime.now().isoformat()
                            )
                            props.append(prop)

            logger.info(f"BetMGM: Found {len(props)} props for event {event_id}")

        except Exception as e:
            logger.error(f"BetMGM: Error getting props for event {event_id}: {e}")

        return props

    def _identify_prop_type(self, name: str) -> Optional[str]:
        """Identify prop type from game name."""
        name_lower = name.lower()

        if 'points' in name_lower and 'rebound' not in name_lower:
            return 'points'
        elif 'rebound' in name_lower:
            return 'rebounds'
        elif 'assist' in name_lower:
            return 'assists'
        elif 'pts+reb+ast' in name_lower or 'combo' in name_lower:
            return 'pts_rebs_asts'
        elif 'three' in name_lower or '3-point' in name_lower:
            return 'threes'

        return None

    def _extract_player_name(self, name: str) -> Optional[str]:
        """Extract player name from game name."""
        # BetMGM format: "Player Name - Points O/U"
        match = re.search(r'^([A-Z][a-z]+\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', name)
        if match:
            return match.group(1).strip()
        return None

    def _parse_line(self, line_str: str) -> Optional[float]:
        """Parse line value from string."""
        match = re.search(r'(\d+\.?\d*)', str(line_str))
        if match:
            return float(match.group(1))
        return None

    def _parse_odds(self, odds) -> Optional[int]:
        """Parse odds to integer."""
        if odds is None:
            return None
        try:
            return int(float(odds))
        except (ValueError, TypeError):
            return None

    def scrape_all_props(self) -> List[PlayerProp]:
        """Scrape all player props for today's games."""
        all_props = []

        events = self.get_nba_events()

        for event in events:
            props = self.get_player_props(event['event_id'])
            all_props.extend(props)
            time.sleep(random.uniform(0.5, 1.5))

        return all_props


class FanaticsScraper:
    """Scraper for Fanatics Sportsbook player props."""

    # Fanatics uses similar infrastructure to PointsBet (they acquired them)
    API_URL = "https://api.fanatics.sportsbook.com/api/v1"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
        })

    def get_nba_events(self) -> List[Dict]:
        """Get today's NBA games from Fanatics."""
        try:
            # Fanatics NBA endpoint
            url = f"{self.API_URL}/sports/basketball/leagues/nba/events"

            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            events = []
            for event in data.get('events', []):
                events.append({
                    'event_id': event.get('id'),
                    'name': event.get('name'),
                    'startTime': event.get('startTime'),
                    'home_team': event.get('homeTeam', {}).get('name'),
                    'away_team': event.get('awayTeam', {}).get('name'),
                })

            logger.info(f"Fanatics: Found {len(events)} NBA events")
            return events

        except Exception as e:
            logger.error(f"Fanatics: Error getting events: {e}")
            return []

    def get_player_props(self, event_id: str) -> List[PlayerProp]:
        """Get player props for a specific game."""
        props = []

        try:
            url = f"{self.API_URL}/events/{event_id}/markets"
            params = {'marketType': 'player_props'}

            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            for market in data.get('markets', []):
                market_name = market.get('name', '')
                prop_type = self._identify_prop_type(market_name)

                if not prop_type:
                    continue

                player_name = market.get('playerName', '') or self._extract_player_name(market_name)
                line = market.get('line', 0)
                is_alt = market.get('isAlternate', False) or 'alt' in market_name.lower()

                outcomes = market.get('outcomes', [])
                over_odds = None
                under_odds = None

                for outcome in outcomes:
                    if 'over' in outcome.get('name', '').lower():
                        over_odds = outcome.get('americanOdds')
                    elif 'under' in outcome.get('name', '').lower():
                        under_odds = outcome.get('americanOdds')

                if player_name:
                    prop = PlayerProp(
                        player_name=player_name,
                        team='',
                        opponent='',
                        game_date=datetime.now().strftime('%Y-%m-%d'),
                        game_time=None,
                        prop_type=prop_type,
                        line=float(line) if line else 0,
                        over_odds=self._parse_odds(over_odds),
                        under_odds=self._parse_odds(under_odds),
                        is_alt_line=is_alt,
                        sportsbook='fanatics',
                        scraped_at=datetime.now().isoformat()
                    )
                    props.append(prop)

            logger.info(f"Fanatics: Found {len(props)} props for event {event_id}")

        except Exception as e:
            logger.error(f"Fanatics: Error getting props for event {event_id}: {e}")

        return props

    def _identify_prop_type(self, name: str) -> Optional[str]:
        """Identify prop type from market name."""
        name_lower = name.lower()

        if 'points' in name_lower and 'rebound' not in name_lower:
            return 'points'
        elif 'rebound' in name_lower:
            return 'rebounds'
        elif 'assist' in name_lower:
            return 'assists'
        elif 'combo' in name_lower or 'pra' in name_lower:
            return 'pts_rebs_asts'
        elif 'three' in name_lower or '3pt' in name_lower:
            return 'threes'

        return None

    def _extract_player_name(self, name: str) -> Optional[str]:
        """Extract player name from market name."""
        match = re.search(r'^([A-Z][a-z]+\.?\s+[A-Z][a-z]+)', name)
        if match:
            return match.group(1).strip()
        return None

    def _parse_odds(self, odds) -> Optional[int]:
        """Parse odds to integer."""
        if odds is None:
            return None
        try:
            return int(float(odds))
        except (ValueError, TypeError):
            return None

    def scrape_all_props(self) -> List[PlayerProp]:
        """Scrape all player props for today's games."""
        all_props = []

        events = self.get_nba_events()

        for event in events:
            props = self.get_player_props(event['event_id'])

            for prop in props:
                prop.team = event.get('home_team', '')
                prop.opponent = event.get('away_team', '')

            all_props.extend(props)
            time.sleep(random.uniform(0.5, 1.5))

        return all_props


class MultiBookPropsScraper:
    """
    Main scraper that aggregates player props from multiple sportsbooks.
    """

    SCRAPERS = {
        'fanduel': FanDuelScraper,
        'draftkings': DraftKingsScraper,
        'betmgm': BetMGMScraper,
        'fanatics': FanaticsScraper,
    }

    def __init__(self, output_dir: str = None, books: List[str] = None):
        """
        Initialize the multi-book scraper.

        Args:
            output_dir: Directory for output files
            books: List of sportsbooks to scrape (default: all)
        """
        self.output_dir = Path(output_dir) if output_dir else Path("data/output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Filter to requested books
        self.books = books or list(self.SCRAPERS.keys())
        self.books = [b.lower() for b in self.books if b.lower() in self.SCRAPERS]

        logger.info(f"Initialized with books: {self.books}")

    def scrape_all(self, parallel: bool = True) -> Dict[str, List[PlayerProp]]:
        """
        Scrape player props from all configured sportsbooks.

        Args:
            parallel: Whether to scrape books in parallel

        Returns:
            Dictionary mapping sportsbook name to list of props
        """
        results = {}

        if parallel:
            with ThreadPoolExecutor(max_workers=len(self.books)) as executor:
                futures = {}
                for book in self.books:
                    scraper = self.SCRAPERS[book]()
                    futures[executor.submit(scraper.scrape_all_props)] = book

                for future in as_completed(futures):
                    book = futures[future]
                    try:
                        props = future.result()
                        results[book] = props
                        logger.info(f"{book}: Scraped {len(props)} props")
                    except Exception as e:
                        logger.error(f"{book}: Scraping failed: {e}")
                        results[book] = []
        else:
            for book in self.books:
                try:
                    scraper = self.SCRAPERS[book]()
                    props = scraper.scrape_all_props()
                    results[book] = props
                    logger.info(f"{book}: Scraped {len(props)} props")
                except Exception as e:
                    logger.error(f"{book}: Scraping failed: {e}")
                    results[book] = []

        return results

    def create_comparison_df(self, results: Dict[str, List[PlayerProp]]) -> 'pd.DataFrame':
        """
        Create a DataFrame comparing props across sportsbooks.

        Args:
            results: Dictionary of sportsbook -> props

        Returns:
            DataFrame with one row per player/prop/line, columns for each book's odds
        """
        import pandas as pd

        # Flatten all props
        all_props = []
        for book, props in results.items():
            for prop in props:
                all_props.append(asdict(prop))

        if not all_props:
            return pd.DataFrame()

        df = pd.DataFrame(all_props)

        # Create pivot table for comparison
        pivot_df = df.pivot_table(
            index=['player_name', 'prop_type', 'line', 'is_alt_line', 'game_date'],
            columns='sportsbook',
            values=['over_odds', 'under_odds'],
            aggfunc='first'
        )

        # Flatten column names
        pivot_df.columns = [f'{col[1]}_{col[0]}' for col in pivot_df.columns]
        pivot_df = pivot_df.reset_index()

        return pivot_df

    def find_best_odds(self, results: Dict[str, List[PlayerProp]]) -> 'pd.DataFrame':
        """
        Find the best over/under odds across all books for each prop.

        Args:
            results: Dictionary of sportsbook -> props

        Returns:
            DataFrame with best odds and which book has them
        """
        import pandas as pd

        comparison_df = self.create_comparison_df(results)

        if comparison_df.empty:
            return comparison_df

        # Find best over odds (highest positive or least negative)
        over_cols = [c for c in comparison_df.columns if 'over_odds' in c]
        under_cols = [c for c in comparison_df.columns if 'under_odds' in c]

        if over_cols:
            comparison_df['best_over_odds'] = comparison_df[over_cols].max(axis=1)
            comparison_df['best_over_book'] = comparison_df[over_cols].idxmax(axis=1).str.replace('_over_odds', '')

        if under_cols:
            comparison_df['best_under_odds'] = comparison_df[under_cols].max(axis=1)
            comparison_df['best_under_book'] = comparison_df[under_cols].idxmax(axis=1).str.replace('_under_odds', '')

        return comparison_df

    def save_results(self, results: Dict[str, List[PlayerProp]], filename: str = None) -> Path:
        """
        Save scraped props to CSV.

        Args:
            results: Dictionary of sportsbook -> props
            filename: Output filename (default: player_props_YYYYMMDD.csv)

        Returns:
            Path to saved file
        """
        import pandas as pd

        if filename is None:
            filename = f"player_props_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        # Flatten all props
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

    def save_comparison(self, results: Dict[str, List[PlayerProp]], filename: str = None) -> Path:
        """
        Save comparison DataFrame to CSV.

        Args:
            results: Dictionary of sportsbook -> props
            filename: Output filename

        Returns:
            Path to saved file
        """
        if filename is None:
            filename = f"props_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        comparison_df = self.find_best_odds(results)

        if comparison_df.empty:
            logger.warning("No comparison data to save")
            return None

        output_path = self.output_dir / filename
        comparison_df.to_csv(output_path, index=False)

        logger.info(f"Saved comparison to {output_path}")
        return output_path


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Scrape NBA player props from multiple sportsbooks')
    parser.add_argument('--books', nargs='+',
                        choices=['fanduel', 'draftkings', 'betmgm', 'fanatics'],
                        help='Sportsbooks to scrape (default: all)')
    parser.add_argument('--output', type=str, default='data/output',
                        help='Output directory')
    parser.add_argument('--no-parallel', action='store_true',
                        help='Scrape sequentially instead of in parallel')
    parser.add_argument('--compare', action='store_true',
                        help='Also save comparison file with best odds')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    scraper = MultiBookPropsScraper(
        output_dir=args.output,
        books=args.books
    )

    print(f"\nScraping player props from: {scraper.books}")
    print("-" * 50)

    results = scraper.scrape_all(parallel=not args.no_parallel)

    # Summary
    print("\n" + "=" * 50)
    print("SCRAPING SUMMARY")
    print("=" * 50)

    total_props = 0
    for book, props in results.items():
        print(f"  {book.upper()}: {len(props)} props")
        total_props += len(props)

    print(f"\n  TOTAL: {total_props} props")

    # Save results
    if total_props > 0:
        output_path = scraper.save_results(results)
        print(f"\n  Saved to: {output_path}")

        if args.compare:
            compare_path = scraper.save_comparison(results)
            print(f"  Comparison: {compare_path}")
    else:
        print("\n  No props found to save")


if __name__ == "__main__":
    main()
