# OddsPortal NBA Odds Scraping Strategy

## Project Overview
Build a web scraper to extract NBA closing lines from OddsPortal.com for seasons 2021-2022 through 2025-2026, outputting to CSV and/or AWS-hosted MySQL database.

---

## Target Data Points

### Required Fields
- `game_id` (generated: e.g., "20240115_LAL_BOS")
- `game_date` (format: YYYY-MM-DD)
- `season` (e.g., "2024-2025")
- `home_team` (standardized name)
- `away_team` (standardized name)
- `home_score` (final, integer)
- `away_score` (final, integer)
- `closing_spread` (decimal, negative = home favored)
- `closing_over_under` (decimal)
- `closing_moneyline_home` (American odds format)
- `closing_moneyline_away` (American odds format)
- `scraped_at` (timestamp of data collection)

### Optional/Enhanced Fields
- `opening_spread`
- `opening_over_under`
- `bookmaker` (which book's closing line - e.g., "Pinnacle", "consensus")
- `game_time` (tip-off time)
- `venue`

---

## Target URLs Structure

### Season-Specific URLs
```
2021-2022: https://www.oddsportal.com/basketball/usa/nba-2021-2022/results/
2022-2023: https://www.oddsportal.com/basketball/usa/nba-2022-2023/results/
2023-2024: https://www.oddsportal.com/basketball/usa/nba-2023-2024/results/
2024-2025: https://www.oddsportal.com/basketball/usa/nba-2024-2025/results/
2025-2026: https://www.oddsportal.com/basketball/usa/nba/results/
```

### Pagination Pattern
OddsPortal uses pagination - you'll need to:
1. Load initial results page
2. Check for "next page" or pagination links
3. Navigate through all pages for each season
4. Typical pattern: `?page=2`, `?page=3`, etc.

---

## Technical Implementation Strategy

### Phase 1: Setup & Environment

#### Required Python Libraries
```python
pip install requests
pip install beautifulsoup4
pip install selenium  # if JavaScript rendering needed
pip install pandas
pip install mysql-connector-python  # for MySQL
pip install python-dotenv  # for environment variables
pip install lxml  # faster parsing
```

#### Project Structure
```
nba_odds_scraper/
├── config/
│   ├── .env                 # AWS credentials, DB config
│   └── team_mappings.json   # Team name standardization
├── scrapers/
│   ├── __init__.py
│   ├── oddsportal_scraper.py
│   └── base_scraper.py
├── database/
│   ├── __init__.py
│   ├── mysql_handler.py
│   └── csv_handler.py
├── utils/
│   ├── __init__.py
│   ├── date_parser.py
│   └── validators.py
├── data/
│   └── output/             # CSV files stored here
├── logs/
│   └── scraper.log
├── main.py
└── requirements.txt
```

---

### Phase 2: Web Scraping Strategy

#### Step 1: Reconnaissance
**Before writing code, manually inspect:**
1. Open browser DevTools (F12)
2. Navigate to one results page
3. Identify HTML structure for:
   - Game rows/containers
   - Date elements
   - Team names
   - Scores
   - Odds elements (spread, O/U, moneyline)
   - Pagination controls

**Key questions to answer:**
- Is content JavaScript-rendered? (if yes, use Selenium)
- What CSS selectors or XPath identify game rows?
- How are closing lines distinguished from opening lines?
- Are there multiple bookmaker tabs?

#### Step 2: Anti-Detection Measures

**Headers Configuration:**
```python
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Cache-Control': 'max-age=0'
}
```

**Rate Limiting:**
```python
import time
import random

# Between page requests
time.sleep(random.uniform(2.0, 4.0))

# Between seasons
time.sleep(random.uniform(10.0, 15.0))

# Exponential backoff on errors
def exponential_backoff(attempt):
    wait_time = min(300, (2 ** attempt) + random.uniform(0, 1))
    time.sleep(wait_time)
```

**Retry Logic:**
```python
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

def create_session():
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session
```

#### Step 3: Data Extraction Logic

**Parsing Strategy:**
```python
def parse_game_row(row_element):
    """
    Extract all data from a single game row
    
    Returns:
        dict with all game data fields
    """
    game_data = {}
    
    # Extract date (convert to YYYY-MM-DD)
    date_text = row_element.find('td', class_='date-class').text
    game_data['game_date'] = parse_date_to_iso(date_text)
    
    # Extract teams
    teams = row_element.find_all('a', class_='team-link')
    game_data['away_team'] = standardize_team_name(teams[0].text)
    game_data['home_team'] = standardize_team_name(teams[1].text)
    
    # Extract scores
    scores = row_element.find('td', class_='score').text.split(':')
    game_data['away_score'] = int(scores[0])
    game_data['home_score'] = int(scores[1])
    
    # Extract odds (closing lines)
    odds_cells = row_element.find_all('td', class_='odds-cell')
    
    # Spread (may need to click or hover to get closing)
    spread_element = odds_cells[0]
    game_data['closing_spread'] = parse_spread(spread_element)
    
    # Over/Under
    ou_element = odds_cells[1]
    game_data['closing_over_under'] = parse_over_under(ou_element)
    
    # Moneyline
    ml_elements = odds_cells[2:4]
    game_data['closing_moneyline_away'] = parse_moneyline(ml_elements[0])
    game_data['closing_moneyline_home'] = parse_moneyline(ml_elements[1])
    
    # Generate game_id
    game_data['game_id'] = f"{game_data['game_date']}_{game_data['away_team']}_{game_data['home_team']}"
    
    return game_data
```

**Date Parsing:**
```python
from datetime import datetime

def parse_date_to_iso(date_string):
    """
    Convert various date formats to YYYY-MM-DD
    
    Examples:
    "15 Jan 2024" -> "2024-01-15"
    "Jan 15, 2024" -> "2024-01-15"
    """
    # Try multiple formats
    formats = [
        "%d %b %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
        "%m/%d/%Y"
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_string.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    raise ValueError(f"Unable to parse date: {date_string}")
```

**Team Name Standardization:**
```python
# Create team_mappings.json
team_mappings = {
    "LA Lakers": "Lakers",
    "L.A. Lakers": "Lakers",
    "Los Angeles Lakers": "Lakers",
    "LAL": "Lakers",
    # ... map all variations to canonical names
}

def standardize_team_name(raw_name):
    """Convert various team name formats to standard"""
    raw_name = raw_name.strip()
    return team_mappings.get(raw_name, raw_name)
```

#### Step 4: Handling JavaScript-Rendered Content

**If OddsPortal uses JavaScript (likely):**
```python
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

def setup_selenium_driver():
    """Configure headless Chrome"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def scrape_season_with_selenium(season_url):
    """Scrape a full season using Selenium"""
    driver = setup_selenium_driver()
    all_games = []
    
    try:
        driver.get(season_url)
        
        # Wait for content to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "game-row-class"))
        )
        
        # Handle pagination
        while True:
            # Parse current page
            soup = BeautifulSoup(driver.page_source, 'lxml')
            games = parse_games_from_page(soup)
            all_games.extend(games)
            
            # Check for next page
            try:
                next_button = driver.find_element(By.CLASS_NAME, "next-page-class")
                if "disabled" in next_button.get_attribute("class"):
                    break
                next_button.click()
                time.sleep(random.uniform(2, 4))
            except:
                break  # No more pages
                
    finally:
        driver.quit()
    
    return all_games
```

---

### Phase 3: Data Validation & Cleaning

#### Validation Rules
```python
def validate_game_data(game):
    """Ensure data quality before storage"""
    errors = []
    
    # Required fields
    required = ['game_id', 'game_date', 'home_team', 'away_team', 
                'home_score', 'away_score']
    for field in required:
        if field not in game or game[field] is None:
            errors.append(f"Missing {field}")
    
    # Date format
    try:
        datetime.strptime(game['game_date'], "%Y-%m-%d")
    except:
        errors.append(f"Invalid date format: {game.get('game_date')}")
    
    # Score validation
    if game.get('home_score', -1) < 0 or game.get('away_score', -1) < 0:
        errors.append("Invalid scores")
    
    # Odds validation
    if game.get('closing_spread') and abs(game['closing_spread']) > 50:
        errors.append(f"Suspicious spread: {game['closing_spread']}")
    
    if game.get('closing_over_under') and (game['closing_over_under'] < 150 or game['closing_over_under'] > 300):
        errors.append(f"Suspicious O/U: {game['closing_over_under']}")
    
    return len(errors) == 0, errors
```

#### Deduplication
```python
def deduplicate_games(games):
    """Remove duplicate entries"""
    seen = set()
    unique_games = []
    
    for game in games:
        game_id = game['game_id']
        if game_id not in seen:
            seen.add(game_id)
            unique_games.append(game)
    
    return unique_games
```

---

### Phase 4: Data Storage

#### Option A: CSV Output

```python
import pandas as pd
from pathlib import Path

def save_to_csv(games, output_dir='./data/output'):
    """Save games to CSV with proper formatting"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    df = pd.DataFrame(games)
    
    # Ensure proper column order
    column_order = [
        'game_id', 'game_date', 'season', 
        'home_team', 'away_team',
        'home_score', 'away_score',
        'closing_spread', 'closing_over_under',
        'closing_moneyline_home', 'closing_moneyline_away',
        'scraped_at'
    ]
    
    df = df[column_order]
    
    # Sort by date
    df = df.sort_values('game_date')
    
    # Save with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{output_dir}/nba_odds_{timestamp}.csv"
    df.to_csv(filename, index=False)
    
    print(f"Saved {len(df)} games to {filename}")
    return filename
```

#### Option B: MySQL Database

**Database Schema:**
```sql
CREATE TABLE nba_games (
    id INT AUTO_INCREMENT PRIMARY KEY,
    game_id VARCHAR(50) UNIQUE NOT NULL,
    game_date DATE NOT NULL,
    season VARCHAR(10) NOT NULL,
    home_team VARCHAR(50) NOT NULL,
    away_team VARCHAR(50) NOT NULL,
    home_score INT,
    away_score INT,
    closing_spread DECIMAL(5,2),
    closing_over_under DECIMAL(5,2),
    closing_moneyline_home INT,
    closing_moneyline_away INT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_game_date (game_date),
    INDEX idx_season (season),
    INDEX idx_teams (home_team, away_team)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Python MySQL Handler:**
```python
import mysql.connector
from mysql.connector import Error
import os
from dotenv import load_dotenv

class MySQLHandler:
    def __init__(self):
        load_dotenv()
        self.config = {
            'host': os.getenv('AWS_RDS_HOST'),
            'database': os.getenv('AWS_RDS_DATABASE'),
            'user': os.getenv('AWS_RDS_USER'),
            'password': os.getenv('AWS_RDS_PASSWORD'),
            'port': int(os.getenv('AWS_RDS_PORT', 3306))
        }
        self.connection = None
    
    def connect(self):
        """Establish database connection"""
        try:
            self.connection = mysql.connector.connect(**self.config)
            if self.connection.is_connected():
                print("Successfully connected to MySQL")
                return True
        except Error as e:
            print(f"Error connecting to MySQL: {e}")
            return False
    
    def create_table(self):
        """Create table if not exists"""
        create_table_query = """
        CREATE TABLE IF NOT EXISTS nba_games (
            id INT AUTO_INCREMENT PRIMARY KEY,
            game_id VARCHAR(50) UNIQUE NOT NULL,
            game_date DATE NOT NULL,
            season VARCHAR(10) NOT NULL,
            home_team VARCHAR(50) NOT NULL,
            away_team VARCHAR(50) NOT NULL,
            home_score INT,
            away_score INT,
            closing_spread DECIMAL(5,2),
            closing_over_under DECIMAL(5,2),
            closing_moneyline_home INT,
            closing_moneyline_away INT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_game_date (game_date),
            INDEX idx_season (season),
            INDEX idx_teams (home_team, away_team)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        
        try:
            cursor = self.connection.cursor()
            cursor.execute(create_table_query)
            self.connection.commit()
            print("Table created successfully")
        except Error as e:
            print(f"Error creating table: {e}")
    
    def insert_game(self, game):
        """Insert or update a single game"""
        insert_query = """
        INSERT INTO nba_games (
            game_id, game_date, season, home_team, away_team,
            home_score, away_score, closing_spread, closing_over_under,
            closing_moneyline_home, closing_moneyline_away
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            home_score = VALUES(home_score),
            away_score = VALUES(away_score),
            closing_spread = VALUES(closing_spread),
            closing_over_under = VALUES(closing_over_under),
            closing_moneyline_home = VALUES(closing_moneyline_home),
            closing_moneyline_away = VALUES(closing_moneyline_away),
            updated_at = CURRENT_TIMESTAMP
        """
        
        values = (
            game['game_id'],
            game['game_date'],
            game['season'],
            game['home_team'],
            game['away_team'],
            game.get('home_score'),
            game.get('away_score'),
            game.get('closing_spread'),
            game.get('closing_over_under'),
            game.get('closing_moneyline_home'),
            game.get('closing_moneyline_away')
        )
        
        try:
            cursor = self.connection.cursor()
            cursor.execute(insert_query, values)
            self.connection.commit()
            return True
        except Error as e:
            print(f"Error inserting game {game['game_id']}: {e}")
            return False
    
    def insert_bulk(self, games):
        """Insert multiple games efficiently"""
        success_count = 0
        for game in games:
            if self.insert_game(game):
                success_count += 1
        
        print(f"Successfully inserted/updated {success_count}/{len(games)} games")
        return success_count
    
    def close(self):
        """Close database connection"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("MySQL connection closed")
```

**.env File Setup:**
```env
# AWS RDS MySQL Configuration
AWS_RDS_HOST=your-rds-instance.region.rds.amazonaws.com
AWS_RDS_DATABASE=nba_odds_db
AWS_RDS_USER=admin
AWS_RDS_PASSWORD=your_secure_password
AWS_RDS_PORT=3306
```

---

### Phase 5: Main Execution Script

```python
# main.py
import logging
from datetime import datetime
from scrapers.oddsportal_scraper import OddsPortalScraper
from database.mysql_handler import MySQLHandler
from database.csv_handler import save_to_csv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/scraper.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def main():
    """Main execution function"""
    
    # Define seasons to scrape
    seasons = [
        ('2021-2022', 'https://www.oddsportal.com/basketball/usa/nba-2021-2022/results/'),
        ('2022-2023', 'https://www.oddsportal.com/basketball/usa/nba-2022-2023/results/'),
        ('2023-2024', 'https://www.oddsportal.com/basketball/usa/nba-2023-2024/results/'),
        ('2024-2025', 'https://www.oddsportal.com/basketball/usa/nba-2024-2025/results/'),
        ('2025-2026', 'https://www.oddsportal.com/basketball/usa/nba/results/')
    ]
    
    # Initialize scraper
    scraper = OddsPortalScraper()
    all_games = []
    
    # Scrape each season
    for season_name, season_url in seasons:
        logger.info(f"Starting scrape for {season_name}")
        try:
            games = scraper.scrape_season(season_url, season_name)
            logger.info(f"Successfully scraped {len(games)} games for {season_name}")
            all_games.extend(games)
        except Exception as e:
            logger.error(f"Error scraping {season_name}: {e}")
            continue
    
    logger.info(f"Total games scraped: {len(all_games)}")
    
    # Save to CSV
    csv_file = save_to_csv(all_games)
    logger.info(f"Saved to CSV: {csv_file}")
    
    # Save to MySQL (optional)
    use_mysql = input("Do you want to save to MySQL database? (y/n): ")
    if use_mysql.lower() == 'y':
        db = MySQLHandler()
        if db.connect():
            db.create_table()
            db.insert_bulk(all_games)
            db.close()
    
    logger.info("Scraping completed successfully")

if __name__ == "__main__":
    main()
```

---

## Best Practices & Error Handling

### 1. Checkpoint System
```python
import json

def save_checkpoint(season, games, checkpoint_file='checkpoint.json'):
    """Save progress in case of interruption"""
    checkpoint = {
        'season': season,
        'games_count': len(games),
        'last_game_id': games[-1]['game_id'] if games else None,
        'timestamp': datetime.now().isoformat()
    }
    
    with open(checkpoint_file, 'w') as f:
        json.dump(checkpoint, f)
    
    # Also save games data
    with open(f'checkpoint_{season}.json', 'w') as f:
        json.dump(games, f)

def load_checkpoint(checkpoint_file='checkpoint.json'):
    """Resume from checkpoint"""
    try:
        with open(checkpoint_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
```

### 2. Monitoring & Alerts
```python
def send_alert(message, level='INFO'):
    """Send alert (implement with email, Slack, etc.)"""
    logger.log(getattr(logging, level), message)
    # Add email/Slack notification here if desired
```

### 3. Data Quality Checks
```python
def validate_season_completeness(games, season):
    """Check if we have expected number of games"""
    expected_games = 1230  # Regular season games
    actual_games = len(games)
    
    if actual_games < expected_games * 0.95:  # Allow 5% margin
        logger.warning(f"{season}: Only {actual_games}/{expected_games} games found")
        return False
    return True
```

### 4. Incremental Updates
```python
def get_latest_game_date(db_handler):
    """Get most recent game in database"""
    query = "SELECT MAX(game_date) FROM nba_games WHERE season = %s"
    # Execute and return date
    # Use this to only scrape new games
```

---

## Execution Timeline

### Initial Full Scrape (Estimated: 2-4 hours)
1. **Season 2021-2022**: ~1,230 games × 3 sec/game = ~60 min
2. **Season 2022-2023**: ~1,230 games × 3 sec/game = ~60 min
3. **Season 2023-2024**: ~1,230 games × 3 sec/game = ~60 min
4. **Season 2024-2025**: ~800 games (partial) × 3 sec/game = ~40 min
5. **Season 2025-2026**: ~500 games (ongoing) × 3 sec/game = ~25 min

### Ongoing Updates (Daily)
- Scrape only new games from current season
- Runtime: 5-10 minutes

---

## Testing Strategy

### 1. Start Small
```python
# Test with single game first
test_url = "https://www.oddsportal.com/basketball/usa/nba/game/XYZ"
# Parse and validate

# Test with single page
# Test with single season
# Then full scrape
```

### 2. Validation Tests
- Verify date formats
- Check team name consistency
- Validate odds ranges
- Ensure no duplicates

### 3. Database Tests
- Test INSERT operations
- Test UPDATE on duplicates
- Verify indexes performance

---

## Security Considerations

### AWS RDS Setup
1. Use security groups to restrict access
2. Enable SSL connections
3. Use IAM authentication (optional)
4. Regular backups enabled
5. Keep credentials in .env, never commit

### Scraping Ethics
1. Respect robots.txt
2. Use reasonable rate limits
3. Identify your bot in User-Agent (optional)
4. Don't overload servers
5. Cache responses when possible

---

## Troubleshooting Guide

### Issue: JavaScript Not Loading
**Solution**: Use Selenium with proper wait conditions

### Issue: Rate Limited / Blocked
**Solution**: 
- Increase delays
- Use rotating proxies (ProxyMesh, ScraperAPI)
- Switch user agents

### Issue: HTML Structure Changed
**Solution**:
- Inspect current structure
- Update selectors
- Add multiple fallback selectors

### Issue: Date Parsing Fails
**Solution**:
- Log problematic dates
- Add more date format patterns
- Handle timezone conversions

### Issue: Missing Closing Lines
**Solution**:
- Check if you need to click/hover to reveal
- Look for alternative data attributes
- May need to scrape individual game pages

---

## Success Metrics

- **Completeness**: 95%+ of expected games per season
- **Accuracy**: Manual spot-check 100 random games
- **Performance**: <5 requests/second
- **Uptime**: Scraper runs without crashing
- **Data Quality**: <1% validation errors

---

## Next Steps After Initial Scrape

1. **Set up automated daily updates**
2. **Add data analysis capabilities**
3. **Create API endpoints** to query database
4. **Build dashboard** for visualization
5. **Implement ML models** for predictions
6. **Add more sports/leagues**

---

## Sample Command for Claude Code

```bash
# To execute this strategy:

1. Read this entire strategy document
2. Create the project structure outlined in Phase 1
3. First, write a reconnaissance script to inspect OddsPortal's HTML
4. Based on that, implement the scraper with Selenium
5. Test on a single page, then single season
6. Add validation and error handling
7. Implement CSV export
8. Set up MySQL connection (I'll provide .env values)
9. Run full scrape with checkpoints
10. Verify data quality and completeness
```
