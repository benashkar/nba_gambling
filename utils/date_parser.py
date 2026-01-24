"""
Date parsing utilities for OddsPortal scraper.
Handles various date formats found on the site.
"""

import re
from datetime import datetime, timedelta
from typing import Optional


class DateParser:
    """Parse various date formats to standardized YYYY-MM-DD format."""

    MONTH_MAP = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
        'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
        'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }

    @classmethod
    def parse(cls, date_str: str, reference_year: Optional[int] = None) -> Optional[str]:
        """
        Parse a date string to YYYY-MM-DD format.

        Args:
            date_str: Date string in various formats
            reference_year: Year to use if not present in date_str

        Returns:
            Date in YYYY-MM-DD format or None if parsing fails
        """
        if not date_str:
            return None

        date_str = date_str.strip().lower()

        # Handle "Today", "Yesterday"
        if 'today' in date_str:
            return datetime.now().strftime('%Y-%m-%d')
        if 'yesterday' in date_str:
            return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        # Try various patterns
        parsed = (
            cls._parse_full_date(date_str) or
            cls._parse_day_month(date_str, reference_year) or
            cls._parse_month_day_year(date_str) or
            cls._parse_iso_format(date_str)
        )

        return parsed

    @classmethod
    def _parse_full_date(cls, date_str: str) -> Optional[str]:
        """Parse formats like '15 Jan 2024' or 'Jan 15, 2024'."""
        # Pattern: DD Mon YYYY
        match = re.search(r'(\d{1,2})\s+([a-z]{3})\s+(\d{4})', date_str)
        if match:
            day, month, year = match.groups()
            month_num = cls.MONTH_MAP.get(month)
            if month_num:
                return f"{year}-{month_num:02d}-{int(day):02d}"

        # Pattern: Mon DD, YYYY
        match = re.search(r'([a-z]{3})\s+(\d{1,2}),?\s+(\d{4})', date_str)
        if match:
            month, day, year = match.groups()
            month_num = cls.MONTH_MAP.get(month)
            if month_num:
                return f"{year}-{month_num:02d}-{int(day):02d}"

        return None

    @classmethod
    def _parse_day_month(cls, date_str: str, reference_year: Optional[int]) -> Optional[str]:
        """Parse formats like '15 Jan' when year is implied."""
        if not reference_year:
            reference_year = datetime.now().year

        # Pattern: DD Mon
        match = re.search(r'(\d{1,2})\s+([a-z]{3})', date_str)
        if match:
            day, month = match.groups()
            month_num = cls.MONTH_MAP.get(month)
            if month_num:
                return f"{reference_year}-{month_num:02d}-{int(day):02d}"

        return None

    @classmethod
    def _parse_month_day_year(cls, date_str: str) -> Optional[str]:
        """Parse formats like 'MM/DD/YYYY' or 'MM-DD-YYYY'."""
        match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', date_str)
        if match:
            month, day, year = match.groups()
            return f"{year}-{int(month):02d}-{int(day):02d}"

        # Handle 2-digit year
        match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2})', date_str)
        if match:
            month, day, year = match.groups()
            year_full = 2000 + int(year) if int(year) < 50 else 1900 + int(year)
            return f"{year_full}-{int(month):02d}-{int(day):02d}"

        return None

    @classmethod
    def _parse_iso_format(cls, date_str: str) -> Optional[str]:
        """Parse ISO format YYYY-MM-DD."""
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})', date_str)
        if match:
            return match.group(0)
        return None

    @staticmethod
    def get_season_from_date(date_str: str) -> Optional[str]:
        """
        Determine NBA season from a game date.
        NBA season runs from October to April/June.

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            Season string like '2024-2025' or None
        """
        if not date_str:
            return None

        try:
            date = datetime.strptime(date_str, '%Y-%m-%d')
            year = date.year
            month = date.month

            # Games Oct-Dec are first year of season
            # Games Jan-Jun are second year of season
            if month >= 10:
                return f"{year}-{year + 1}"
            else:
                return f"{year - 1}-{year}"
        except ValueError:
            return None

    @staticmethod
    def get_reference_year_for_season(season: str) -> int:
        """
        Get the reference year for parsing dates within a season.
        Returns the year when season starts (October).

        Args:
            season: Season string like '2024-2025'

        Returns:
            Start year of the season
        """
        if '-' in season:
            return int(season.split('-')[0])
        return int(season)
