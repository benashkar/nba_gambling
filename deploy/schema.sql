-- NBA Gambling Database Schema
-- Run this script to initialize the database

CREATE DATABASE IF NOT EXISTS nba_gambling;
USE nba_gambling;

-- Main table for NBA game odds
CREATE TABLE IF NOT EXISTS games (
    id INT AUTO_INCREMENT PRIMARY KEY,
    game_id VARCHAR(50) NOT NULL UNIQUE,
    game_date DATE NOT NULL,
    season VARCHAR(20) NOT NULL,
    home_team VARCHAR(10) NOT NULL,
    away_team VARCHAR(10) NOT NULL,
    home_score DECIMAL(5,1) NULL,
    away_score DECIMAL(5,1) NULL,
    closing_spread DECIMAL(5,1) NULL,
    closing_over_under DECIMAL(5,1) NULL,
    closing_moneyline_home DECIMAL(10,1) NULL,
    closing_moneyline_away DECIMAL(10,1) NULL,
    scraped_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_game_date (game_date),
    INDEX idx_season (season),
    INDEX idx_home_team (home_team),
    INDEX idx_away_team (away_team),
    INDEX idx_scraped_at (scraped_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table for tracking scrape runs
CREATE TABLE IF NOT EXISTS scrape_runs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    scraper_name VARCHAR(100) NOT NULL,
    season VARCHAR(20) NULL,
    started_at DATETIME NOT NULL,
    completed_at DATETIME NULL,
    games_scraped INT DEFAULT 0,
    games_inserted INT DEFAULT 0,
    games_updated INT DEFAULT 0,
    status ENUM('running', 'completed', 'failed') DEFAULT 'running',
    error_message TEXT NULL,

    INDEX idx_scraper_name (scraper_name),
    INDEX idx_started_at (started_at),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- View for recent games with full details
CREATE OR REPLACE VIEW recent_games AS
SELECT
    game_id,
    game_date,
    season,
    away_team,
    home_team,
    CONCAT(away_score, ' - ', home_score) AS score,
    closing_spread,
    closing_over_under,
    closing_moneyline_away AS ml_away,
    closing_moneyline_home AS ml_home,
    CASE
        WHEN home_score > away_score THEN home_team
        WHEN away_score > home_score THEN away_team
        ELSE 'TIE'
    END AS winner,
    (home_score + away_score) AS total_points,
    CASE
        WHEN (home_score + away_score) > closing_over_under THEN 'OVER'
        WHEN (home_score + away_score) < closing_over_under THEN 'UNDER'
        ELSE 'PUSH'
    END AS over_under_result
FROM games
WHERE home_score IS NOT NULL
ORDER BY game_date DESC;

-- Grant permissions (adjust user/host as needed)
-- CREATE USER IF NOT EXISTS 'nba_scraper'@'localhost' IDENTIFIED BY 'your_password_here';
-- GRANT SELECT, INSERT, UPDATE ON nba_gambling.* TO 'nba_scraper'@'localhost';
-- FLUSH PRIVILEGES;
