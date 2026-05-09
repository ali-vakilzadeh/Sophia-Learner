"""
Event handler module for Sophia Learner.

This module provides a custom FileSystemEventHandler that processes filesystem
events and forwards them to the debouncer for hold policy enforcement.
"""

import logging
from pathlib import Path
from typing import List

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileMovedEvent

from sophia_learner.watcher.debouncer import Debouncer

logger = logging.getLogger(__name__)


class SophiaEventHandler(FileSystemEventHandler):
    """
    Handle filesystem events and push to debouncer.

    This event handler monitors file creation, modification, and move events,
    filters them by extension and type (files only, no directories), and forwards
    them to the debouncer for the 24-hour hold policy.
    """

    def __init__(self, debouncer: Debouncer, extensions: List[str]):
        """
        Initialize the event handler.

        Args:
            debouncer: Debouncer instance for managing file hold periods.
            extensions: List of file extensions to watch (e.g., ['.pdf', '.docx']).
        """
        super().__init__()
        self._debouncer = debouncer
        self._extensions = [ext.lower() if ext.startswith('.') else f'.{ext.lower()}' 
                           for ext in extensions]
        logger.debug(f"SophiaEventHandler initialized with extensions: {self._extensions}")

    def on_created(self, event: FileCreatedEvent) -> None:
        """
        Handle file created events.

        Args:
            event: The file creation event.
        """
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if self._is_valid_extension(file_path):
            logger.debug(f"File created: {file_path}")
            self._queue_event(file_path)
        else:
            logger.debug(f"Ignored file with unsupported extension: {file_path}")

    def on_modified(self, event: FileModifiedEvent) -> None:
        """
        Handle file modified events.

        Args:
            event: The file modification event.
        """
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if self._is_valid_extension(file_path):
            logger.debug(f"File modified: {file_path}")
            self._queue_event(file_path)
        else:
            logger.debug(f"Ignored modified file with unsupported extension: {file_path}")

    def on_moved(self, event: FileMovedEvent) -> None:
        """
        Handle file moved events.

        Args:
            event: The file move event.
        """
        if event.is_directory:
            return

        dest_path = Path(event.dest_path)
        src_path = Path(event.src_path)
        
        if self._is_valid_extension(dest_path):
            logger.debug(f"File moved into watched folder: {src_path} -> {dest_path}")
            self._queue_event(dest_path)
        else:
            logger.debug(f"Ignored moved file with unsupported extension: {dest_path}")

    def _queue_event(self, file_path: Path) -> None:
        """
        Push event to debouncer if extension matches.

        Args:
            file_path: Path to the file that triggered the event.
        """
        if self._debouncer is None:
            logger.warning(f"No debouncer configured, cannot queue event for {file_path}")
            return

        # Let the debouncer handle the event with a timestamp
        from datetime import datetime
        self._debouncer.add_event(file_path, datetime.now())

    def _is_valid_extension(self, file_path: Path) -> bool:
        """
        Check if the file has a valid extension for processing.

        Args:
            file_path: Path to the file to check.

        Returns:
            True if the file extension is in the allowed list, False otherwise.
        """
        # If no extensions are specified, allow all files
        if not self._extensions:
            return True

        # Check file suffix (including the dot)
        suffix = file_path.suffix.lower()
        
        # Also check if the file has no extension but we're watching for extensions
        if not suffix and self._extensions:
            # No extension, check if we're watching for extensionless files
            # (unlikely, but handle gracefully)
            return False
        
        return suffix in self._extensions

    def on_any_event(self, event) -> None:
        """
        Log all events for debugging purposes.

        Args:
            event: The filesystem event.
        """
        # Only log non-file events that we don't explicitly handle
        if event.event_type not in ['created', 'modified', 'moved']:
            logger.debug(f"Unhandled event type {event.event_type}: {event.src_path}")
