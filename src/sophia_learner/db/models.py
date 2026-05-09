"""
Database models for Sophia Learner.

This module provides dataclasses representing the database schema
and functions to create tables and manage schema migrations.
"""

import json
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional, Any

from sophia_learner.db.database import Database


@dataclass
class FileRecord:
    """Record representing a file in the system."""
    id: int
    path: Path
    filename: str
    version: Optional[str]
    sha256: str
    size_bytes: int
    mime_type: str
    first_seen: datetime
    last_modified: datetime
    status: Literal["pending", "quarantined", "processing", "processed", "failed", "conflicting"]
    assigned_priority: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert the record to a dictionary for JSON serialization."""
        data = asdict(self)
        # Convert Path to string for JSON serialization
        data["path"] = str(self.path)
        # Convert datetime to ISO format
        if isinstance(self.first_seen, datetime):
            data["first_seen"] = self.first_seen.isoformat()
        if isinstance(self.last_modified, datetime):
            data["last_modified"] = self.last_modified.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FileRecord':
        """Create a FileRecord from a dictionary."""
        # Convert string path back to Path
        if "path" in data and isinstance(data["path"], str):
            data["path"] = Path(data["path"])
        # Convert ISO datetime strings back to datetime
        if "first_seen" in data and isinstance(data["first_seen"], str):
            data["first_seen"] = datetime.fromisoformat(data["first_seen"])
        if "last_modified" in data and isinstance(data["last_modified"], str):
            data["last_modified"] = datetime.fromisoformat(data["last_modified"])
        return cls(**data)


@dataclass
class VersionRecord:
    """Record representing a file version."""
    file_id: int
    version_number: str
    parent_version: Optional[str]
    conflict_resolved: bool
    resolution_choice: Optional[str]
    resolved_by: Optional[str]
    resolved_at: Optional[datetime]

    def to_dict(self) -> Dict[str, Any]:
        """Convert the record to a dictionary."""
        data = asdict(self)
        if self.resolved_at:
            data["resolved_at"] = self.resolved_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VersionRecord':
        """Create a VersionRecord from a dictionary."""
        if "resolved_at" in data and data["resolved_at"]:
            data["resolved_at"] = datetime.fromisoformat(data["resolved_at"])
        return cls(**data)


@dataclass
class ProcessingLog:
    """Record representing a processing log entry."""
    id: int
    file_id: int
    status: str
    stage: str
    message: str
    created_at: datetime
    retry_count: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert the record to a dictionary."""
        data = asdict(self)
        if isinstance(self.created_at, datetime):
            data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProcessingLog':
        """Create a ProcessingLog from a dictionary."""
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


@dataclass
class ConflictRecord:
    """Record representing a version conflict."""
    id: int
    file_group: str
    versions: List[str]
    status: Literal["pending", "resolved"]
    created_at: datetime
    resolved_at: Optional[datetime]

    def to_dict(self) -> Dict[str, Any]:
        """Convert the record to a dictionary."""
        data = asdict(self)
        if isinstance(self.created_at, datetime):
            data["created_at"] = self.created_at.isoformat()
        if self.resolved_at:
            data["resolved_at"] = self.resolved_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConflictRecord':
        """Create a ConflictRecord from a dictionary."""
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "resolved_at" in data and data["resolved_at"]:
            data["resolved_at"] = datetime.fromisoformat(data["resolved_at"])
        return cls(**data)


@dataclass
class MetricRecord:
    """Record representing daily metrics."""
    id: int
    date: date
    files_processed: int
    tokens_processed: int
    avg_processing_time_seconds: float
    ai_call_count: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert the record to a dictionary."""
        data = asdict(self)
        if isinstance(self.date, date):
            data["date"] = self.date.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MetricRecord':
        """Create a MetricRecord from a dictionary."""
        if "date" in data and isinstance(data["date"], str):
            data["date"] = date.fromisoformat(data["date"])
        return cls(**data)


@dataclass
class ScheduleLog:
    """Record representing a processing schedule log."""
    id: int
    scheduled_start: datetime
    actual_start: datetime
    actual_end: datetime
    files_processed: int
    window_name: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert the record to a dictionary."""
        data = asdict(self)
        for field in ["scheduled_start", "actual_start", "actual_end"]:
            if field in data and isinstance(data[field], datetime):
                data[field] = data[field].isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScheduleLog':
        """Create a ScheduleLog from a dictionary."""
        for field in ["scheduled_start", "actual_start", "actual_end"]:
            if field in data and isinstance(data[field], str):
                data[field] = datetime.fromisoformat(data[field])
        return cls(**data)


def create_tables(db: Database) -> None:
    """
    Create all tables if they don't exist.

    Args:
        db: Database instance for executing SQL.
    """
    # Files table
    db.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            version TEXT,
            sha256 TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL,
            mime_type TEXT NOT NULL,
            first_seen TIMESTAMP NOT NULL,
            last_modified TIMESTAMP NOT NULL,
            status TEXT NOT NULL,
            assigned_priority INTEGER DEFAULT 5,
            CHECK (status IN ('pending', 'quarantined', 'processing', 'processed', 'failed', 'conflicting'))
        )
    """, commit=True)

    # Versions table
    db.execute("""
        CREATE TABLE IF NOT EXISTS versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            version_number TEXT NOT NULL,
            parent_version TEXT,
            conflict_resolved BOOLEAN DEFAULT 0,
            resolution_choice TEXT,
            resolved_by TEXT,
            resolved_at TIMESTAMP,
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
            UNIQUE(file_id, version_number)
        )
    """, commit=True)

    # Processing logs table
    db.execute("""
        CREATE TABLE IF NOT EXISTS processing_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            retry_count INTEGER DEFAULT 0,
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        )
    """, commit=True)

    # Conflicts table
    db.execute("""
        CREATE TABLE IF NOT EXISTS conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_group TEXT NOT NULL,
            versions TEXT NOT NULL,  -- JSON array of version strings
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            CHECK (status IN ('pending', 'resolved'))
        )
    """, commit=True)

    # Metrics table
    db.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL UNIQUE,
            files_processed INTEGER DEFAULT 0,
            tokens_processed INTEGER DEFAULT 0,
            avg_processing_time_seconds REAL DEFAULT 0.0,
            ai_call_count INTEGER DEFAULT 0
        )
    """, commit=True)

    # Schedule logs table
    db.execute("""
        CREATE TABLE IF NOT EXISTS schedule_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scheduled_start TIMESTAMP NOT NULL,
            actual_start TIMESTAMP NOT NULL,
            actual_end TIMESTAMP NOT NULL,
            files_processed INTEGER DEFAULT 0,
            window_name TEXT NOT NULL
        )
    """, commit=True)

    # Schema versions table for migrations
    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """, commit=True)


def _get_current_version(db: Database) -> int:
    """
    Get the current schema version.

    Args:
        db: Database instance.

    Returns:
        Current schema version, or 0 if no version is set.
    """
    try:
        result = db.fetchone("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        if result:
            return result[0]
        return 0
    except Exception:
        # Table might not exist yet
        return 0


def _set_schema_version(db: Database, version: int) -> None:
    """
    Set the current schema version.

    Args:
        db: Database instance.
        version: Version number to set.
    """
    db.execute("INSERT INTO schema_version (version) VALUES (?)", (version,), commit=True)


def migrate_schema(db: Database, target_version: int) -> None:
    """
    Apply schema migrations incrementally.

    Args:
        db: Database instance.
        target_version: Target schema version to migrate to.
    """
    current_version = _get_current_version(db)
    
    if current_version >= target_version:
        return
    
    # Define migration steps (version -> SQL)
    migrations = {
        1: """
            -- Version 1: Initial schema (handled by create_tables)
            INSERT INTO schema_version (version) VALUES (1);
        """,
        2: """
            -- Version 2: Add indexes for better performance
            CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
            CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
            CREATE INDEX IF NOT EXISTS idx_files_first_seen ON files(first_seen);
            CREATE INDEX IF NOT EXISTS idx_versions_file_id ON versions(file_id);
            CREATE INDEX IF NOT EXISTS idx_processing_logs_file_id ON processing_logs(file_id);
            CREATE INDEX IF NOT EXISTS idx_processing_logs_created_at ON processing_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_conflicts_status ON conflicts(status);
            CREATE INDEX IF NOT EXISTS idx_metrics_date ON metrics(date);
        """,
        3: """
            -- Version 3: Add retry_count column to files for better retry tracking
            ALTER TABLE files ADD COLUMN retry_count INTEGER DEFAULT 0;
        """,
        4: """
            -- Version 4: Add processing_duration column to processing_logs
            ALTER TABLE processing_logs ADD COLUMN processing_duration_ms INTEGER;
        """,
        5: """
            -- Version 5: Add file_group column to files for logical grouping
            ALTER TABLE files ADD COLUMN file_group TEXT;
            CREATE INDEX IF NOT EXISTS idx_files_file_group ON files(file_group);
        """,
    }
    
    # Apply migrations in order
    for version in range(current_version + 1, target_version + 1):
        if version not in migrations:
            continue
        
        try:
            # Execute migration SQL
            migration_sql = migrations[version]
            # Split into individual statements
            statements = [s.strip() for s in migration_sql.split(';') if s.strip()]
            for stmt in statements:
                if stmt:
                    db.execute(stmt, commit=False)
            
            # Update schema version if not already set by migration
            if "INSERT INTO schema_version" not in migration_sql:
                _set_schema_version(db, version)
            
            db.commit()
            
        except Exception as e:
            db.rollback()
            raise RuntimeError(f"Failed to apply schema migration to version {version}: {e}") from e
