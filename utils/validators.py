"""
Data validation utilities for scraped NBA odds data.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class DataValidator:
    """Validate scraped game data."""

    # Valid score ranges
    MIN_SCORE = 50
    MAX_SCORE = 200

    # Valid spread ranges
    MIN_SPREAD = -50.0
    MAX_SPREAD = 50.0

    # Valid over/under ranges
    MIN_TOTAL = 150.0
    MAX_TOTAL = 300.0

    # Valid moneyline ranges
    MIN_MONEYLINE = -10000
    MAX_MONEYLINE = 10000

    def __init__(self, team_mappings_path: Optional[str] = None):
        """
        Initialize validator with team mappings.

        Args:
            team_mappings_path: Path to team_mappings.json
        """
        self.valid_teams = set()
        self._load_team_mappings(team_mappings_path)

    def _load_team_mappings(self, path: Optional[str]):
        """Load valid team codes from mappings file."""
        if path is None:
            # Default path relative to project
            path = Path(__file__).parent.parent / 'config' / 'team_mappings.json'
        else:
            path = Path(path)

        try:
            with open(path, 'r') as f:
                data = json.load(f)
                self.valid_teams = set(data.get('team_full_names', {}).keys())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Could not load team mappings: {e}")
            # Fallback to standard NBA team codes
            self.valid_teams = {
                'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN',
                'DET', 'GSW', 'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA',
                'MIL', 'MIN', 'NOP', 'NYK', 'OKC', 'ORL', 'PHI', 'PHX',
                'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
            }

    def validate_game(self, game: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a single game record.

        Args:
            game: Dictionary containing game data

        Returns:
            Dictionary with 'valid' bool and 'errors' list
        """
        errors = []
        warnings = []

        # Required fields
        required = ['game_date', 'home_team', 'away_team']
        for field in required:
            if not game.get(field):
                errors.append(f"Missing required field: {field}")

        # Validate date format
        date = game.get('game_date', '')
        if date and not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
            errors.append(f"Invalid date format: {date}")

        # Validate teams
        home = game.get('home_team', '')
        away = game.get('away_team', '')

        if home and home not in self.valid_teams:
            warnings.append(f"Unrecognized home team: {home}")
        if away and away not in self.valid_teams:
            warnings.append(f"Unrecognized away team: {away}")
        if home and away and home == away:
            errors.append(f"Home and away team are the same: {home}")

        # Validate scores (if present)
        home_score = game.get('home_score')
        away_score = game.get('away_score')

        if home_score is not None:
            if not self._is_valid_score(home_score):
                warnings.append(f"Suspicious home score: {home_score}")
        if away_score is not None:
            if not self._is_valid_score(away_score):
                warnings.append(f"Suspicious away score: {away_score}")

        # Validate spread
        spread = game.get('closing_spread')
        if spread is not None:
            if not self._is_valid_spread(spread):
                warnings.append(f"Suspicious spread: {spread}")

        # Validate over/under
        total = game.get('closing_over_under')
        if total is not None:
            if not self._is_valid_total(total):
                warnings.append(f"Suspicious over/under: {total}")

        # Validate moneylines
        ml_home = game.get('closing_moneyline_home')
        ml_away = game.get('closing_moneyline_away')

        if ml_home is not None:
            if not self._is_valid_moneyline(ml_home):
                warnings.append(f"Suspicious home moneyline: {ml_home}")
        if ml_away is not None:
            if not self._is_valid_moneyline(ml_away):
                warnings.append(f"Suspicious away moneyline: {ml_away}")

        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }

    def _is_valid_score(self, score: Any) -> bool:
        """Check if score is within reasonable range."""
        try:
            score = int(score)
            return self.MIN_SCORE <= score <= self.MAX_SCORE
        except (ValueError, TypeError):
            return False

    def _is_valid_spread(self, spread: Any) -> bool:
        """Check if spread is within reasonable range."""
        try:
            spread = float(spread)
            return self.MIN_SPREAD <= spread <= self.MAX_SPREAD
        except (ValueError, TypeError):
            return False

    def _is_valid_total(self, total: Any) -> bool:
        """Check if over/under is within reasonable range."""
        try:
            total = float(total)
            return self.MIN_TOTAL <= total <= self.MAX_TOTAL
        except (ValueError, TypeError):
            return False

    def _is_valid_moneyline(self, ml: Any) -> bool:
        """Check if moneyline is within reasonable range."""
        try:
            ml = int(ml)
            return self.MIN_MONEYLINE <= ml <= self.MAX_MONEYLINE
        except (ValueError, TypeError):
            return False

    def validate_batch(self, games: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate a batch of games.

        Args:
            games: List of game dictionaries

        Returns:
            Summary of validation results
        """
        total = len(games)
        valid_count = 0
        error_count = 0
        warning_count = 0
        all_errors = []
        all_warnings = []

        for i, game in enumerate(games):
            result = self.validate_game(game)

            if result['valid']:
                valid_count += 1
            else:
                error_count += 1
                for err in result['errors']:
                    all_errors.append(f"Game {i}: {err}")

            if result['warnings']:
                warning_count += 1
                for warn in result['warnings']:
                    all_warnings.append(f"Game {i}: {warn}")

        return {
            'total': total,
            'valid': valid_count,
            'with_errors': error_count,
            'with_warnings': warning_count,
            'errors': all_errors[:20],  # Limit for readability
            'warnings': all_warnings[:20]
        }

    @staticmethod
    def check_duplicates(games: List[Dict[str, Any]]) -> List[str]:
        """
        Find duplicate game IDs.

        Args:
            games: List of game dictionaries

        Returns:
            List of duplicate game_ids
        """
        seen = set()
        duplicates = []

        for game in games:
            game_id = game.get('game_id')
            if game_id:
                if game_id in seen:
                    duplicates.append(game_id)
                else:
                    seen.add(game_id)

        return duplicates
