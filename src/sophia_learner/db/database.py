"""
Database management module for Sophia Learner.

This module provides a singleton Database class for managing SQLite connections,
with thread-safe access, parameterized queries, and backup functionality.
"""

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional, Tuple, Union
import logging

logger = logging.getLogger(__name__)

# Global singleton holder for the database connection
_DB_CONNECTION: Optional[sqlite3.Connection] = None


class Database:
    """
    Singleton manager for SQLite database connections.

    This class provides thread-safe database access using threading.local(),
    parameterized queries to prevent SQL injection, and methods for common
    database operations including backup and vacuum.
    """

    def __init__(self, db_path: Path, foreign_keys: bool = True):
        """
        Initialize the database manager.

        Args:
            db_path: Path to the SQLite database file.
            foreign_keys: Whether to enable foreign key constraints.
        """
        self._db_path = Path(db_path).resolve()
        self._foreign_keys = foreign_keys
        self._local = threading.local()
        self._lock = threading.Lock()
        
        # Ensure the database directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize the connection if needed
        self.connect()
        
        # Enable foreign keys if requested
        if self._foreign_keys:
            self.execute("PRAGMA foreign_keys = ON;")

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get the thread-local connection.

        Returns:
            sqlite3.Connection for the current thread.
        """
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                str(self._db_path),
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            # Enable row factory for dictionary-like access
            self._local.connection.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrency
            self._local.connection.execute("PRAGMA journal_mode=WAL;")
            # Set timeout for locked database (5 seconds)
            self._local.connection.execute(f"PRAGMA busy_timeout = {5 * 1000};")
        return self._local.connection

    def connect(self) -> sqlite3.Connection:
        """
        Create or return the existing thread-local connection.

        Returns:
            sqlite3.Connection object for the current thread.
        """
        return self._get_connection()

    def execute(
        self,
        query: str,
        params: Union[tuple, dict] = (),
        commit: bool = False
    ) -> sqlite3.Cursor:
        """
        Execute a parameterized SQL query.

        Args:
            query: SQL query string with placeholders.
            params: Parameters for the query (tuple or dict).
            commit: Whether to automatically commit after execution.

        Returns:
            sqlite3.Cursor object.

        Raises:
            sqlite3.Error: If the query execution fails.
        """
        conn = self._get_connection()
        try:
            if isinstance(params, dict):
                cursor = conn.execute(query, params)
            else:
                cursor = conn.execute(query, params)
            if commit:
                conn.commit()
            return cursor
        except sqlite3.Error as e:
            logger.error(f"Query execution failed: {query[:200]}... Error: {e}")
            conn.rollback()
            raise

    def executemany(
        self,
        query: str,
        params_list: List[Union[tuple, dict]],
        commit: bool = False
    ) -> sqlite3.Cursor:
        """
        Execute a parameterized SQL query multiple times.

        Args:
            query: SQL query string with placeholders.
            params_list: List of parameter sets (each a tuple or dict).
            commit: Whether to automatically commit after execution.

        Returns:
            sqlite3.Cursor object.

        Raises:
            sqlite3.Error: If the query execution fails.
        """
        conn = self._get_connection()
        try:
            cursor = conn.executemany(query, params_list)
            if commit:
                conn.commit()
            return cursor
        except sqlite3.Error as e:
            logger.error(f"Batch query execution failed: {query[:200]}... Error: {e}")
            conn.rollback()
            raise

    def fetchone(self, query: str, params: Union[tuple, dict] = ()) -> Optional[tuple]:
        """
        Execute a query and return a single row.

        Args:
            query: SQL query string with placeholders.
            params: Parameters for the query (tuple or dict).

        Returns:
            A single row as a tuple, or None if no rows found.
        """
        cursor = self.execute(query, params)
        return cursor.fetchone()

    def fetchall(self, query: str, params: Union[tuple, dict] = ()) -> List[tuple]:
        """
        Execute a query and return all rows.

        Args:
            query: SQL query string with placeholders.
            params: Parameters for the query (tuple or dict).

        Returns:
            List of rows as tuples.
        """
        cursor = self.execute(query, params)
        return cursor.fetchall()

    def commit(self) -> None:
        """Commit the current transaction."""
        conn = self._get_connection()
        conn.commit()
        logger.debug("Transaction committed")

    def rollback(self) -> None:
        """Rollback the current transaction."""
        conn = self._get_connection()
        conn.rollback()
        logger.debug("Transaction rolled back")

    def close(self) -> None:
        """
        Close the thread-local connection and clean up.
        """
        global _DB_CONNECTION
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
            logger.debug("Database connection closed")
        
        # If this is the main thread, clear the global reference
        with self._lock:
            if _DB_CONNECTION == self._local.connection:
                _DB_CONNECTION = None

    def backup(self, backup_path: Path) -> bool:
        """
        Create a hot backup of the database using SQLite online backup API.

        Args:
            backup_path: Path where the backup should be created.

        Returns:
            True if backup was successful, False otherwise.
        """
        backup_path = Path(backup_path).resolve()
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            conn = self._get_connection()
            # Create a connection to the backup file
            backup_conn = sqlite3.connect(str(backup_path))
            with backup_conn:
                conn.backup(backup_conn, pages=1, progress=None)
            backup_conn.close()
            logger.info(f"Database backup created at {backup_path}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Backup failed: {e}")
            return False

    def vacuum(self) -> None:
        """
        Rebuild the database to reclaim space and defragment.
        """
        try:
            logger.info("Starting VACUUM operation")
            self.execute("VACUUM;", commit=True)
            logger.info("VACUUM completed successfully")
        except sqlite3.Error as e:
            logger.error(f"VACUUM failed: {e}")
            raise

    def table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists in the database.

        Args:
            table_name: Name of the table to check.

        Returns:
            True if the table exists, False otherwise.
        """
        query = """
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name=?
        """
        result = self.fetchone(query, (table_name,))
        return result is not None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection."""
        self.close()
