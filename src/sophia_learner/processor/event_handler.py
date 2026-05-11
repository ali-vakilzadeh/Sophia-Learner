"""
Event Handler - Process filesystem events and route to debouncer

This module provides a custom FileSystemEventHandler that monitors
file creation, modification, and move events, filtering them by
extension and directory type before sending to the debouncer.
"""

import logging
from pathlib import Path
from typing import List, Optional

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileMovedEvent

from ..utils.logger import get_logger

logger = get_logger(__name__)


class SophiaEventHandler(FileSystemEventHandler):
    """
    Handles filesystem events and pushes relevant files to the debouncer.
    
    This event handler monitors file creation, modification, and move events,
    filtering out directories and files with non-matching extensions.
    Events are queued to the debouncer for the 24-hour hold period.
    
    Attributes:
        _debouncer: Reference to the debouncer for queueing events
        _extensions: List of valid file extensions to process
        _ignore_directories: Whether to ignore directory events (always True)
    """
    
    def __init__(self, debouncer: Optional['Debouncer'] = None, extensions: Optional[List[str]] = None):
        """
        Initialize the event handler.
        
        Args:
            debouncer: Debouncer instance for queueing file events
            extensions: List of valid file extensions (e.g., ['.pdf', '.docx'])
        """
        super().__init__()
        self._debouncer = debouncer
        self._extensions = extensions or []
        self._ignore_directories = True
        
        # Normalize extensions to lowercase with leading dot
        self._extensions = [
            ext.lower() if ext.startswith('.') else f'.{ext.lower()}'
            for ext in self._extensions
        ]
        
        logger.debug(f"SophiaEventHandler initialized with extensions: {self._extensions}")
    
    def set_debouncer(self, debouncer: 'Debouncer'):
        """
        Set or update the debouncer reference.
        
        This allows lazy initialization of the debouncer after handler creation.
        
        Args:
            debouncer: Debouncer instance to use for queueing events
        """
        self._debouncer = debouncer
        logger.debug("Debouncer set for event handler")
    
    def update_extensions(self, extensions: List[str]):
        """
        Update the list of valid file extensions.
        
        Args:
            extensions: New list of valid file extensions
        """
        self._extensions = [
            ext.lower() if ext.startswith('.') else f'.{ext.lower()}'
            for ext in extensions
        ]
        logger.debug(f"Updated extensions to: {self._extensions}")
    
    def on_created(self, event):
        """
        Handle file creation events.
        
        Args:
            event: FileCreatedEvent from watchdog
        """
        # Skip directory events
        if event.is_directory and self._ignore_directories:
            logger.debug(f"Ignoring directory creation: {event.src_path}")
            return
        
        file_path = Path(event.src_path)
        
        # Check if extension is valid
        if not self._is_valid_extension(file_path):
            logger.debug(f"Ignoring file with invalid extension: {file_path}")
            return
        
        logger.info(f"File created: {file_path}")
        self._queue_event(file_path)
    
    def on_modified(self, event):
        """
        Handle file modification events.
        
        Args:
            event: FileModifiedEvent from watchdog
        """
        # Skip directory events
        if event.is_directory and self._ignore_directories:
            logger.debug(f"Ignoring directory modification: {event.src_path}")
            return
        
        file_path = Path(event.src_path)
        
        # Check if extension is valid
        if not self._is_valid_extension(file_path):
            logger.debug(f"Ignoring file with invalid extension: {file_path}")
            return
        
        # Only queue modification events for files that exist and are regular files
        if file_path.exists() and file_path.is_file():
            logger.debug(f"File modified: {file_path}")
            self._queue_event(file_path)
        else:
            logger.debug(f"Ignoring modification for non-existent file: {file_path}")
    
    def on_moved(self, event):
        """
        Handle file move events (including rename and move into watched folder).
        
        Args:
            event: FileMovedEvent from watchdog
        """
        # Skip directory events
        if event.is_directory and self._ignore_directories:
            logger.debug(f"Ignoring directory move: {event.src_path} -> {event.dest_path}")
            return
        
        src_path = Path(event.src_path)
        dest_path = Path(event.dest_path)
        
        # Check if destination extension is valid
        if not self._is_valid_extension(dest_path):
            logger.debug(f"Ignoring move to invalid extension: {dest_path}")
            return
        
        # Only queue if destination is a file (not directory)
        if dest_path.exists() and dest_path.is_file():
            logger.info(f"File moved: {src_path} -> {dest_path}")
            self._queue_event(dest_path)
        else:
            # If destination doesn't exist yet, it might be a move-in-progress
            # We'll still queue it as the file will be created
            logger.debug(f"File move detected (destination may not exist yet): {src_path} -> {dest_path}")
            self._queue_event(dest_path)
    
    def on_deleted(self, event):
        """
        Handle file deletion events.
        
        Note: Deletion events are not queued for processing, but are logged.
        
        Args:
            event: FileDeletedEvent from watchdog
        """
        if event.is_directory and self._ignore_directories:
            return
        
        file_path = Path(event.src_path)
        
        # Log deletion for audit purposes
        if self._is_valid_extension(file_path):
            logger.info(f"File deleted (removing from processing queue if pending): {file_path}")
            
            # Notify debouncer to cancel any pending timers for this file
            if self._debouncer:
                self._debouncer.cancel_file(file_path)
    
    def on_any_event(self, event):
        """
        Log any unhandled events for debugging.
        
        Args:
            event: Any FileSystemEvent
        """
        # Only log events that aren't handled by specific methods
        event_type = event.event_type
        if event_type not in ['created', 'modified', 'moved', 'deleted']:
            src_path = getattr(event, 'src_path', 'unknown')
            logger.debug(f"Unhandled event type '{event_type}' for {src_path}")
    
    def _queue_event(self, file_path: Path):
        """
        Queue a file event to the debouncer for processing.
        
        Args:
            file_path: Path to the file that triggered the event
        """
        if not self._debouncer:
            logger.warning(f"No debouncer set, cannot queue event for {file_path}")
            return
        
        try:
            # Ensure the path is absolute
            absolute_path = file_path.resolve()
            
            # Queue the event with current timestamp
            from datetime import datetime
            self._debouncer.add_event(absolute_path, datetime.now())
            
            logger.debug(f"Queued event for {absolute_path}")
            
        except Exception as e:
            logger.error(f"Failed to queue event for {file_path}: {e}")
    
    def _is_valid_extension(self, file_path: Path) -> bool:
        """
        Check if the file has a valid extension for processing.
        
        Args:
            file_path: Path to the file to check
            
        Returns:
            True if the file extension is in the allowed list (or list is empty),
            False otherwise
        """
        # If no extensions specified, accept all files
        if not self._extensions:
            logger.debug(f"No extension restrictions, accepting all files")
            return True
        
        # Get file extension (lowercase with dot)
        file_ext = file_path.suffix.lower()
        
        # Check if extension is in allowed list
        is_valid = file_ext in self._extensions
        
        if not is_valid:
            logger.debug(f"Extension {file_ext} not in allowed list: {self._extensions}")
        
        return is_valid
    
    def is_watching_extension(self, extension: str) -> bool:
        """
        Check if a specific extension is being watched.
        
        Args:
            extension: File extension (with or without leading dot)
            
        Returns:
            True if extension is in the watch list
        """
        # Normalize extension
        ext = extension.lower()
        if not ext.startswith('.'):
            ext = f'.{ext}'
        
        return ext in self._extensions
    
    def get_watched_extensions(self) -> List[str]:
        """
        Get the list of currently watched extensions.
        
        Returns:
            List of file extensions being monitored
        """
        return self._extensions.copy()
    
    def __repr__(self) -> str:
        """String representation of the event handler."""
        return f"SophiaEventHandler(extensions={self._extensions}, debouncer={'set' if self._debouncer else 'None'})"
