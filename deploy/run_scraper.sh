#!/bin/bash
# NBA Gambling Scraper - Daily Run Script
# This script is designed to be run by cron
#
# Usage: ./run_scraper.sh [--full]
#   --full: Run full historical scrape (all seasons)
#   default: Scrape only current season (faster daily update)

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

# Load environment variables
if [ -f "$APP_DIR/.env" ]; then
    export $(grep -v '^#' "$APP_DIR/.env" | xargs)
fi

# Activate virtual environment
source "$APP_DIR/venv/bin/activate"

# Change to app directory
cd "$APP_DIR"

# Timestamp for logging
echo "=========================================="
echo "NBA Scraper Run: $(date)"
echo "=========================================="

# Determine scrape mode
if [ "$1" == "--full" ]; then
    echo "Mode: Full historical scrape (all seasons)"
    SEASON_ARG="--all-seasons"
else
    echo "Mode: Current season only (2025-2026)"
    SEASON_ARG="--season 2025-2026"
fi

# Run the scraper
python main.py \
    $SEASON_ARG \
    --mysql \
    --headless \
    --resume \
    --log-file logs/scraper.log

echo ""
echo "Scrape completed: $(date)"
echo "=========================================="
