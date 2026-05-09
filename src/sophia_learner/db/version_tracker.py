"""
Version tracking module for Sophia Learner.

This module provides methods for managing file versions and detecting/resolving
version conflicts in the document processing pipeline.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sophia_learner.db.database import Database
from sophia_learner.db.models import ConflictRecord, VersionRecord

logger = logging.getLogger(__name__)


class VersionTracker:
    """
    Version and conflict management for tracked files.

    This class provides methods to register file versions, retrieve version chains,
    detect conflicts between multiple versions of the same logical file, and resolve
    those conflicts through manual or automatic resolution.
    """

    def __init__(self, db: Database):
        """
        Initialize the VersionTracker with a database connection.

        Args:
            db: Database instance for executing queries.
        """
        self._db = db

    def register_version(
        self, file_id: int, version_number: str, parent_version: Optional[str] = None
    ) -> None:
        """
        Register a new version for a file.

        Args:
            file_id: ID of the file record.
            version_number: Version string (e.g., "1", "2.5", "v3").
            parent_version: Optional parent version string.
        """
        query = """
            INSERT INTO versions (file_id, version_number, parent_version, conflict_resolved)
            VALUES (?, ?, ?, 0)
        """
        self._db.execute(query, (file_id, version_number, parent_version), commit=True)
        logger.debug(f"Registered version {version_number} for file {file_id}")

    def get_version_chain(self, file_path: Path) -> List[VersionRecord]:
        """
        Return all versions of the same logical file.

        Args:
            file_path: Path to the file (base name is used for grouping).

        Returns:
            List of VersionRecord objects for all versions of this file.
        """
        # First, find all files with the same base name (ignoring version suffixes)
        # This uses the file_group field from the files table
        query = """
            SELECT f.id, f.path, f.filename, f.version, f.sha256, f.size_bytes,
                   f.mime_type, f.first_seen, f.last_modified, f.status, f.assigned_priority,
                   v.version_number, v.parent_version, v.conflict_resolved,
                   v.resolution_choice, v.resolved_by, v.resolved_at
            FROM files f
            JOIN versions v ON f.id = v.file_id
            WHERE f.file_group = (
                SELECT file_group FROM files WHERE path = ?
            ) OR f.path = ?
            ORDER BY v.version_number
        """
        results = self._db.fetchall(query, (str(file_path), str(file_path)))
        
        version_records = []
        for row in results:
            # Row format: f.id, f.path, f.filename, f.version, f.sha256, f.size_bytes,
            #            f.mime_type, f.first_seen, f.last_modified, f.status, f.assigned_priority,
            #            v.version_number, v.parent_version, v.conflict_resolved,
            #            v.resolution_choice, v.resolved_by, v.resolved_at
            version_records.append(
                VersionRecord(
                    file_id=row[0],
                    version_number=row[11],
                    parent_version=row[12],
                    conflict_resolved=bool(row[13]),
                    resolution_choice=row[14],
                    resolved_by=row[15],
                    resolved_at=datetime.fromisoformat(row[16]) if row[16] else None,
                )
            )
        
        return version_records

    def detect_conflict(self, file_group: str, versions: List[str]) -> Optional[int]:
        """
        Check if a conflict already exists for this file group.

        Args:
            file_group: Logical file group identifier.
            versions: List of version strings in this group.

        Returns:
            Conflict ID if a pending conflict exists, None otherwise.
        """
        # Serialize versions to JSON for comparison
        versions_json = json.dumps(sorted(versions))
        
        query = """
            SELECT id FROM conflicts
            WHERE file_group = ? AND status = 'pending'
        """
        result = self._db.fetchone(query, (file_group,))
        
        if result:
            return result[0]
        return None

    def create_conflict(self, file_group: str, versions: List[str]) -> int:
        """
        Create a new conflict record for a version group.

        Args:
            file_group: Logical file group identifier.
            versions: List of version strings in conflict.

        Returns:
            ID of the newly created conflict record.
        """
        versions_json = json.dumps(sorted(versions))
        
        query = """
            INSERT INTO conflicts (file_group, versions, status, created_at)
            VALUES (?, ?, 'pending', ?)
        """
        cursor = self._db.execute(
            query, (file_group, versions_json, datetime.now().isoformat()), commit=True
        )
        conflict_id = cursor.lastrowid
        
        # Also mark all files in this group as conflicting
        # First, get all file IDs for this group
        file_query = """
            UPDATE files
            SET status = 'conflicting'
            WHERE file_group = ?
        """
        self._db.execute(file_query, (file_group,), commit=True)
        
        logger.info(f"Created conflict {conflict_id} for group {file_group} with versions {versions}")
        return conflict_id

    def resolve_conflict(
        self, conflict_id: int, chosen_version: str, resolved_by: str = "user"
    ) -> None:
        """
        Resolve a version conflict.

        Args:
            conflict_id: ID of the conflict to resolve.
            chosen_version: Version string that was chosen.
            resolved_by: Identifier of who/what resolved the conflict (user, auto, etc.).
        """
        # Update conflict record
        query = """
            UPDATE conflicts
            SET status = 'resolved', resolved_at = ?
            WHERE id = ?
        """
        self._db.execute(query, (datetime.now().isoformat(), conflict_id), commit=True)
        
        # Get the conflict to find the file group
        conflict_query = "SELECT file_group, versions FROM conflicts WHERE id = ?"
        conflict = self._db.fetchone(conflict_query, (conflict_id,))
        
        if conflict:
            file_group = conflict[0]
            versions = json.loads(conflict[1])
            
            # Mark the chosen version as resolved in the versions table
            # First, find the file with the chosen version
            file_query = """
                SELECT f.id FROM files f
                JOIN versions v ON f.id = v.file_id
                WHERE f.file_group = ? AND v.version_number = ?
            """
            file_result = self._db.fetchone(file_query, (file_group, chosen_version))
            
            if file_result:
                self.mark_version_as_resolved(file_result[0], chosen_version)
            
            # For other versions, mark them as superseded? No, just update file status
            # Update file status for all files in group
            status_query = """
                UPDATE files
                SET status = 'processed'
                WHERE file_group = ? AND id != ?
            """
            if file_result:
                self._db.execute(status_query, (file_group, file_result[0]), commit=True)
            
            # Update the chosen file's status
            if file_result:
                status_query_chosen = """
                    UPDATE files
                    SET status = 'processed'
                    WHERE id = ?
                """
                self._db.execute(status_query_chosen, (file_result[0],), commit=True)
        
        logger.info(f"Resolved conflict {conflict_id} with chosen version {chosen_version}")

    def get_pending_conflicts(self) -> List[ConflictRecord]:
        """
        Get all pending conflicts.

        Returns:
            List of ConflictRecord objects with status='pending'.
        """
        query = """
            SELECT id, file_group, versions, status, created_at, resolved_at
            FROM conflicts
            WHERE status = 'pending'
            ORDER BY created_at ASC
        """
        results = self._db.fetchall(query)
        
        conflicts = []
        for row in results:
            conflicts.append(
                ConflictRecord(
                    id=row[0],
                    file_group=row[1],
                    versions=json.loads(row[2]),
                    status=row[3],
                    created_at=datetime.fromisoformat(row[4]),
                    resolved_at=datetime.fromisoformat(row[5]) if row[5] else None,
                )
            )
        
        return conflicts

    def mark_version_as_resolved(self, file_id: int, resolution: str) -> None:
        """
        Mark a specific version as resolved.

        Args:
            file_id: ID of the file/version to mark as resolved.
            resolution: Resolution choice (version string or "auto").
        """
        query = """
            UPDATE versions
            SET conflict_resolved = 1, resolution_choice = ?, resolved_by = 'system', resolved_at = ?
            WHERE file_id = ?
        """
        self._db.execute(
            query, (resolution, datetime.now().isoformat(), file_id), commit=True
        )
        logger.debug(f"Marked version for file {file_id} as resolved with choice {resolution}")

    def get_conflict_by_id(self, conflict_id: int) -> Optional[ConflictRecord]:
        """
        Get a conflict record by its ID.

        Args:
            conflict_id: ID of the conflict.

        Returns:
            ConflictRecord if found, None otherwise.
        """
        query = """
            SELECT id, file_group, versions, status, created_at, resolved_at
            FROM conflicts
            WHERE id = ?
        """
        result = self._db.fetchone(query, (conflict_id,))
        
        if result:
            return ConflictRecord(
                id=result[0],
                file_group=result[1],
                versions=json.loads(result[2]),
                status=result[3],
                created_at=datetime.fromisoformat(result[4]),
                resolved_at=datetime.fromisoformat(result[5]) if result[5] else None,
            )
        return None

    def get_files_in_conflict(self, conflict_id: int) -> List[int]:
        """
        Get all file IDs involved in a conflict.

        Args:
            conflict_id: ID of the conflict.

        Returns:
            List of file IDs.
        """
        conflict = self.get_conflict_by_id(conflict_id)
        if not conflict:
            return []
        
        # Find all files with matching file_group
        query = "SELECT id FROM files WHERE file_group = ?"
        results = self._db.fetchall(query, (conflict.file_group,))
        
        return [row[0] for row in results]
