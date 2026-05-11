"""
Quarantine - Securely store and manage files during processing

This module provides secure file storage throughout the processing pipeline,
with separate directories for different stages of the file lifecycle.
"""

import logging
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from ..utils.file_utils import ensure_directory, secure_delete, get_unique_filename
from ..utils.logger import get_logger, log_security_event

logger = get_logger(__name__)


class Quarantine:
    """
    Securely store files before, during, and after processing.
    
    The quarantine system maintains separate directories for different stages:
    - incoming: Raw files that have just been detected
    - processing: Files currently being processed (locked)
    - processed: Successfully processed files (kept for 30 days)
    - rejected: Files that failed security checks
    - conflicts: Files with version conflicts awaiting resolution
    
    Attributes:
        _root: Root quarantine directory
        _stages: Dictionary mapping stage names to subdirectory paths
    """
    
    # Stage names
    STAGE_INCOMING = "incoming"
    STAGE_PROCESSING = "processing"
    STAGE_PROCESSED = "processed"
    STAGE_REJECTED = "rejected"
    STAGE_CONFLICTS = "conflicts"
    
    # All valid stages
    VALID_STAGES = [STAGE_INCOMING, STAGE_PROCESSING, STAGE_PROCESSED, 
                    STAGE_REJECTED, STAGE_CONFLICTS]
    
    def __init__(self, quarantine_root: Path):
        """
        Initialize the quarantine manager.
        
        Args:
            quarantine_root: Root directory for quarantine storage
        """
        self._root = Path(quarantine_root).resolve()
        self._stages: Dict[str, Path] = {}
        
        # Create stage directories
        for stage in self.VALID_STAGES:
            stage_path = self._root / stage
            ensure_directory(stage_path, mode=0o750)
            self._stages[stage] = stage_path
            
        logger.info(f"Quarantine initialized at {self._root}")
    
    def move_to_quarantine(self, file_path: Path, stage: str) -> Path:
        """
        Move a file into the quarantine system.
        
        Args:
            file_path: Path to the file to quarantine
            stage: Stage to move to (incoming, processing, processed, rejected, conflicts)
            
        Returns:
            New path of the quarantined file
            
        Raises:
            ValueError: If stage is invalid
            FileNotFoundError: If source file doesn't exist
        """
        if stage not in self.VALID_STAGES:
            raise ValueError(f"Invalid stage: {stage}. Must be one of {self.VALID_STAGES}")
        
        source_path = Path(file_path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"File not found: {source_path}")
        
        # Generate unique filename in quarantine (preserve original name with timestamp)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_name = f"{timestamp}_{source_path.name}"
        dest_path = self._stages[stage] / unique_name
        
        try:
            # Move file to quarantine
            shutil.move(str(source_path), str(dest_path))
            
            # Set secure permissions
            dest_path.chmod(0o640)
            
            logger.info(f"Moved {source_path} to quarantine [{stage}]: {dest_path}")
            log_security_event("quarantine_moved", source_path, {
                "stage": stage,
                "destination": str(dest_path)
            })
            
            return dest_path
            
        except Exception as e:
            logger.error(f"Failed to move {source_path} to quarantine: {e}")
            raise
    
    def move_from_quarantine(self, quarantine_path: Path, destination: Path):
        """
        Move a file out of quarantine back to its original location.
        
        Args:
            quarantine_path: Path to file in quarantine
            destination: Destination path to move to
            
        Raises:
            FileNotFoundError: If quarantine file doesn't exist
        """
        source_path = Path(quarantine_path).resolve()
        dest_path = Path(destination).resolve()
        
        if not source_path.exists():
            raise FileNotFoundError(f"Quarantine file not found: {source_path}")
        
        # Ensure destination directory exists
        ensure_directory(dest_path.parent, mode=0o755)
        
        try:
            shutil.move(str(source_path), str(dest_path))
            logger.info(f"Moved from quarantine: {source_path} -> {dest_path}")
            
        except Exception as e:
            logger.error(f"Failed to move {source_path} from quarantine: {e}")
            raise
    
    def mark_processed(self, quarantine_path: Path):
        """
        Move a file from processing to processed stage.
        
        Args:
            quarantine_path: Path to file in processing quarantine
        """
        self._move_between_stages(quarantine_path, self.STAGE_PROCESSING, self.STAGE_PROCESSED)
    
    def mark_rejected(self, quarantine_path: Path, reason: str):
        """
        Move a file to rejected stage and log the reason.
        
        Args:
            quarantine_path: Path to file in quarantine (any stage)
            reason: Reason for rejection
        """
        # Determine current stage
        current_stage = self._get_stage(quarantine_path)
        
        # Move to rejected
        rejected_path = self._move_between_stages(quarantine_path, current_stage, self.STAGE_REJECTED)
        
        # Write reason file
        reason_file = rejected_path.with_suffix(".reject.txt")
        reason_file.write_text(f"Rejected at {datetime.now().isoformat()}\nReason: {reason}")
        reason_file.chmod(0o640)
        
        logger.warning(f"File rejected: {quarantine_path} - {reason}")
        log_security_event("file_rejected", quarantine_path, {"reason": reason})
    
    def _move_between_stages(self, file_path: Path, from_stage: str, to_stage: str) -> Path:
        """
        Move a file between quarantine stages.
        
        Args:
            file_path: Path to file in quarantine
            from_stage: Current stage
            to_stage: Target stage
            
        Returns:
            New path after move
        """
        source_path = Path(file_path).resolve()
        
        if not source_path.exists():
            logger.error(f"Cannot move non-existent file: {source_path}")
            raise FileNotFoundError(f"File not found: {source_path}")
        
        # Verify file is actually in the expected stage
        if from_stage and self._get_stage(source_path) != from_stage:
            logger.warning(f"File {source_path} is not in {from_stage} stage")
        
        # Generate destination path (preserve filename)
        dest_path = self._stages[to_stage] / source_path.name
        
        # Handle filename conflicts
        if dest_path.exists():
            dest_path = get_unique_filename(self._stages[to_stage], 
                                           prefix=source_path.stem,
                                           suffix=source_path.suffix)
        
        try:
            shutil.move(str(source_path), str(dest_path))
            logger.debug(f"Moved {source_path} from {from_stage} to {to_stage}: {dest_path}")
            return dest_path
            
        except Exception as e:
            logger.error(f"Failed to move {source_path} between stages: {e}")
            raise
    
    def _get_stage(self, file_path: Path) -> Optional[str]:
        """
        Determine which stage a file belongs to.
        
        Args:
            file_path: Path to file in quarantine
            
        Returns:
            Stage name or None if not in quarantine
        """
        resolved_path = Path(file_path).resolve()
        
        for stage, stage_path in self._stages.items():
            try:
                resolved_path.relative_to(stage_path)
                return stage
            except ValueError:
                continue
        
        return None
    
    def cleanup_old_files(self, days: int = 30):
        """
        Delete files older than specified days from quarantine.
        
        Only cleans up processed and rejected stages. Active stages
        (incoming, processing, conflicts) are not cleaned up automatically.
        
        Args:
            days: Age in days after which files should be deleted
        """
        cutoff_time = datetime.now() - timedelta(days=days)
        
        # Stages to clean up
        cleanup_stages = [self.STAGE_PROCESSED, self.STAGE_REJECTED]
        
        total_deleted = 0
        total_freed_bytes = 0
        
        for stage in cleanup_stages:
            stage_path = self._stages[stage]
            
            if not stage_path.exists():
                continue
            
            for file_path in stage_path.iterdir():
                if file_path.is_file():
                    # Get file modification time
                    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    
                    if mtime < cutoff_time:
                        file_size = file_path.stat().st_size
                        
                        try:
                            # Securely delete the file
                            secure_delete(file_path)
                            total_deleted += 1
                            total_freed_bytes += file_size
                            logger.debug(f"Deleted old file: {file_path} (age: {(datetime.now() - mtime).days} days)")
                            
                        except Exception as e:
                            logger.error(f"Failed to delete {file_path}: {e}")
        
        if total_deleted > 0:
            logger.info(f"Cleanup complete: deleted {total_deleted} files, freed {total_freed_bytes / (1024*1024):.2f} MB")
        else:
            logger.debug(f"No files older than {days} days found for cleanup")
    
    def get_quarantine_statistics(self) -> Dict[str, Dict[str, any]]:
        """
        Get statistics about quarantine usage.
        
        Returns:
            Dictionary with statistics per stage (file count, total size, oldest file)
        """
        stats = {}
        
        for stage, stage_path in self._stages.items():
            if not stage_path.exists():
                stats[stage] = {
                    "count": 0,
                    "total_size_bytes": 0,
                    "oldest_file": None,
                    "newest_file": None
                }
                continue
            
            files = list(stage_path.iterdir())
            files = [f for f in files if f.is_file()]
            
            if not files:
                stats[stage] = {
                    "count": 0,
                    "total_size_bytes": 0,
                    "oldest_file": None,
                    "newest_file": None
                }
                continue
            
            total_size = sum(f.stat().st_size for f in files)
            oldest = min(files, key=lambda f: f.stat().st_mtime)
            newest = max(files, key=lambda f: f.stat().st_mtime)
            
            stats[stage] = {
                "count": len(files),
                "total_size_bytes": total_size,
                "total_size_mb": total_size / (1024 * 1024),
                "oldest_file": {
                    "name": oldest.name,
                    "age_days": (datetime.now() - datetime.fromtimestamp(oldest.stat().st_mtime)).days
                },
                "newest_file": {
                    "name": newest.name,
                    "age_hours": (datetime.now() - datetime.fromtimestamp(newest.stat().st_mtime)).total_seconds() / 3600
                }
            }
        
        return stats
    
    def get_files_by_stage(self, stage: str) -> List[Path]:
        """
        Get list of files in a specific quarantine stage.
        
        Args:
            stage: Stage name (incoming, processing, processed, rejected, conflicts)
            
        Returns:
            List of file paths in that stage
        """
        if stage not in self.VALID_STAGES:
            raise ValueError(f"Invalid stage: {stage}")
        
        stage_path = self._stages[stage]
        
        if not stage_path.exists():
            return []
        
        return [f for f in stage_path.iterdir() if f.is_file()]
    
    def get_file_info(self, file_path: Path) -> Optional[Dict]:
        """
        Get detailed information about a quarantined file.
        
        Args:
            file_path: Path to file in quarantine
            
        Returns:
            Dictionary with file information or None if not found
        """
        resolved_path = Path(file_path).resolve()
        
        if not resolved_path.exists():
            return None
        
        stage = self._get_stage(resolved_path)
        if not stage:
            return None
        
        stat = resolved_path.stat()
        
        return {
            "path": str(resolved_path),
            "name": resolved_path.name,
            "stage": stage,
            "size_bytes": stat.st_size,
            "size_mb": stat.st_size / (1024 * 1024),
            "created_at": datetime.fromtimestamp(stat.st_ctime),
            "modified_at": datetime.fromtimestamp(stat.st_mtime),
            "age_days": (datetime.now() - datetime.fromtimestamp(stat.st_mtime)).days
        }
    
    def clear_stage(self, stage: str, confirm: bool = False):
        """
        Clear all files from a specific quarantine stage.
        
        Args:
            stage: Stage to clear
            confirm: Must be True to actually delete files (safety measure)
            
        Returns:
            Number of files deleted
        """
        if not confirm:
            logger.warning(f"Clear operation not confirmed for stage {stage}")
            return 0
        
        if stage not in self.VALID_STAGES:
            raise ValueError(f"Invalid stage: {stage}")
        
        stage_path = self._stages[stage]
        
        if not stage_path.exists():
            return 0
        
        deleted_count = 0
        for file_path in stage_path.iterdir():
            if file_path.is_file():
                try:
                    secure_delete(file_path)
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete {file_path}: {e}")
        
        logger.warning(f"Cleared {deleted_count} files from {stage} stage")
        return deleted_count
    
    def get_quarantine_path(self, stage: str) -> Path:
        """
        Get the directory path for a specific stage.
        
        Args:
            stage: Stage name
            
        Returns:
            Path to the stage directory
        """
        if stage not in self.VALID_STAGES:
            raise ValueError(f"Invalid stage: {stage}")
        
        return self._stages[stage]
