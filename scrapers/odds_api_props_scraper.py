"""
The Odds API - NBA Player Props Scraper

Uses The Odds API to get player prop lines from multiple sportsbooks:
- FanDuel
- DraftKings
- BetMGM
- (Fanatics not yet available on this API)

Includes both standard O/U lines and alternate lines.

API Documentation: https://the-odds-api.com/liveapi/guides/v4/
Free tier: 500 requests/month
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import requests

logger = logging.getLogger(__name__)


@dataclass
class PlayerProp:
    """Represents a single player prop line."""
    player_name: str
    team: str
    opponent: str
    game_id: str
    game_date: str
    game_time: Optional[str]
    prop_type: str  # 'points', 'rebounds', 'assists', 'pts_rebs_asts', 'threes'
    line: float
    over_odds: Optional[int]  # American odds
    under_odds: Optional[int]
    is_alt_line: bool
    sportsbook: str
    scraped_at: str


class OddsAPIPropsScraper:
    """
    Scraper for NBA player props using The Odds API.

    Covers: FanDuel, DraftKings, BetMGM
    """

    SPORT = "basketball_nba"

    # Sportsbook keys in the API
    BOOKMAKERS = {
        'fanduel': 'fanduel',
        'draftkings': 'draftkings',
        'betmgm': 'betmgm',
    }

    # Player prop market keys
    PROP_MARKETS = {
        'points': 'player_points',
        'rebounds': 'player_rebounds',
        'assists': 'player_assists',
        'threes': 'player_threes',
        'pts_rebs_asts': 'player_points_rebounds_assists',
    }

    # Alternate market keys
    ALT_PROP_MARKETS = {
        'points': 'player_points_alternate',
        'rebounds': 'player_rebounds_alternate',
        'assists': 'player_assists_alternate',
        'threes': 'player_threes_alternate',
    }

    def __init__(self, api_key: str = None, config_path: str = None):
        """
        Initialize the scraper.

        Args:
            api_key: The Odds API key (or load from config/env)
            config_path: Path to config file with API key
        """
        import os

        self.api_key = api_key

        # Check environment variable
        if not self.api_key:
            self.api_key = os.environ.get('ODDS_API_KEY')

        # Check config file
        if not self.api_key and config_path:
            self.api_key = self._load_api_key(config_path)
        elif not self.api_key:
            # Try default config path
            default_config = Path(__file__).parent.parent / "config" / "api_keys.json"
            if default_config.exists():
                self.api_key = self._load_api_key(str(default_config))

        if not self.api_key:
            raise ValueError("API key required. Set via ODDS_API_KEY env var, api_key param, or config file.")

        self.base_url = "https://api.the-odds-api.com/v4"
        self.session = requests.Session()

        # Track API usage
        self.requests_remaining = None
        self.requests_used = None

    def _load_api_key(self, config_path: str) -> Optional[str]:
        """Load API key from config file."""
        try:
            with open(config_path) as f:
                config = json.load(f)
            return config.get('the_odds_api', {}).get('api_key')
        except Exception as e:
            logger.warning(f"Could not load config: {e}")
            return None

    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make API request and track usage."""
        url = f"{self.base_url}/{endpoint}"
        params = params or {}
        params['apiKey'] = self.api_key

        try:
            resp = self.session.get(url, params=params, timeout=30)

            # Track usage from headers
            self.requests_remaining = resp.headers.get('x-requests-remaining')
            self.requests_used = resp.headers.get('x-requests-used')

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 401:
                logger.error("Invalid API key")
            elif resp.status_code == 429:
                logger.error("Rate limit exceeded")
            else:
                logger.error(f"API error {resp.status_code}: {resp.text}")

        except Exception as e:
            logger.error(f"Request failed: {e}")

        return None

    def get_nba_events(self) -> List[Dict]:
        """Get upcoming NBA games."""
        data = self._make_request(f"sports/{self.SPORT}/events")

        if not data:
            return []

        events = []
        for event in data:
            events.append({
                'id': event.get('id'),
                'home_team': event.get('home_team'),
                'away_team': event.get('away_team'),
                'commence_time': event.get('commence_time'),
            })

        logger.info(f"Found {len(events)} NBA events")
        return events

    def get_event_player_props(
        self,
        event_id: str,
        markets: List[str] = None,
        bookmakers: List[str] = None
    ) -> List[PlayerProp]:
        """
        Get player props for a specific game.

        Args:
            event_id: The event/game ID
            markets: List of prop markets to fetch (default: all)
            bookmakers: List of sportsbooks (default: all available)

        Returns:
            List of PlayerProp objects
        """
        props = []

        # Default to all markets
        if markets is None:
            markets = list(self.PROP_MARKETS.keys())

        # Default to all bookmakers
        if bookmakers is None:
            bookmakers = list(self.BOOKMAKERS.values())

        # Build market list for API (standard + alternate)
        api_markets = []
        for m in markets:
            if m in self.PROP_MARKETS:
                api_markets.append(self.PROP_MARKETS[m])
            if m in self.ALT_PROP_MARKETS:
                api_markets.append(self.ALT_PROP_MARKETS[m])

        params = {
            'regions': 'us',
            'markets': ','.join(api_markets),
            'bookmakers': ','.join(bookmakers),
            'oddsFormat': 'american',
        }

        data = self._make_request(f"sports/{self.SPORT}/events/{event_id}/odds", params)

        if not data:
            return props

        # Parse the response
        home_team = data.get('home_team', '')
        away_team = data.get('away_team', '')
        commence_time = data.get('commence_time', '')

        # Parse date
        game_date = ''
        game_time = ''
        if commence_time:
            try:
                dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                game_date = dt.strftime('%Y-%m-%d')
                game_time = dt.strftime('%H:%M')
            except:
                pass

        for bookmaker in data.get('bookmakers', []):
            book_key = bookmaker.get('key', '')

            for market in bookmaker.get('markets', []):
                market_key = market.get('key', '')

                # Identify prop type and if alternate
                prop_type = self._market_to_prop_type(market_key)
                if not prop_type:
                    continue

                is_alt = 'alternate' in market_key

                # Parse outcomes (over/under for each player)
                outcomes = market.get('outcomes', [])

                # Group outcomes by player and line
                player_lines = {}

                for outcome in outcomes:
                    player_name = outcome.get('description', '')
                    line = outcome.get('point', 0)
                    odds = outcome.get('price')
                    outcome_name = outcome.get('name', '').lower()

                    key = (player_name, line)

                    if key not in player_lines:
                        player_lines[key] = {
                            'player_name': player_name,
                            'line': line,
                            'over_odds': None,
                            'under_odds': None,
                        }

                    if outcome_name == 'over':
                        player_lines[key]['over_odds'] = odds
                    elif outcome_name == 'under':
                        player_lines[key]['under_odds'] = odds

                # Create PlayerProp objects
                for (player_name, line), line_data in player_lines.items():
                    # Determine team
                    team = ''
                    opponent = ''
                    # (Would need roster data to determine team)

                    prop = PlayerProp(
                        player_name=player_name,
                        team=team,
                        opponent=opponent,
                        game_id=event_id,
                        game_date=game_date,
                        game_time=game_time,
                        prop_type=prop_type,
                        line=float(line) if line else 0,
                        over_odds=line_data['over_odds'],
                        under_odds=line_data['under_odds'],
                        is_alt_line=is_alt,
                        sportsbook=book_key,
                        scraped_at=datetime.now().isoformat()
                    )
                    props.append(prop)

        logger.info(f"Event {event_id}: Found {len(props)} props")
        return props

    def _market_to_prop_type(self, market_key: str) -> Optional[str]:
        """Convert API market key to our prop type."""
        market_lower = market_key.lower()

        if 'points_rebounds_assists' in market_lower:
            return 'pts_rebs_asts'
        elif 'points' in market_lower:
            return 'points'
        elif 'rebounds' in market_lower:
            return 'rebounds'
        elif 'assists' in market_lower:
            return 'assists'
        elif 'threes' in market_lower:
            return 'threes'

        return None

    def scrape_all_props(
        self,
        markets: List[str] = None,
        bookmakers: List[str] = None,
        max_events: int = None
    ) -> Dict[str, List[PlayerProp]]:
        """
        Scrape player props for all upcoming NBA games.

        Args:
            markets: List of prop types to fetch
            bookmakers: List of sportsbooks
            max_events: Maximum events to scrape (for testing/limiting API usage)

        Returns:
            Dictionary mapping sportsbook to list of props
        """
        all_props = {}

        events = self.get_nba_events()

        if max_events:
            events = events[:max_events]

        for i, event in enumerate(events):
            logger.info(f"Scraping event {i+1}/{len(events)}: {event['away_team']} @ {event['home_team']}")

            props = self.get_event_player_props(
                event['id'],
                markets=markets,
                bookmakers=bookmakers
            )

            # Group by sportsbook
            for prop in props:
                book = prop.sportsbook
                if book not in all_props:
                    all_props[book] = []
                all_props[book].append(prop)

        # Log usage
        logger.info(f"API requests remaining: {self.requests_remaining}")

        return all_props

    def create_comparison_df(self, results: Dict[str, List[PlayerProp]]):
        """Create comparison DataFrame across sportsbooks."""
        import pandas as pd

        all_props = []
        for book, props in results.items():
            for prop in props:
                all_props.append(asdict(prop))

        if not all_props:
            return pd.DataFrame()

        df = pd.DataFrame(all_props)

        # Normalize names for matching
        df['player_normalized'] = df['player_name'].str.lower().str.strip()

        # Pivot for comparison
        pivot = df.pivot_table(
            index=['player_normalized', 'prop_type', 'line', 'is_alt_line', 'game_date'],
            columns='sportsbook',
            values=['over_odds', 'under_odds'],
            aggfunc='first'
        )

        pivot.columns = [f'{col[1]}_{col[0]}' for col in pivot.columns]
        pivot = pivot.reset_index()

        return pivot

    def find_best_odds(self, results: Dict[str, List[PlayerProp]]):
        """Find best odds across all sportsbooks."""
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

    def save_results(
        self,
        results: Dict[str, List[PlayerProp]],
        output_dir: str = "data/output",
        filename: str = None
    ) -> Path:
        """Save props to CSV."""
        import pandas as pd

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

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
        file_path = output_path / filename
        df.to_csv(file_path, index=False)

        logger.info(f"Saved {len(all_props)} props to {file_path}")
        return file_path


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Scrape NBA player props from The Odds API')
    parser.add_argument('--markets', nargs='+',
                        choices=['points', 'rebounds', 'assists', 'threes', 'pts_rebs_asts'],
                        default=['points', 'rebounds', 'assists'],
                        help='Prop types to scrape')
    parser.add_argument('--books', nargs='+',
                        choices=['fanduel', 'draftkings', 'betmgm'],
                        default=['fanduel', 'draftkings', 'betmgm'],
                        help='Sportsbooks to include')
    parser.add_argument('--max-events', type=int, default=None,
                        help='Max events to scrape (for testing)')
    parser.add_argument('--output', type=str, default='data/output',
                        help='Output directory')
    parser.add_argument('--compare', action='store_true',
                        help='Also save comparison file')
    parser.add_argument('--api-key', type=str,
                        help='API key (or use config file)')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Initialize scraper
    try:
        scraper = OddsAPIPropsScraper(api_key=args.api_key)
    except ValueError as e:
        print(f"Error: {e}")
        print("Set API key via --api-key or create config/api_keys.json")
        return

    print(f"\nScraping player props...")
    print(f"  Markets: {args.markets}")
    print(f"  Books: {args.books}")
    print("-" * 50)

    results = scraper.scrape_all_props(
        markets=args.markets,
        bookmakers=args.books,
        max_events=args.max_events
    )

    # Summary
    print("\n" + "=" * 50)
    print("SCRAPING SUMMARY")
    print("=" * 50)

    total = 0
    for book, props in results.items():
        print(f"  {book.upper()}: {len(props)} props")
        total += len(props)

    print(f"\n  TOTAL: {total} props")
    print(f"  API requests remaining: {scraper.requests_remaining}")

    if total > 0:
        output_path = scraper.save_results(results, args.output)
        print(f"\n  Saved to: {output_path}")

        if args.compare:
            import pandas as pd
            comparison = scraper.find_best_odds(results)
            compare_path = Path(args.output) / f"props_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            comparison.to_csv(compare_path, index=False)
            print(f"  Comparison: {compare_path}")


if __name__ == "__main__":
    main()
