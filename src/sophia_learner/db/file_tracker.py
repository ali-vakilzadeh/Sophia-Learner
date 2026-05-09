"""
File tracking module for Sophia Learner.

This module provides CRUD operations for managing file records in the database.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from sqlite3 import IntegrityError

from sophia_learner.db.database import Database
from sophia_learner.db.models import FileRecord

logger = logging.getLogger(__name__)


class FileTracker:
    """
    CRUD operations for file records.

    This class provides methods to add, retrieve, update, and query file records
    in the SQLite database, with proper error handling and parameterized queries.
    """

    def __init__(self, db: Database):
        """
        Initialize the FileTracker with a database connection.

        Args:
            db: Database instance for executing queries.
        """
        self._db = db

    def add_file(self, file_record: FileRecord) -> int:
        """
        Insert a new file record into the database.

        Args:
            file_record: FileRecord instance to insert.

        Returns:
            The auto-generated ID of the new record.

        Raises:
            IntegrityError: If a file with the same SHA256 already exists.
        """
        query = """
            INSERT INTO files (
                path, filename, version, sha256, size_bytes, mime_type,
                first_seen, last_modified, status, assigned_priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            str(file_record.path),
            file_record.filename,
            file_record.version,
            file_record.sha256,
            file_record.size_bytes,
            file_record.mime_type,
            file_record.first_seen.isoformat(),
            file_record.last_modified.isoformat(),
            file_record.status,
            file_record.assigned_priority,
        )

        try:
            cursor = self._db.execute(query, params, commit=True)
            file_id = cursor.lastrowid
            logger.info(f"Added file record: {file_record.filename} (ID: {file_id})")
            return file_id
        except IntegrityError as e:
            logger.error(f"File with SHA256 {file_record.sha256} already exists")
            raise IntegrityError(f"File with SHA256 {file_record.sha256} already exists") from e

    def get_file_by_path(self, path: Path, version: Optional[str] = None) -> Optional[FileRecord]:
        """
        Retrieve a file record by its path and optional version.

        Args:
            path: Path to the file.
            version: Optional version string to match.

        Returns:
            FileRecord if found, None otherwise.
        """
        if version:
            query = """
                SELECT id, path, filename, version, sha256, size_bytes, mime_type,
                       first_seen, last_modified, status, assigned_priority
                FROM files
                WHERE path = ? AND version = ?
            """
            params = (str(path), version)
        else:
            query = """
                SELECT id, path, filename, version, sha256, size_bytes, mime_type,
                       first_seen, last_modified, status, assigned_priority
                FROM files
                WHERE path = ?
                ORDER BY first_seen DESC LIMIT 1
            """
            params = (str(path),)

        result = self._db.fetchone(query, params)
        if result:
            return self._row_to_file_record(result)
        return None

    def get_file_by_sha256(self, sha256: str) -> Optional[FileRecord]:
        """
        Retrieve a file record by its SHA256 hash.

        Args:
            sha256: SHA256 hash of the file.

        Returns:
            FileRecord if found, None otherwise.
        """
        query = """
            SELECT id, path, filename, version, sha256, size_bytes, mime_type,
                   first_seen, last_modified, status, assigned_priority
            FROM files
            WHERE sha256 = ?
        """
        result = self._db.fetchone(query, (sha256,))
        if result:
            return self._row_to_file_record(result)
        return None

    def get_pending_files(self, limit: int = 100) -> List[FileRecord]:
        """
        Get files with status='pending', ordered by priority (higher first) and first_seen.

        Args:
            limit: Maximum number of files to return.

        Returns:
            List of FileRecord objects.
        """
        query = """
            SELECT id, path, filename, version, sha256, size_bytes, mime_type,
                   first_seen, last_modified, status, assigned_priority
            FROM files
            WHERE status = 'pending'
            ORDER BY assigned_priority DESC, first_seen ASC
            LIMIT ?
        """
        results = self._db.fetchall(query, (limit,))
        return [self._row_to_file_record(row) for row in results]

    def update_file_status(self, file_id: int, status: str, message: Optional[str] = None) -> None:
        """
        Update the status of a file record.

        Args:
            file_id: ID of the file to update.
            status: New status value.
            message: Optional log message to record.
        """
        # Update file status
        query = """
            UPDATE files
            SET status = ?
            WHERE id = ?
        """
        self._db.execute(query, (status, file_id), commit=True)
        
        # Log the status change
        if message:
            log_query = """
                INSERT INTO processing_logs (file_id, status, stage, message, created_at, retry_count)
                VALUES (?, ?, 'status_update', ?, ?, 0)
            """
            self._db.execute(log_query, (file_id, status, message, datetime.now().isoformat()), commit=True)
        
        logger.debug(f"Updated file {file_id} status to {status}")

    def file_exists(self, sha256: str) -> bool:
        """
        Check if a file with the given SHA256 exists in the database.

        Args:
            sha256: SHA256 hash to check.

        Returns:
            True if file exists, False otherwise.
        """
        query = "SELECT 1 FROM files WHERE sha256 = ? LIMIT 1"
        result = self._db.fetchone(query, (sha256,))
        return result is not None

    def get_failed_files(self, retry_limit: int = 3) -> List[FileRecord]:
        """
        Get files with status='failed' that have been retried less than the retry limit.

        Args:
            retry_limit: Maximum number of retries allowed.

        Returns:
            List of FileRecord objects that can be retried.
        """
        query = """
            SELECT id, path, filename, version, sha256, size_bytes, mime_type,
                   first_seen, last_modified, status, assigned_priority
            FROM files
            WHERE status = 'failed' AND retry_count < ?
            ORDER BY first_seen ASC
        """
        results = self._db.fetchall(query, (retry_limit,))
        return [self._row_to_file_record(row) for row in results]

    def increment_retry_count(self, file_id: int) -> None:
        """
        Increment the retry count for a failed file.

        Args:
            file_id: ID of the file to update.
        """
        query = """
            UPDATE files
            SET retry_count = retry_count + 1
            WHERE id = ?
        """
        self._db.execute(query, (file_id,), commit=True)
        logger.debug(f"Incremented retry count for file {file_id}")

    def get_statistics(self) -> Dict[str, int]:
        """
        Get counts of files grouped by status.

        Returns:
            Dictionary with status names as keys and counts as values.
        """
        query = """
            SELECT status, COUNT(*) as count
            FROM files
            GROUP BY status
        """
        results = self._db.fetchall(query)
        stats = {}
        for row in results:
            stats[row[0]] = row[1]
        
        # Ensure all status types are present with default 0
        for status in ["pending", "quarantined", "processing", "processed", "failed", "conflicting"]:
            if status not in stats:
                stats[status] = 0
        
        return stats

    def get_file_by_id(self, file_id: int) -> Optional[FileRecord]:
        """
        Retrieve a file record by its ID.

        Args:
            file_id: ID of the file to retrieve.

        Returns:
            FileRecord if found, None otherwise.
        """
        query = """
            SELECT id, path, filename, version, sha256, size_bytes, mime_type,
                   first_seen, last_modified, status, assigned_priority
            FROM files
            WHERE id = ?
        """
        result = self._db.fetchone(query, (file_id,))
        if result:
            return self._row_to_file_record(result)
        return None

    def delete_file(self, file_id: int) -> bool:
        """
        Delete a file record from the database.

        Args:
            file_id: ID of the file to delete.

        Returns:
            True if deleted, False if not found.
        """
        # Check if file exists
        if not self.get_file_by_id(file_id):
            return False
        
        query = "DELETE FROM files WHERE id = ?"
        self._db.execute(query, (file_id,), commit=True)
        logger.info(f"Deleted file record {file_id}")
        return True

    def _row_to_file_record(self, row) -> FileRecord:
        """
        Convert a database row to a FileRecord object.

        Args:
            row: Database row (tuple or sqlite3.Row).

        Returns:
            FileRecord instance.
        """
        # Handle both tuple and sqlite3.Row
        if hasattr(row, 'keys'):
            # sqlite3.Row object
            return FileRecord(
                id=row['id'],
                path=Path(row['path']),
                filename=row['filename'],
                version=row['version'],
                sha256=row['sha256'],
                size_bytes=row['size_bytes'],
                mime_type=row['mime_type'],
                first_seen=datetime.fromisoformat(row['first_seen']),
                last_modified=datetime.fromisoformat(row['last_modified']),
                status=row['status'],
                assigned_priority=row['assigned_priority'],
            )
        else:
            # Tuple
            return FileRecord(
                id=row[0],
                path=Path(row[1]),
                filename=row[2],
                version=row[3],
                sha256=row[4],
                size_bytes=row[5],
                mime_type=row[6],
                first_seen=datetime.fromisoformat(row[7]),
                last_modified=datetime.fromisoformat(row[8]),
                status=row[9],
                assigned_priority=row[10],
            )
