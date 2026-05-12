"""
Backfill processing for existing files not yet processed.

This module provides the BackfillProcessor class which discovers existing files
in watched folders and queues them for processing, ensuring no files are missed
when the system starts or when new folders are added.
"""

import os
from pathlib import Path
from typing import List, Optional, Set, Dict
from datetime import datetime
import fnmatch

from sophia_learner.db.file_tracker import FileTracker
from sophia_learner.processor.version_detector import VersionDetector
from sophia_learner.utils.logger import get_logger
from sophia_learner.utils.file_utils import get_file_size_safe


logger = get_logger(__name__)


class BackfillProcessor:
    """
    Discover and queue existing files for processing.
    
    This class handles scanning watched folders for existing files that
    haven't been processed yet (backfill), filtering them appropriately,
    and adding them to the processing queue with configurable priority.
    
    Attributes:
        file_tracker: FileTracker instance for database operations
        version_detector: VersionDetector instance for version detection
    """
    
    def __init__(self, file_tracker: FileTracker, version_detector: VersionDetector):
        """
        Initialize BackfillProcessor with required dependencies.
        
        Args:
            file_tracker: FileTracker instance for DB operations
            version_detector: VersionDetector for file version detection
            
        Raises:
            ValueError: If file_tracker or version_detector is None
        """
        if file_tracker is None:
            raise ValueError("file_tracker cannot be None")
        if version_detector is None:
            raise ValueError("version_detector cannot be None")
        
        self.file_tracker = file_tracker
        self.version_detector = version_detector
        
        logger.info("BackfillProcessor initialized")
    
    def scan_folders(self, watch_folders: List[Path], 
                     extensions: List[str]) -> List[Path]:
        """
        Scan watched folders for files matching extensions.
        
        Args:
            watch_folders: List of directory paths to scan
            extensions: List of file extensions to include (e.g., ['.pdf', '.docx'])
            
        Returns:
            List of file paths found (recursively)
            
        Raises:
            ValueError: If watch_folders is empty
            FileNotFoundError: If a watch folder doesn't exist
        """
        if not watch_folders:
            raise ValueError("watch_folders cannot be empty")
        
        found_files: Set[Path] = set()
        
        # Normalize extensions to ensure they start with dot and are lowercase
        normalized_extensions = [
            ext if ext.startswith('.') else f'.{ext}'
            for ext in extensions
        ]
        normalized_extensions = [ext.lower() for ext in normalized_extensions]
        
        for folder in watch_folders:
            folder_path = Path(folder)
            
            # Check if folder exists
            if not folder_path.exists():
                raise FileNotFoundError(f"Watch folder does not exist: {folder}")
            
            if not folder_path.is_dir():
                raise NotADirectoryError(f"Path is not a directory: {folder}")
            
            logger.info(f"Scanning folder: {folder}")
            
            # Walk through directory recursively
            try:
                for root, dirs, files in os.walk(folder_path):
                    # Skip hidden directories (starting with .)
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    
                    for file in files:
                        file_path = Path(root) / file
                        
                        # Skip hidden files
                        if file.startswith('.'):
                            continue
                        
                        # Check extension
                        if normalized_extensions:
                            file_ext = file_path.suffix.lower()
                            if file_ext not in normalized_extensions:
                                continue
                        
                        # Skip directories and non-regular files
                        if not file_path.is_file():
                            continue
                        
                        found_files.add(file_path)
                        
            except PermissionError as e:
                logger.warning(f"Permission denied scanning {folder}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error scanning {folder}: {e}")
                continue
        
        file_list = list(found_files)
        logger.info(f"Scanned {len(file_list)} files from {len(watch_folders)} folders")
        return file_list
    
    def filter_unprocessed(self, files: List[Path]) -> List[Path]:
        """
        Filter out files that have already been processed or are pending.
        
        Args:
            files: List of file paths to filter
            
        Returns:
            List of file paths that haven't been processed yet
            
        Note:
            A file is considered processed if it has a database record with
            status 'processed', 'processing', or 'quarantined'.
        """
        if not files:
            return []
        
        unprocessed_files = []
        processed_count = 0
        error_count = 0
        
        for file_path in files:
            try:
                # Check if file exists in database
                existing_record = self.file_tracker.get_file_by_path(file_path)
                
                # Determine if file needs processing
                if existing_record is None:
                    # No record - definitely needs processing
                    unprocessed_files.append(file_path)
                elif existing_record.status in ['processed', 'processing', 'quarantined']:
                    # Already processed or in progress
                    processed_count += 1
                    logger.debug(f"Skipping already processed file: {file_path}")
                elif existing_record.status in ['pending', 'failed']:
                    # Needs processing (pending or failed with retries)
                    unprocessed_files.append(file_path)
                else:
                    # Other status (conflicting, etc.) - include for processing
                    unprocessed_files.append(file_path)
                    
            except Exception as e:
                logger.error(f"Error checking file status for {file_path}: {e}")
                error_count += 1
                # Include file if we can't determine status (better to process than miss)
                unprocessed_files.append(file_path)
        
        logger.info(f"Filtered {len(files)} files: {len(unprocessed_files)} unprocessed, "
                   f"{processed_count} already processed, {error_count} errors")
        
        return unprocessed_files
    
    def enqueue_for_processing(self, file_paths: List[Path], 
                               priority: int = 3) -> int:
        """
        Add files to the processing queue.
        
        Args:
            file_paths: List of file paths to enqueue
            priority: Priority level (1-5, where 1 is highest, 5 is lowest)
                     Default is 3 (medium priority)
                     
        Returns:
            Number of files successfully enqueued
            
        Note:
            This method adds files to the database with status 'pending'
            and assigns the specified priority.
        """
        if not file_paths:
            return 0
        
        # Validate priority range
        if not 1 <= priority <= 5:
            logger.warning(f"Priority {priority} out of range (1-5), clamping to 3")
            priority = 3
        
        enqueued_count = 0
        skipped_count = 0
        error_count = 0
        
        for file_path in file_paths:
            try:
                # Check if file still exists
                if not file_path.exists():
                    logger.warning(f"File no longer exists, skipping: {file_path}")
                    skipped_count += 1
                    continue
                
                # Check if already enqueued recently
                existing = self.file_tracker.get_file_by_path(file_path)
                if existing and existing.status == 'pending':
                    logger.debug(f"File already pending, skipping: {file_path}")
                    skipped_count += 1
                    continue
                
                # Detect version from filename
                version = self.version_detector.detect_version(file_path)
                
                # Compute SHA256 and file size
                from sophia_learner.utils.hash_utils import compute_sha256
                sha256 = compute_sha256(file_path)
                file_size = get_file_size_safe(file_path)
                
                # Create file record
                from sophia_learner.db.models import FileRecord
                from datetime import datetime
                
                file_record = FileRecord(
                    id=None,  # Will be auto-assigned
                    path=file_path,
                    filename=file_path.name,
                    version=version,
                    sha256=sha256,
                    size_bytes=file_size,
                    mime_type='',  # Will be detected during processing
                    first_seen=datetime.now(),
                    last_modified=datetime.fromtimestamp(file_path.stat().st_mtime),
                    status='pending',
                    assigned_priority=priority
                )
                
                # Add to database
                self.file_tracker.add_file(file_record)
                enqueued_count += 1
                
                logger.debug(f"Enqueued file (priority {priority}): {file_path}")
                
            except Exception as e:
                logger.error(f"Failed to enqueue {file_path}: {e}")
                error_count += 1
        
        logger.info(f"Enqueued {enqueued_count} files (priority {priority}), "
                   f"skipped {skipped_count}, errors {error_count}")
        
        return enqueued_count
    
    def run_backfill(self, watch_folders: List[Path], 
                     extensions: List[str], 
                     max_files: int = 1000) -> int:
        """
        Run complete backfill process: scan, filter, and enqueue.
        
        Args:
            watch_folders: List of directory paths to scan
            extensions: List of file extensions to include
            max_files: Maximum number of files to process (0 = unlimited)
            
        Returns:
            Number of files successfully enqueued
            
        Raises:
            ValueError: If max_files is negative
        """
        if max_files < 0:
            raise ValueError(f"max_files must be >= 0, got {max_files}")
        
        logger.info(f"Starting backfill on {len(watch_folders)} folders...")
        start_time = datetime.now()
        
        # Step 1: Scan folders
        try:
            all_files = self.scan_folders(watch_folders, extensions)
        except Exception as e:
            logger.error(f"Failed to scan folders: {e}")
            raise
        
        if not all_files:
            logger.info("No files found to backfill")
            return 0
        
        # Apply max_files limit
        if max_files > 0 and len(all_files) > max_files:
            logger.warning(f"Found {len(all_files)} files, limiting to {max_files}")
            all_files = all_files[:max_files]
        
        # Step 2: Filter unprocessed files
        unprocessed_files = self.filter_unprocessed(all_files)
        
        if not unprocessed_files:
            logger.info("All files already processed or pending")
            return 0
        
        # Step 3: Enqueue for processing
        # Use default priority (3 = medium) for backfill
        enqueued = self.enqueue_for_processing(unprocessed_files, priority=3)
        
        # Log summary
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Backfill complete: {enqueued} files enqueued in {elapsed:.2f} seconds")
        
        return enqueued
    
    @staticmethod
    def should_backfill_on_startup(config) -> bool:
        """
        Determine if backfill should run on startup based on configuration.
        
        Args:
            config: Settings object containing watcher configuration
            
        Returns:
            True if backfill should run on startup, False otherwise
        """
        try:
            # Check if backfill_on_startup is enabled in config
            if hasattr(config, 'watcher') and hasattr(config.watcher, 'backfill_on_startup'):
                return config.watcher.backfill_on_startup
            
            # Default to True for safety (better to check than miss files)
            logger.debug("backfill_on_startup not in config, defaulting to True")
            return True
            
        except Exception as e:
            logger.warning(f"Error checking backfill_on_startup config: {e}, defaulting to True")
            return True
    
    def get_backfill_statistics(self, watch_folders: List[Path],
                               extensions: List[str]) -> Dict:
        """
        Get statistics about potential backfill without actually running it.
        
        Args:
            watch_folders: List of directory paths to scan
            extensions: List of file extensions to include
            
        Returns:
            Dictionary with backfill statistics
        """
        stats = {
            'total_files_found': 0,
            'processed_files': 0,
            'pending_files': 0,
            'failed_files': 0,
            'new_files_ready': 0,
            'total_size_bytes': 0,
            'by_extension': {},
            'by_folder': {}
        }
        
        try:
            # Scan folders
            all_files = self.scan_folders(watch_folders, extensions)
            stats['total_files_found'] = len(all_files)
            
            # Analyze each file
            for file_path in all_files:
                # Track by extension
                ext = file_path.suffix.lower()
                stats['by_extension'][ext] = stats['by_extension'].get(ext, 0) + 1
                
                # Track by folder
                parent = str(file_path.parent)
                stats['by_folder'][parent] = stats['by_folder'].get(parent, 0) + 1
                
                # Check file status
                try:
                    existing = self.file_tracker.get_file_by_path(file_path)
                    
                    if existing is None:
                        stats['new_files_ready'] += 1
                        stats['total_size_bytes'] += get_file_size_safe(file_path)
                    elif existing.status == 'processed':
                        stats['processed_files'] += 1
                    elif existing.status == 'pending':
                        stats['pending_files'] += 1
                    elif existing.status == 'failed':
                        stats['failed_files'] += 1
                    else:
                        # Other status counts as new
                        stats['new_files_ready'] += 1
                        stats['total_size_bytes'] += get_file_size_safe(file_path)
                        
                except Exception as e:
                    logger.warning(f"Error checking status for {file_path}: {e}")
                    stats['new_files_ready'] += 1
            
        except Exception as e:
            logger.error(f"Error getting backfill statistics: {e}")
            stats['error'] = str(e)
        
        return stats


# Example usage and testing
if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    from sophia_learner.db.database import Database
    from sophia_learner.db.file_tracker import FileTracker
    from sophia_learner.processor.version_detector import VersionDetector
    
    # Create test database
    with tempfile.NamedTemporaryFile(suffix='.db') as tmp:
        db_path = Path(tmp.name)
        db = Database(db_path)
        
        # Create tables
        from sophia_learner.db.models import create_tables
        create_tables(db)
        
        # Initialize components
        file_tracker = FileTracker(db)
        version_detector = VersionDetector()
        backfill = BackfillProcessor(file_tracker, version_detector)
        
        # Create test files
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)
            
            # Create some test files
            test_files = []
            extensions = ['.txt', '.pdf', '.docx']
            for i in range(10):
                ext = extensions[i % len(extensions)]
                file_path = test_dir / f"test_file_{i}{ext}"
                file_path.write_text(f"Test content {i}")
                test_files.append(file_path)
            
            # Create a subdirectory with more files
            subdir = test_dir / "subdir"
            subdir.mkdir()
            for i in range(5):
                file_path = subdir / f"nested_file_{i}.pdf"
                file_path.write_text(f"Nested content {i}")
                test_files.append(file_path)
            
            # Test scan_folders
            print("=== Testing scan_folders ===")
            found = backfill.scan_folders([test_dir], extensions)
            print(f"Found {len(found)} files (expected 15)")
            
            # Test filter_unprocessed
            print("\n=== Testing filter_unprocessed ===")
            # First, enqueue a few files manually
            backfill.enqueue_for_processing(found[:3], priority=3)
            
            unprocessed = backfill.filter_unprocessed(found)
            print(f"Unprocessed files: {len(unprocessed)} (expected {len(found) - 3})")
            
            # Test run_backfill
            print("\n=== Testing run_backfill ===")
            enqueued = backfill.run_backfill([test_dir], extensions, max_files=10)
            print(f"Enqueued {enqueued} files in backfill")
            
            # Test statistics
            print("\n=== Testing backfill statistics ===")
            stats = backfill.get_backfill_statistics([test_dir], extensions)
            print(f"Statistics: {stats}")
            
            # Test should_backfill_on_startup
            print("\n=== Testing should_backfill_on_startup ===")
            # Create a mock config
            class MockConfig:
                class Watcher:
                    backfill_on_startup = True
                watcher = Watcher()
            
            config = MockConfig()
            should = BackfillProcessor.should_backfill_on_startup(config)
            print(f"Should backfill on startup: {should}")
    
    # Example with custom configuration
    print("\n=== Example: Production Usage ===")
    print("""
    # In production code, you would use:
    
    from sophia_learner.config.settings import load_config
    from sophia_learner.db.database import Database
    from sophia_learner.db.file_tracker import FileTracker
    from sophia_learner.processor.version_detector import VersionDetector
    from sophia_learner.scheduler.backfill import BackfillProcessor
    
    # Load configuration
    config = load_config()
    
    # Initialize components
    db = Database(config.database.path)
    file_tracker = FileTracker(db)
    version_detector = VersionDetector()
    backfill = BackfillProcessor(file_tracker, version_detector)
    
    # Run backfill on startup if configured
    if BackfillProcessor.should_backfill_on_startup(config):
        enqueued = backfill.run_backfill(
            watch_folders=config.watcher.watch_folders,
            extensions=config.watcher.file_extensions,
            max_files=1000
        )
        print(f"Backfill enqueued {enqueued} files")
    
    # Or just get statistics without enqueuing
    stats = backfill.get_backfill_statistics(
        config.watcher.watch_folders,
        config.watcher.file_extensions
    )
    print(f"Found {stats['total_files_found']} total files, "
          f"{stats['new_files_ready']} ready for backfill")
    """)
