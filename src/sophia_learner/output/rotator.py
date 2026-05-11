"""
File rotation management for training data output.

This module provides the Rotator class which handles automatic file rotation
based on size and date thresholds, with optional compression of archived files.
"""

import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
import re

from sophia_learner.utils.logger import get_logger
from sophia_learner.utils.file_utils import ensure_directory, atomic_write


logger = get_logger(__name__)


class Rotator:
    """
    Manage file size and date-based rotation for output files.
    
    This class handles automatic rotation of training data files when they
    exceed size limits or when a new day begins. It supports optional
    compression of rotated files and cleanup of old archives.
    
    Attributes:
        output_dir: Directory where output files are stored
        max_size_mb: Maximum file size in megabytes before rotation
        rotate_daily: Whether to rotate based on date changes
        compress: Whether to compress rotated files with gzip
        _last_date: Date of the last rotation check
    """
    
    # Pattern for matching training data files
    FILE_PATTERN = re.compile(r'training_data_(?P<timestamp>\d{8}_\d{6})\.jsonl(?:\.gz)?$')
    
    def __init__(self, output_dir: Path, max_size_mb: int, 
                 rotate_daily: bool, compress: bool):
        """
        Initialize Rotator with configuration.
        
        Args:
            output_dir: Directory where output files are stored
            max_size_mb: Maximum file size in MB before rotation (must be > 0)
            rotate_daily: Whether to rotate based on date changes
            compress: Whether to compress rotated files with gzip
            
        Raises:
            ValueError: If max_size_mb <= 0 or output_dir is invalid
        """
        if max_size_mb <= 0:
            raise ValueError(f"max_size_mb must be positive, got {max_size_mb}")
        
        self.output_dir = Path(output_dir)
        self.max_size_mb = max_size_mb
        self.rotate_daily = rotate_daily
        self.compress = compress
        self._last_date = datetime.now().date()
        
        # Ensure output directory exists
        ensure_directory(self.output_dir, mode=0o750)
        
        logger.info(f"Rotator initialized: max_size={max_size_mb}MB, "
                   f"rotate_daily={rotate_daily}, compress={compress}")
    
    def _generate_timestamp(self) -> str:
        """
        Generate timestamp string for filename.
        
        Returns:
            Timestamp in format YYYYMMDD_HHMMSS
        """
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def get_next_output_path(self) -> Path:
        """
        Generate the next output file path.
        
        Returns:
            Path object for a new output file with timestamp
        """
        timestamp = self._generate_timestamp()
        filename = f"training_data_{timestamp}.jsonl"
        return self.output_dir / filename
    
    def check_rotate(self, current_path: Optional[Path], 
                     current_size_mb: float) -> Path:
        """
        Check if rotation is needed and perform it if conditions are met.
        
        Args:
            current_path: Path to current output file (may be None or non-existent)
            current_size_mb: Current file size in megabytes
            
        Returns:
            Path to the active output file (may be same or new)
        """
        # Handle case where no current file exists
        if current_path is None or not current_path.exists():
            return self.get_next_output_path()
        
        needs_rotation = False
        rotation_reason = None
        
        # Check size-based rotation
        if current_size_mb >= self.max_size_mb:
            needs_rotation = True
            rotation_reason = f"size ({current_size_mb:.2f}MB >= {self.max_size_mb}MB)"
        
        # Check date-based rotation
        if self.rotate_daily and not needs_rotation:
            current_date = datetime.now().date()
            if current_date != self._last_date:
                needs_rotation = True
                rotation_reason = f"date change ({self._last_date} -> {current_date})"
                self._last_date = current_date
        
        # Perform rotation if needed
        if needs_rotation:
            logger.info(f"Rotating {current_path}: {rotation_reason}")
            new_path = self._rotate_by_size(current_path)
            
            # Compress the rotated file if configured
            if self.compress:
                compressed_path = self.compress_file(new_path)
                # Remove original after compression
                if compressed_path and compressed_path != new_path:
                    try:
                        new_path.unlink()
                        logger.debug(f"Removed original file after compression: {new_path}")
                    except Exception as e:
                        logger.warning(f"Failed to remove original file {new_path}: {e}")
            
            return self.get_next_output_path()
        
        return current_path
    
    def _rotate_by_size(self, current_path: Path) -> Path:
        """
        Rotate file based on size threshold.
        
        Creates a new filename with timestamp and renames the current file.
        
        Args:
            current_path: Path to current output file
            
        Returns:
            Path to the rotated (archived) file
        """
        # Generate new filename with timestamp
        timestamp = self._extract_timestamp_from_path(current_path)
        if timestamp is None:
            timestamp = self._generate_timestamp()
        
        # Create rotated filename
        rotated_filename = f"training_data_{timestamp}.jsonl"
        rotated_path = self.output_dir / rotated_filename
        
        # Ensure we don't overwrite existing files
        rotated_path = self._get_unique_filename(rotated_path)
        
        # Rename current file to rotated filename
        try:
            current_path.rename(rotated_path)
            logger.info(f"Rotated {current_path} -> {rotated_path}")
        except Exception as e:
            logger.error(f"Failed to rotate file {current_path}: {e}")
            raise
        
        return rotated_path
    
    def _rotate_by_date(self, current_path: Path) -> Path:
        """
        Rotate file based on date change.
        
        This method is called when the date has changed since the last write.
        It creates a new file for the new day.
        
        Args:
            current_path: Path to current output file
            
        Returns:
            Path to the new output file (not the rotated one)
        """
        # This method is primarily a convenience wrapper around _rotate_by_size
        # but can be extended for special date-based naming schemes
        if current_path.exists():
            return self._rotate_by_size(current_path)
        return self.get_next_output_path()
    
    def _extract_timestamp_from_path(self, file_path: Path) -> Optional[str]:
        """
        Extract timestamp from filename if it matches the pattern.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Timestamp string if found, None otherwise
        """
        match = self.FILE_PATTERN.match(file_path.name)
        if match:
            return match.group('timestamp')
        return None
    
    def _get_unique_filename(self, base_path: Path) -> Path:
        """
        Generate a unique filename if the base name already exists.
        
        Args:
            base_path: Desired file path
            
        Returns:
            Unique file path with counter suffix if needed
        """
        if not base_path.exists():
            return base_path
        
        # Add counter suffix
        counter = 1
        stem = base_path.stem
        suffix = base_path.suffix
        
        while True:
            new_path = base_path.parent / f"{stem}_{counter}{suffix}"
            if not new_path.exists():
                return new_path
            counter += 1
    
    def compress_file(self, file_path: Path) -> Path:
        """
        Compress a file using gzip.
        
        Creates a .gz archive of the file and returns the path to the archive.
        
        Args:
            file_path: Path to the file to compress
            
        Returns:
            Path to the compressed file (.gz)
            
        Raises:
            FileNotFoundError: If file_path doesn't exist
            IOError: If compression fails
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Cannot compress {file_path}: file not found")
        
        # Create compressed filename
        compressed_path = file_path.with_suffix(file_path.suffix + '.gz')
        
        # Compress the file
        try:
            with open(file_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb', compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            logger.info(f"Compressed {file_path} -> {compressed_path}")
            
            # Get original and compressed sizes for logging
            original_size = file_path.stat().st_size
            compressed_size = compressed_path.stat().st_size
            compression_ratio = (1 - compressed_size / original_size) * 100
            
            logger.debug(f"Compression ratio: {compression_ratio:.1f}% "
                        f"({original_size} -> {compressed_size} bytes)")
            
            return compressed_path
            
        except Exception as e:
            logger.error(f"Failed to compress {file_path}: {e}")
            raise IOError(f"Compression failed: {e}")
    
    def get_archive_list(self) -> List[Path]:
        """
        Get list of all rotated/archived files.
        
        Returns:
            List of Path objects for all training data archives
            (both compressed and uncompressed)
        """
        archives = []
        
        # Find all training data files
        for pattern in ["training_data_*.jsonl", "training_data_*.jsonl.gz"]:
            archives.extend(self.output_dir.glob(pattern))
        
        # Sort by modification time (oldest first)
        archives.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0)
        
        return archives
    
    def cleanup_old_archives(self, days_to_keep: int = 90) -> int:
        """
        Delete archive files older than specified number of days.
        
        Args:
            days_to_keep: Number of days to keep (files older than this are deleted)
            
        Returns:
            Number of files deleted
        """
        if days_to_keep <= 0:
            logger.warning(f"days_to_keep must be positive, got {days_to_keep}")
            return 0
        
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        deleted_count = 0
        
        archives = self.get_archive_list()
        
        for archive_path in archives:
            try:
                # Get file modification time
                mtime = datetime.fromtimestamp(archive_path.stat().st_mtime)
                
                if mtime < cutoff_date:
                    archive_path.unlink()
                    deleted_count += 1
                    logger.info(f"Deleted old archive: {archive_path} "
                              f"(age: {(datetime.now() - mtime).days} days)")
                    
            except Exception as e:
                logger.warning(f"Failed to delete {archive_path}: {e}")
        
        if deleted_count > 0:
            logger.info(f"Cleanup complete: deleted {deleted_count} old archives "
                       f"(older than {days_to_keep} days)")
        else:
            logger.debug(f"No archives older than {days_to_keep} days found")
        
        return deleted_count
    
    def get_archive_statistics(self) -> dict:
        """
        Get statistics about current archives.
        
        Returns:
            Dictionary with archive statistics
        """
        archives = self.get_archive_list()
        
        if not archives:
            return {
                "total_count": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0,
                "oldest_date": None,
                "newest_date": None,
                "compressed_count": 0,
                "uncompressed_count": 0
            }
        
        total_size = 0
        compressed_count = 0
        dates = []
        
        for archive in archives:
            total_size += archive.stat().st_size
            if archive.suffix == '.gz':
                compressed_count += 1
            dates.append(datetime.fromtimestamp(archive.stat().st_mtime))
        
        return {
            "total_count": len(archives),
            "total_size_bytes": total_size,
            "total_size_mb": total_size / (1024 * 1024),
            "oldest_date": min(dates),
            "newest_date": max(dates),
            "compressed_count": compressed_count,
            "uncompressed_count": len(archives) - compressed_count
        }


# Example usage and testing
if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        
        # Initialize rotator
        rotator = Rotator(
            output_dir=output_dir,
            max_size_mb=1,  # 1MB for testing
            rotate_daily=True,
            compress=True
        )
        
        # Create a test file
        test_file = output_dir / "training_data_20240101_120000.jsonl"
        with open(test_file, 'w') as f:
            f.write("test line\n" * 1000)  # Create some content
        
        # Test rotation by size
        size_mb = test_file.stat().st_size / (1024 * 1024)
        new_file = rotator.check_rotate(test_file, size_mb)
        print(f"Rotation result: {test_file} -> {new_file}")
        
        # Test archive listing
        archives = rotator.get_archive_list()
        print(f"Archives found: {len(archives)}")
        
        # Test statistics
        stats = rotator.get_archive_statistics()
        print(f"Archive statistics: {stats}")
        
        # Test cleanup (with short retention for testing)
        deleted = rotator.cleanup_old_archives(days_to_keep=0)  # Delete all
        print(f"Deleted {deleted} files")
