#!/bin/bash
# NBA Gambling Scraper - Server Setup Script
# Run this on a fresh Ubuntu 22.04+ server
#
# Usage: sudo bash setup.sh

set -e

echo "=========================================="
echo "NBA Gambling Scraper - Server Setup"
echo "=========================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo bash setup.sh)"
    exit 1
fi

# Get the non-root user (who ran sudo)
ACTUAL_USER=${SUDO_USER:-$USER}
APP_DIR="/home/$ACTUAL_USER/nba_gambling"

echo ""
echo "Configuration:"
echo "  User: $ACTUAL_USER"
echo "  App Directory: $APP_DIR"
echo ""

# Update system
echo "[1/8] Updating system packages..."
apt-get update && apt-get upgrade -y

# Install Python and dependencies
echo "[2/8] Installing Python and dependencies..."
apt-get install -y python3 python3-pip python3-venv git curl wget unzip

# Install Chrome for Selenium
echo "[3/8] Installing Google Chrome..."
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
apt-get update
apt-get install -y google-chrome-stable

# Install MySQL Server
echo "[4/8] Installing MySQL Server..."
apt-get install -y mysql-server

# Start and enable MySQL
systemctl start mysql
systemctl enable mysql

# Setup MySQL database and user
echo "[5/8] Setting up MySQL database..."
read -sp "Enter MySQL root password (leave empty if not set): " MYSQL_ROOT_PASS
echo ""
read -sp "Enter password for nba_scraper user: " NBA_SCRAPER_PASS
echo ""

# Create database and user
if [ -z "$MYSQL_ROOT_PASS" ]; then
    mysql -u root <<EOF
CREATE DATABASE IF NOT EXISTS nba_gambling;
CREATE USER IF NOT EXISTS 'nba_scraper'@'localhost' IDENTIFIED BY '$NBA_SCRAPER_PASS';
GRANT ALL PRIVILEGES ON nba_gambling.* TO 'nba_scraper'@'localhost';
FLUSH PRIVILEGES;
EOF
else
    mysql -u root -p"$MYSQL_ROOT_PASS" <<EOF
CREATE DATABASE IF NOT EXISTS nba_gambling;
CREATE USER IF NOT EXISTS 'nba_scraper'@'localhost' IDENTIFIED BY '$NBA_SCRAPER_PASS';
GRANT ALL PRIVILEGES ON nba_gambling.* TO 'nba_scraper'@'localhost';
FLUSH PRIVILEGES;
EOF
fi

echo "MySQL database 'nba_gambling' created"

# Clone or update the repository
echo "[6/8] Setting up application..."
if [ -d "$APP_DIR" ]; then
    echo "Directory exists, pulling latest..."
    cd "$APP_DIR"
    sudo -u $ACTUAL_USER git pull
else
    sudo -u $ACTUAL_USER git clone https://github.com/benashkar/nba_gambling.git "$APP_DIR"
    cd "$APP_DIR"
fi

# Create virtual environment and install dependencies
echo "[7/8] Setting up Python virtual environment..."
sudo -u $ACTUAL_USER python3 -m venv "$APP_DIR/venv"
sudo -u $ACTUAL_USER "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo -u $ACTUAL_USER "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# Initialize database schema
echo "[8/8] Initializing database schema..."
if [ -z "$MYSQL_ROOT_PASS" ]; then
    mysql -u root nba_gambling < "$APP_DIR/deploy/schema.sql" 2>/dev/null || true
else
    mysql -u root -p"$MYSQL_ROOT_PASS" nba_gambling < "$APP_DIR/deploy/schema.sql" 2>/dev/null || true
fi

# Create environment file
echo "Creating .env file..."
cat > "$APP_DIR/.env" <<EOF
# MySQL Configuration
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=nba_scraper
MYSQL_PASSWORD=$NBA_SCRAPER_PASS
MYSQL_DATABASE=nba_gambling
EOF
chown $ACTUAL_USER:$ACTUAL_USER "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

# Create directories
sudo -u $ACTUAL_USER mkdir -p "$APP_DIR/data/output" "$APP_DIR/logs" "$APP_DIR/checkpoints"

# Setup cron job
echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "To test the scraper:"
echo "  cd $APP_DIR"
echo "  source venv/bin/activate"
echo "  source .env"
echo "  python main.py --all-seasons --mysql --headless"
echo ""
echo "To setup daily cron job (runs at 6 AM):"
echo "  crontab -e"
echo "  Add: 0 6 * * * cd $APP_DIR && ./deploy/run_scraper.sh >> logs/cron.log 2>&1"
echo ""
echo "Environment file created at: $APP_DIR/.env"
echo "MySQL password stored in .env (chmod 600)"
echo ""
