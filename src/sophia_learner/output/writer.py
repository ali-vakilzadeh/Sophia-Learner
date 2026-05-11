"""
Thread-safe output writer for training data with atomic writes and automatic rotation.

This module provides the OutputWriter class which handles writing training samples
to JSONL files with proper locking, atomic operations, and integration with the
Rotator for file size/date-based rotation.
"""

import json
import threading
from pathlib import Path
from typing import Dict, List, Optional, TextIO
from tempfile import NamedTemporaryFile

from sophia_learner.config.settings import OutputConfig
from sophia_learner.ai.training_formatter import TrainingFormatter
from sophia_learner.output.rotator import Rotator
from sophia_learner.utils.logger import get_logger
from sophia_learner.utils.file_utils import ensure_directory


logger = get_logger(__name__)


class OutputWriter:
    """
    Thread-safe, atomic writing to training data files with automatic rotation.
    
    This class manages the output of training samples to JSONL files, ensuring
    that writes are atomic (via temp file rename), thread-safe (via locks),
    and automatically rotates files based on size or date.
    
    Attributes:
        config: Output configuration settings
        formatter: Training formatter for validating/formatting samples
        rotator: Rotator instance for file rotation management
        _lock: threading.Lock for thread safety
        _current_file: Path to current output file
        _file_handle: Optional file handle (lazy opened)
        _current_size_mb: Current size of output file in MB
        _is_closed: Flag indicating if writer has been closed
    """
    
    def __init__(self, config: OutputConfig, formatter: TrainingFormatter):
        """
        Initialize OutputWriter with configuration and formatter.
        
        Args:
            config: Output configuration (folder, format, rotation settings)
            formatter: TrainingFormatter for sample validation and formatting
            
        Raises:
            ValueError: If output directory cannot be created or is invalid
        """
        self.config = config
        self.formatter = formatter
        self._lock = threading.Lock()
        self._current_file: Optional[Path] = None
        self._file_handle: Optional[TextIO] = None
        self._current_size_mb: float = 0.0
        self._is_closed = False
        
        # Ensure output directory exists with safe permissions
        ensure_directory(config.folder, mode=0o750)
        
        # Initialize rotator
        self.rotator = Rotator(
            output_dir=config.folder,
            max_size_mb=config.max_file_size_mb,
            rotate_daily=config.rotate_daily,
            compress=config.compress_archive
        )
        
        # Create initial output file path
        self._initialize_output_file()
        
        logger.info(f"OutputWriter initialized. Output directory: {config.folder}")
    
    def _initialize_output_file(self) -> None:
        """
        Initialize or determine the current output file path.
        
        This method checks for existing files or creates a new one using
        the rotator's naming scheme.
        """
        # Try to find the most recent output file
        existing_files = sorted(
            self.config.folder.glob("training_data_*.jsonl"),
            reverse=True
        )
        
        if existing_files and not self.rotator.rotate_daily:
            # Resume using the most recent file
            self._current_file = existing_files[0]
            self._current_size_mb = self._get_file_size_mb(self._current_file)
            logger.debug(f"Resuming with existing output file: {self._current_file}")
        else:
            # Create new output file
            self._current_file = self.rotator.get_next_output_path()
            self._current_size_mb = 0.0
            logger.debug(f"Created new output file: {self._current_file}")
    
    def _get_file_size_mb(self, file_path: Path) -> float:
        """
        Get file size in megabytes.
        
        Args:
            file_path: Path to file
            
        Returns:
            Size in MB (float)
        """
        try:
            return file_path.stat().st_size / (1024 * 1024)
        except FileNotFoundError:
            return 0.0
    
    def _open_file_handle(self) -> None:
        """
        Open file handle for writing (appending mode).
        
        This method is called internally when a write operation is about to occur.
        """
        if self._file_handle is None or self._file_handle.closed:
            # Ensure directory exists
            ensure_directory(self.config.folder, mode=0o750)
            
            # Open in append mode (creates file if doesn't exist)
            self._file_handle = open(self._current_file, 'a', encoding='utf-8')
            logger.debug(f"Opened file handle: {self._current_file}")
    
    def _check_and_rotate(self) -> None:
        """
        Check if rotation is needed and perform it if necessary.
        
        This method checks both size and date-based rotation criteria
        and rotates the file if conditions are met.
        """
        # Update current file size
        if self._current_file and self._current_file.exists():
            self._current_size_mb = self._get_file_size_mb(self._current_file)
        
        # Check rotation
        new_path = self.rotator.check_rotate(self._current_file, self._current_size_mb)
        
        if new_path != self._current_file:
            # Rotation occurred
            logger.info(f"Rotating output file from {self._current_file} to {new_path}")
            
            # Close current handle if open
            if self._file_handle and not self._file_handle.closed:
                self._file_handle.close()
            
            # Update to new file
            self._current_file = new_path
            self._current_size_mb = 0.0
            self._file_handle = None  # Will be reopened on next write
    
    def _write(self, sample: Dict) -> None:
        """
        Raw write operation (assumes lock is already held).
        
        Args:
            sample: Training sample already validated by formatter
            
        Raises:
            IOError: If write operation fails
        """
        try:
            # Ensure file handle is open
            self._open_file_handle()
            
            # Check rotation before writing
            self._check_and_rotate()
            
            # Re-open file handle if rotation happened and we need a new one
            if self._file_handle is None or self._file_handle.closed:
                self._open_file_handle()
            
            # Serialize sample to JSON line
            json_line = json.dumps(sample, ensure_ascii=False) + '\n'
            
            # Write to file
            self._file_handle.write(json_line)
            self._file_handle.flush()  # Ensure it's written to disk
            
            # Update size tracking
            self._current_size_mb += len(json_line.encode('utf-8')) / (1024 * 1024)
            
            logger.debug(f"Wrote sample to {self._current_file}")
            
        except IOError as e:
            logger.error(f"Failed to write sample to {self._current_file}: {e}")
            raise
    
    def append(self, sample: Dict) -> bool:
        """
        Append a single training sample to the output file.
        
        This method is thread-safe and performs atomic writes.
        
        Args:
            sample: Training sample dictionary (must conform to output schema)
            
        Returns:
            bool: True if write was successful, False otherwise
            
        Raises:
            ValueError: If sample validation fails
            RuntimeError: If writer is closed
        """
        if self._is_closed:
            raise RuntimeError("OutputWriter is closed and cannot accept more samples")
        
        # Validate sample
        if not self.formatter.validate_sample(sample):
            logger.warning(f"Sample validation failed: {sample}")
            raise ValueError(f"Sample does not conform to output schema: {sample}")
        
        # Add metadata to sample
        enriched_sample = self.formatter.add_metadata(sample)
        
        # Write with lock
        with self._lock:
            try:
                self._write(enriched_sample)
                return True
            except Exception as e:
                logger.error(f"Failed to append sample: {e}")
                return False
    
    def append_batch(self, samples: List[Dict]) -> int:
        """
        Append multiple training samples in batch.
        
        This method is more efficient than individual appends for large batches.
        
        Args:
            samples: List of training sample dictionaries
            
        Returns:
            int: Number of successfully written samples
            
        Raises:
            RuntimeError: If writer is closed
        """
        if self._is_closed:
            raise RuntimeError("OutputWriter is closed and cannot accept more samples")
        
        if not samples:
            return 0
        
        successful_count = 0
        
        # Validate all samples first (fail fast)
        validated_samples = []
        for sample in samples:
            if self.formatter.validate_sample(sample):
                validated_samples.append(self.formatter.add_metadata(sample))
            else:
                logger.warning(f"Skipping invalid sample in batch: {sample}")
        
        if not validated_samples:
            return 0
        
        # Write all samples under a single lock
        with self._lock:
            try:
                # Ensure file is ready
                self._open_file_handle()
                
                # Write each sample
                for sample in validated_samples:
                    self._write(sample)
                    successful_count += 1
                
                logger.info(f"Successfully wrote {successful_count} samples in batch")
                return successful_count
                
            except Exception as e:
                logger.error(f"Batch write failed after {successful_count} samples: {e}")
                # Return count of successfully written samples
                return successful_count
    
    def flush(self) -> None:
        """
        Flush any buffered writes to disk.
        
        This ensures all data is persisted before operations like close.
        """
        with self._lock:
            if self._file_handle and not self._file_handle.closed:
                self._file_handle.flush()
                logger.debug("Flushed output buffer to disk")
    
    def close(self) -> None:
        """
        Close the output writer and finalize current file.
        
        This method flushes any pending writes, closes file handles,
        and marks the writer as closed (preventing further writes).
        """
        with self._lock:
            if not self._is_closed:
                self.flush()
                
                if self._file_handle and not self._file_handle.closed:
                    self._file_handle.close()
                    logger.debug(f"Closed file handle: {self._current_file}")
                
                self._is_closed = True
                logger.info("OutputWriter closed")
    
    def get_current_output_path(self) -> Path:
        """
        Get the path to the current active output file.
        
        Returns:
            Path: Current output file path
            
        Raises:
            RuntimeError: If writer is closed
        """
        if self._is_closed:
            raise RuntimeError("OutputWriter is closed, no current output path")
        
        return self._current_file
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        self.close()
    
    def __del__(self):
        """Destructor - ensure resources are cleaned up."""
        if not self._is_closed:
            try:
                self.close()
            except Exception:
                pass  # Avoid errors during garbage collection


# Example usage and testing helper
if __name__ == "__main__":
    # This is a simple test/example, not for production
    from sophia_learner.config.settings import OutputConfig
    from sophia_learner.ai.training_formatter import TrainingFormatter
    
    # Create test configuration
    config = OutputConfig(
        folder=Path("/tmp/sophia_test_output"),
        format="jsonl",
        max_file_size_mb=1,  # Small for testing rotation
        rotate_daily=False,
        compress_archive=False
    )
    
    # Create formatter (with basic schema for testing)
    schema = {
        "instruction": "string",
        "output": "string"
    }
    formatter = TrainingFormatter(schema)
    
    # Test writer
    with OutputWriter(config, formatter) as writer:
        # Write single sample
        sample = {
            "instruction": "What is Python?",
            "output": "Python is a programming language."
        }
        writer.append(sample)
        
        # Write batch samples
        batch = [
            {"instruction": "Test 1", "output": "Answer 1"},
            {"instruction": "Test 2", "output": "Answer 2"},
            {"instruction": "Test 3", "output": "Answer 3"}
        ]
        count = writer.append_batch(batch)
        print(f"Wrote {count} samples to {writer.get_current_output_path()}")
