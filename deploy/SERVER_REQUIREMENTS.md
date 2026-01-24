# NBA Gambling Scraper - Server Requirements

Complete infrastructure specification for DevOps/SysAdmin deployment.

---

## 1. Hardware Specifications

| Resource | Minimum | Recommended | Notes |
|----------|---------|-------------|-------|
| **CPU** | 2 vCPU | 4 vCPU | Chrome/Selenium is CPU-intensive |
| **RAM** | 4 GB | 8 GB | Chrome uses ~800MB per instance |
| **Storage** | 20 GB SSD | 40 GB SSD | NVMe preferred for MySQL performance |
| **Network** | 100 Mbps | 1 Gbps | Outbound internet access required |

### Cloud Provider Equivalents

| Provider | Instance Type | Specs | Est. Cost/Month |
|----------|---------------|-------|-----------------|
| DigitalOcean | Basic Droplet | 4GB RAM, 2 vCPU, 80GB | $24 |
| AWS | t3.medium | 4GB RAM, 2 vCPU | $30-40 |
| Hetzner | CX31 | 8GB RAM, 2 vCPU, 80GB | €7 (~$8) |
| Vultr | Regular Cloud | 4GB RAM, 2 vCPU, 80GB | $24 |
| Linode | Linode 4GB | 4GB RAM, 2 vCPU, 80GB | $24 |

---

## 2. Operating System

| Requirement | Specification |
|-------------|---------------|
| **OS** | Ubuntu 22.04 LTS (Jammy Jellyfish) |
| **Architecture** | x86_64 (amd64) |
| **Kernel** | 5.15+ |

**Alternatives supported:**
- Ubuntu 24.04 LTS
- Debian 12 (Bookworm)
- Amazon Linux 2023

---

## 3. System Packages

### Core Packages (apt)

```bash
# System utilities
apt-get install -y \
    curl \
    wget \
    unzip \
    git \
    ca-certificates \
    gnupg \
    lsb-release \
    software-properties-common

# Python
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev

# MySQL
apt-get install -y \
    mysql-server \
    mysql-client \
    libmysqlclient-dev

# Chrome dependencies
apt-get install -y \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils
```

### Google Chrome Installation

```bash
# Add Google Chrome repository
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list

# Install Chrome
apt-get update
apt-get install -y google-chrome-stable

# Verify installation
google-chrome --version
# Expected: Google Chrome 120.x.x.x or higher
```

---

## 4. Python Requirements

### Python Version
- **Minimum:** Python 3.10
- **Recommended:** Python 3.11+

### Python Packages (pip)

```
selenium>=4.15.0
beautifulsoup4>=4.12.0
pandas>=2.0.0
lxml>=4.9.0
webdriver-manager>=4.0.0
mysql-connector-python>=8.2.0
python-dotenv>=1.0.0
```

### Virtual Environment Setup

```bash
python3 -m venv /opt/nba_gambling/venv
source /opt/nba_gambling/venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. MySQL Configuration

### Version
- **Minimum:** MySQL 8.0
- **Recommended:** MySQL 8.0.35+

### Database Setup

```sql
-- Create database
CREATE DATABASE nba_gambling
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- Create application user
CREATE USER 'nba_scraper'@'localhost' IDENTIFIED BY '<SECURE_PASSWORD>';
GRANT SELECT, INSERT, UPDATE, DELETE ON nba_gambling.* TO 'nba_scraper'@'localhost';
FLUSH PRIVILEGES;
```

### MySQL Configuration (/etc/mysql/mysql.conf.d/mysqld.cnf)

```ini
[mysqld]
# Performance tuning for small instance
innodb_buffer_pool_size = 512M
innodb_log_file_size = 128M
max_connections = 50

# Character set
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci

# Timezone (important for game dates)
default-time-zone = 'America/New_York'
```

### Expected Database Size

| Timeframe | Rows | Size |
|-----------|------|------|
| Per season | ~1,300 games | ~150 KB |
| 5 seasons | ~6,500 games | ~750 KB |
| 10 years projected | ~13,000 games | ~1.5 MB |
| With 6 scrapers (10 years) | ~80,000 rows | ~10 MB |

---

## 6. Directory Structure

```
/opt/nba_gambling/                  # Application root (or /home/ubuntu/nba_gambling)
├── venv/                           # Python virtual environment
├── database/                       # Database module
├── scrapers/                       # Scraper code
├── utils/                          # Utility functions
├── config/                         # Configuration files
├── deploy/                         # Deployment scripts
├── data/
│   └── output/                     # CSV output files
├── logs/                           # Application logs
├── checkpoints/                    # Scraper resume data
├── .env                            # Environment variables (600 permissions)
├── main.py                         # Entry point
└── requirements.txt                # Python dependencies
```

### Directory Permissions

```bash
# Application directory
chown -R appuser:appuser /opt/nba_gambling
chmod 755 /opt/nba_gambling

# Sensitive files
chmod 600 /opt/nba_gambling/.env

# Executable scripts
chmod +x /opt/nba_gambling/deploy/*.sh
```

---

## 7. Environment Variables

Create `/opt/nba_gambling/.env`:

```bash
# MySQL Configuration
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=nba_scraper
MYSQL_PASSWORD=<SECURE_PASSWORD>
MYSQL_DATABASE=nba_gambling

# Optional: Chrome options
CHROME_BIN=/usr/bin/google-chrome
DISPLAY=:99  # For headless operation
```

---

## 8. Network & Firewall

### Outbound Access Required

| Destination | Port | Protocol | Purpose |
|-------------|------|----------|---------|
| oddsportal.com | 443 | HTTPS | Scraping target |
| dl.google.com | 443 | HTTPS | Chrome updates |
| pypi.org | 443 | HTTPS | Python packages |
| github.com | 443 | HTTPS | Code repository |

### Inbound Access (Optional)

| Port | Protocol | Purpose |
|------|----------|---------|
| 22 | SSH | Remote administration |
| 3306 | MySQL | Only if remote DB access needed |

### UFW Configuration

```bash
ufw allow OpenSSH
ufw enable
# No inbound ports needed for scraper operation
```

---

## 9. Cron Schedule

### Crontab Configuration

```cron
# NBA Scraper - Daily update at 6 AM ET (after games finish)
0 6 * * * cd /opt/nba_gambling && ./deploy/run_scraper.sh >> logs/cron.log 2>&1

# Weekly full historical scrape on Sunday at 4 AM
0 4 * * 0 cd /opt/nba_gambling && ./deploy/run_scraper.sh --full >> logs/cron.log 2>&1

# Log rotation - keep 7 days
0 0 * * * find /opt/nba_gambling/logs -name "*.log" -mtime +7 -delete

# MySQL backup - daily at 3 AM
0 3 * * * mysqldump -u nba_scraper -p'PASSWORD' nba_gambling | gzip > /opt/nba_gambling/backups/nba_gambling_$(date +\%Y\%m\%d).sql.gz
```

### Timezone

Set server timezone to US Eastern for correct scheduling:

```bash
timedatectl set-timezone America/New_York
```

---

## 10. Service User (Optional)

For production, create a dedicated service user:

```bash
# Create user
useradd -r -m -d /opt/nba_gambling -s /bin/bash nba_scraper

# Set ownership
chown -R nba_scraper:nba_scraper /opt/nba_gambling

# Add to crontab for service user
crontab -u nba_scraper -e
```

---

## 11. Monitoring & Logging

### Log Files

| Log | Location | Purpose |
|-----|----------|---------|
| Scraper log | `/opt/nba_gambling/logs/scraper.log` | Application events |
| Cron log | `/opt/nba_gambling/logs/cron.log` | Scheduled run output |
| MySQL log | `/var/log/mysql/error.log` | Database errors |

### Health Check Script

```bash
#!/bin/bash
# /opt/nba_gambling/deploy/healthcheck.sh

# Check MySQL
mysqladmin ping -u nba_scraper -p'PASSWORD' > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "CRITICAL: MySQL is down"
    exit 1
fi

# Check Chrome
google-chrome --version > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "CRITICAL: Chrome not installed"
    exit 1
fi

# Check last scrape (should be within 25 hours)
LAST_SCRAPE=$(mysql -u nba_scraper -p'PASSWORD' -N -e "SELECT TIMESTAMPDIFF(HOUR, MAX(scraped_at), NOW()) FROM nba_gambling.games;")
if [ "$LAST_SCRAPE" -gt 25 ]; then
    echo "WARNING: Last scrape was $LAST_SCRAPE hours ago"
    exit 1
fi

echo "OK: All systems operational"
exit 0
```

---

## 12. Security Checklist

- [ ] MySQL root password set
- [ ] Application user has minimal privileges (no GRANT, DROP)
- [ ] `.env` file has 600 permissions
- [ ] SSH key authentication only (disable password auth)
- [ ] UFW enabled with minimal open ports
- [ ] Automatic security updates enabled (`unattended-upgrades`)
- [ ] MySQL bound to localhost only (not 0.0.0.0)
- [ ] No credentials in code or git repository

---

## 13. Quick Setup Commands

```bash
# 1. Clone repository
git clone https://github.com/benashkar/nba_gambling.git /opt/nba_gambling
cd /opt/nba_gambling

# 2. Run automated setup (interactive - prompts for passwords)
sudo bash deploy/setup.sh

# 3. Test the installation
source venv/bin/activate
python main.py --season 2025-2026 --mysql --headless --max-pages 1

# 4. Setup cron
crontab -e
# Add the cron lines from section 9
```

---

## 14. Troubleshooting

### Chrome fails to start
```bash
# Check Chrome installation
google-chrome --version

# Test headless mode
google-chrome --headless --disable-gpu --dump-dom https://www.google.com
```

### MySQL connection refused
```bash
# Check MySQL is running
systemctl status mysql

# Test connection
mysql -u nba_scraper -p -e "SELECT 1"
```

### Scraper timeout
```bash
# Increase timeout in main.py or check network
curl -I https://www.oddsportal.com
```

---

## Contact

For questions about this specification, contact the development team.

Repository: https://github.com/benashkar/nba_gambling
