"""Database connection handling for MySQL."""

import os
import logging
from typing import Optional
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling, Error as MySQLError

logger = logging.getLogger(__name__)

# Global connection pool
_connection_pool: Optional[pooling.MySQLConnectionPool] = None


class DatabaseConnection:
    """Manages MySQL database connections."""

    def __init__(
        self,
        host: str = None,
        port: int = None,
        user: str = None,
        password: str = None,
        database: str = None,
        pool_size: int = 5
    ):
        """
        Initialize database connection settings.

        Args:
            host: MySQL host (default: from env or localhost)
            port: MySQL port (default: from env or 3306)
            user: MySQL user (default: from env)
            password: MySQL password (default: from env)
            database: Database name (default: from env or nba_gambling)
            pool_size: Connection pool size
        """
        self.config = {
            'host': host or os.getenv('MYSQL_HOST', 'localhost'),
            'port': port or int(os.getenv('MYSQL_PORT', '3306')),
            'user': user or os.getenv('MYSQL_USER', 'nba_scraper'),
            'password': password or os.getenv('MYSQL_PASSWORD', ''),
            'database': database or os.getenv('MYSQL_DATABASE', 'nba_gambling'),
            'charset': 'utf8mb4',
            'collation': 'utf8mb4_unicode_ci',
            'autocommit': False,
        }
        self.pool_size = pool_size
        self._pool: Optional[pooling.MySQLConnectionPool] = None

    def init_pool(self) -> pooling.MySQLConnectionPool:
        """Initialize the connection pool."""
        if self._pool is None:
            try:
                self._pool = pooling.MySQLConnectionPool(
                    pool_name="nba_gambling_pool",
                    pool_size=self.pool_size,
                    pool_reset_session=True,
                    **self.config
                )
                logger.info(f"Database connection pool initialized: {self.config['host']}:{self.config['port']}/{self.config['database']}")
            except MySQLError as e:
                logger.error(f"Failed to create connection pool: {e}")
                raise
        return self._pool

    @contextmanager
    def get_connection(self):
        """
        Get a connection from the pool.

        Yields:
            MySQL connection object

        Usage:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                ...
        """
        if self._pool is None:
            self.init_pool()

        conn = None
        try:
            conn = self._pool.get_connection()
            yield conn
        except MySQLError as e:
            logger.error(f"Database error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn and conn.is_connected():
                conn.close()

    @contextmanager
    def get_cursor(self, dictionary: bool = True):
        """
        Get a cursor with automatic connection handling.

        Args:
            dictionary: If True, return results as dictionaries

        Yields:
            MySQL cursor object
        """
        with self.get_connection() as conn:
            cursor = conn.cursor(dictionary=dictionary)
            try:
                yield cursor
                conn.commit()
            except MySQLError as e:
                conn.rollback()
                raise
            finally:
                cursor.close()

    def test_connection(self) -> bool:
        """Test the database connection."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                logger.info("Database connection test successful")
                return result is not None
        except MySQLError as e:
            logger.error(f"Database connection test failed: {e}")
            return False

    def close(self):
        """Close all connections in the pool."""
        if self._pool:
            # Note: mysql.connector pool doesn't have explicit close
            # Connections are closed when returned to pool
            self._pool = None
            logger.info("Database connection pool closed")


# Singleton instance for convenience
_db_instance: Optional[DatabaseConnection] = None


def get_connection() -> DatabaseConnection:
    """Get the global database connection instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseConnection()
    return _db_instance


def init_database(
    host: str = None,
    port: int = None,
    user: str = None,
    password: str = None,
    database: str = None
) -> DatabaseConnection:
    """
    Initialize the global database connection.

    Args:
        host: MySQL host
        port: MySQL port
        user: MySQL user
        password: MySQL password
        database: Database name

    Returns:
        DatabaseConnection instance
    """
    global _db_instance
    _db_instance = DatabaseConnection(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database
    )
    _db_instance.init_pool()
    return _db_instance
