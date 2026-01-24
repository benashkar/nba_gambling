#!/usr/bin/env python3
"""
Reconnaissance script for OddsPortal.com NBA odds scraping.

This script loads OddsPortal in Selenium and helps identify:
- CSS selectors for game data elements
- Page structure and DOM layout
- Pagination controls
- Dynamic content loading patterns

Run this before implementing the full scraper to discover actual selectors.
"""

import time
import json
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup


def setup_driver(headless: bool = False) -> webdriver.Chrome:
    """Setup Chrome WebDriver with anti-detection measures."""
    options = Options()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """
    })

    return driver


def escape_css_class(cls: str) -> str:
    """Escape special characters in CSS class names for use in selectors."""
    # Escape colons and other special CSS characters
    escaped = ""
    for char in cls:
        if char in ':[]()#.>+~':
            escaped += '\\' + char
        else:
            escaped += char
    return escaped


def analyze_page_structure(html: str) -> dict:
    """Analyze the HTML structure and find potential selectors."""
    soup = BeautifulSoup(html, 'lxml')
    analysis = {
        'potential_game_containers': [],
        'potential_team_elements': [],
        'potential_score_elements': [],
        'potential_date_elements': [],
        'potential_odds_elements': [],
        'potential_pagination': [],
        'class_frequency': {},
    }

    # Find elements with class names containing keywords
    keywords = {
        'game': ['game', 'match', 'event', 'row'],
        'team': ['team', 'participant', 'name', 'home', 'away'],
        'score': ['score', 'result', 'final'],
        'date': ['date', 'time', 'day'],
        'odds': ['odds', 'odd', 'line', 'spread', 'moneyline', 'total'],
        'pagination': ['page', 'pagination', 'pager', 'nav']
    }

    all_elements = soup.find_all(class_=True)

    for elem in all_elements:
        classes = elem.get('class', [])
        for cls in classes:
            cls_lower = cls.lower()

            # Track class frequency
            analysis['class_frequency'][cls] = analysis['class_frequency'].get(cls, 0) + 1

            # Check each category
            for category, kw_list in keywords.items():
                for kw in kw_list:
                    if kw in cls_lower:
                        if category == 'game':
                            key = 'potential_game_containers'
                        elif category == 'pagination':
                            key = 'potential_pagination'
                        else:
                            key = f'potential_{category}_elements'

                        selector = f".{cls}"
                        if selector not in [s['selector'] for s in analysis.get(key, [])]:
                            text_preview = elem.get_text(strip=True)[:100]
                            # Try to count occurrences with escaped selector
                            try:
                                escaped_selector = f".{escape_css_class(cls)}"
                                count = len(soup.select(escaped_selector))
                            except Exception:
                                count = 1  # Fallback if selector fails
                            analysis[key].append({
                                'selector': selector,
                                'tag': elem.name,
                                'sample_text': text_preview,
                                'count': count
                            })
                        break

    # Sort by count (most frequent first)
    for key in analysis:
        if isinstance(analysis[key], list) and analysis[key]:
            analysis[key].sort(key=lambda x: x.get('count', 0), reverse=True)

    return analysis


def extract_sample_games(driver, soup: BeautifulSoup) -> list:
    """Try to extract sample game data using various selector strategies."""
    samples = []

    # Try different selector strategies
    strategies = [
        {
            'name': 'eventRow pattern',
            'container': 'div[class*="eventRow"]',
            'team': '[class*="participant"], [class*="team"]',
            'score': '[class*="score"]'
        },
        {
            'name': 'table pattern',
            'container': 'tr[class*="event"], tr[class*="deactivate"]',
            'team': 'td a[href*="basketball"]',
            'score': 'td[class*="result"], td[class*="score"]'
        },
        {
            'name': 'flex container pattern',
            'container': 'div[class*="flex"][class*="event"]',
            'team': 'span[class*="team"], div[class*="team"]',
            'score': 'span[class*="score"], div[class*="score"]'
        }
    ]

    for strategy in strategies:
        containers = soup.select(strategy['container'])
        if containers:
            sample = {
                'strategy': strategy['name'],
                'container_count': len(containers),
                'games': []
            }

            for container in containers[:5]:
                game = {}
                teams = container.select(strategy['team'])
                scores = container.select(strategy['score'])

                if teams:
                    game['teams'] = [t.get_text(strip=True) for t in teams[:2]]
                if scores:
                    game['scores'] = [s.get_text(strip=True) for s in scores[:2]]

                if game:
                    sample['games'].append(game)

            if sample['games']:
                samples.append(sample)

    return samples


def run_recon(url: str = "https://www.oddsportal.com/basketball/usa/nba/results/",
              headless: bool = False,
              save_html: bool = True):
    """
    Run reconnaissance on OddsPortal.

    Args:
        url: URL to analyze
        headless: Run in headless mode
        save_html: Save raw HTML for manual inspection
    """
    print("=" * 60)
    print("OddsPortal Reconnaissance Script")
    print("=" * 60)
    print(f"\nTarget URL: {url}")
    print(f"Headless: {headless}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    driver = None
    try:
        print("Setting up Chrome WebDriver...")
        driver = setup_driver(headless=headless)

        print(f"Navigating to {url}...")
        driver.get(url)

        print("Waiting for page to load...")
        time.sleep(5)  # Give JavaScript time to render

        # Try to wait for specific elements
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div, table, tr"))
            )
        except TimeoutException:
            print("Warning: Timeout waiting for elements")

        # Get page source
        html = driver.page_source
        soup = BeautifulSoup(html, 'lxml')

        # Save HTML for manual inspection
        if save_html:
            output_dir = Path("recon_output")
            output_dir.mkdir(exist_ok=True)

            html_file = output_dir / f"oddsportal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"\nSaved HTML to: {html_file}")

        # Analyze page structure
        print("\n" + "=" * 60)
        print("PAGE STRUCTURE ANALYSIS")
        print("=" * 60)

        analysis = analyze_page_structure(html)

        # Print findings
        categories = [
            ('Game Containers', 'potential_game_containers'),
            ('Team Elements', 'potential_team_elements'),
            ('Score Elements', 'potential_score_elements'),
            ('Date Elements', 'potential_date_elements'),
            ('Odds Elements', 'potential_odds_elements'),
            ('Pagination', 'potential_pagination_containers'),
        ]

        for name, key in categories:
            print(f"\n{name}:")
            elements = analysis.get(key, [])
            if elements:
                for elem in elements[:5]:
                    print(f"  Selector: {elem['selector']}")
                    print(f"    Tag: {elem['tag']}, Count: {elem['count']}")
                    print(f"    Sample: {elem['sample_text'][:60]}...")
            else:
                print("  None found")

        # Try sample extraction
        print("\n" + "=" * 60)
        print("SAMPLE GAME EXTRACTION")
        print("=" * 60)

        samples = extract_sample_games(driver, soup)
        for sample in samples:
            print(f"\nStrategy: {sample['strategy']}")
            print(f"Containers found: {sample['container_count']}")
            print("Sample games:")
            for i, game in enumerate(sample['games'][:3]):
                print(f"  Game {i+1}: {game}")

        # Save analysis
        if save_html:
            analysis_file = output_dir / f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(analysis_file, 'w') as f:
                json.dump({
                    'url': url,
                    'timestamp': datetime.now().isoformat(),
                    'analysis': analysis,
                    'samples': samples
                }, f, indent=2, default=str)
            print(f"\nSaved analysis to: {analysis_file}")

        # Interactive mode if not headless
        if not headless:
            print("\n" + "=" * 60)
            print("INTERACTIVE MODE")
            print("=" * 60)
            print("Browser is open. Inspect elements manually.")
            print("Press Enter to close the browser...")
            input()

    except Exception as e:
        print(f"\nError during reconnaissance: {e}")
        raise

    finally:
        if driver:
            driver.quit()
            print("\nBrowser closed.")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='OddsPortal reconnaissance script')

    parser.add_argument(
        '--url',
        default='https://www.oddsportal.com/basketball/usa/nba/results/',
        help='URL to analyze'
    )

    parser.add_argument(
        '--headless',
        action='store_true',
        help='Run in headless mode (no visible browser)'
    )

    parser.add_argument(
        '--no-save',
        action='store_true',
        help='Do not save HTML and analysis files'
    )

    args = parser.parse_args()

    run_recon(
        url=args.url,
        headless=args.headless,
        save_html=not args.no_save
    )
