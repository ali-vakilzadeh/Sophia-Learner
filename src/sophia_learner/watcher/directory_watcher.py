"""
Directory watcher module for Sophia Learner.

This module provides a DirectoryWatcher class that manages watchdog observers
for monitoring multiple directories for file system events.
"""

import logging
import queue
from pathlib import Path
from typing import Optional, Dict

from watchdog.observers import Observer
from watchdog.events import FileSystemEvent, FileSystemEventHandler

from sophia_learner.config.settings import WatcherConfig
from sophia_learner.watcher.event_handler import SophiaEventHandler

logger = logging.getLogger(__name__)

# Global singleton holder for the observer
_OBSERVER: Optional[Observer] = None


class DirectoryWatcher:
    """
    Manages watchdog observers for multiple directories.

    This class handles the setup, monitoring, and teardown of file system
    watchers across multiple directories, dispatching events to the event queue.
    """

    def __init__(self, event_queue: queue.Queue, config: WatcherConfig):
        """
        Initialize the DirectoryWatcher.

        Args:
            event_queue: Queue for placing file events for processing.
            config: Watcher configuration containing watch folders and extensions.
        """
        self._event_queue = event_queue
        self._config = config
        self._observer: Optional[Observer] = None
        self._handlers: Dict[Path, SophiaEventHandler] = {}
        self._watches: Dict[Path, FileSystemEventHandler] = {}

    def add_watch(self, path: Path, recursive: bool = True) -> bool:
        """
        Start watching a folder.

        Args:
            path: Directory path to watch.
            recursive: Whether to watch subdirectories recursively.

        Returns:
            True if the watch was successfully added, False otherwise.
        """
        if not self._observer:
            logger.error("Cannot add watch: Observer not started")
            return False

        path = Path(path).resolve()

        if not path.exists():
            logger.error(f"Cannot watch non-existent path: {path}")
            return False

        if not path.is_dir():
            logger.error(f"Cannot watch non-directory path: {path}")
            return False

        # Create event handler for this path
        from sophia_learner.watcher.debouncer import Debouncer
        from sophia_learner.watcher.scheduler import ProcessingScheduler
        
        # Debouncer and scheduler are created at higher level and passed via config
        # For now, we'll create a simple event handler without debouncer
        # In production, these would be injected
        handler = SophiaEventHandler(None, self._config.file_extensions)
        
        try:
            self._observer.schedule(handler, str(path), recursive=recursive)
            self._watches[path] = handler
            self._handlers[path] = handler
            logger.info(f"Added watch on {path} (recursive={recursive})")
            return True
        except Exception as e:
            logger.error(f"Failed to add watch on {path}: {e}")
            return False

    def remove_watch(self, path: Path) -> None:
        """
        Stop watching a folder.

        Args:
            path: Directory path to stop watching.
        """
        if not self._observer:
            return

        path = Path(path).resolve()

        if path in self._watches:
            try:
                self._observer.unschedule(self._watches[path])
                del self._watches[path]
                del self._handlers[path]
                logger.info(f"Removed watch on {path}")
            except Exception as e:
                logger.error(f"Failed to remove watch on {path}: {e}")

    def start(self) -> None:
        """
        Start the observer thread.

        Creates and starts a new Observer if one doesn't exist, then adds all
        configured watch folders.
        """
        global _OBSERVER

        if self._observer is not None and self._observer.is_alive():
            logger.warning("Observer is already running")
            return

        self._observer = Observer()
        _OBSERVER = self._observer
        self._observer.start()
        logger.info("Directory watcher started")

        # Add all configured watch folders
        for watch_folder in self._config.watch_folders:
            self.add_watch(watch_folder, recursive=True)

    def stop(self) -> None:
        """
        Stop the observer thread gracefully.

        Stops the observer and waits for it to finish processing events.
        """
        global _OBSERVER

        if self._observer is None:
            logger.warning("Observer is not running")
            return

        logger.info("Stopping directory watcher...")
        
        # Remove all watches first
        for path in list(self._watches.keys()):
            self.remove_watch(path)
        
        self._observer.stop()
        self._observer.join(timeout=10)
        
        if self._observer.is_alive():
            logger.warning("Observer did not stop gracefully")
        
        self._observer = None
        _OBSERVER = None
        logger.info("Directory watcher stopped")

    def on_any_event(self, event: FileSystemEvent) -> None:
        """
        Callback for logging all filesystem events.

        This method is useful for debugging and monitoring.
        Note: This is not automatically called; it's provided as a utility
        for external logging if needed.

        Args:
            event: The filesystem event to log.
        """
        logger.debug(f"Filesystem event: {event.event_type} on {event.src_path}")

    def get_watched_paths(self) -> list:
        """
        Get the list of currently watched paths.

        Returns:
            List of watched directory paths.
        """
        return list(self._watches.keys())

    def is_watching(self, path: Path) -> bool:
        """
        Check if a path is currently being watched.

        Args:
            path: Directory path to check.

        Returns:
            True if the path is being watched, False otherwise.
        """
        return Path(path).resolve() in self._watches

    def pause_watching(self, path: Path) -> bool:
        """
        Temporarily pause watching a directory.

        Args:
            path: Directory path to pause.

        Returns:
            True if successfully paused, False otherwise.
        """
        if not self.is_watching(path):
            logger.warning(f"Path {path} is not being watched")
            return False

        try:
            self.remove_watch(path)
            logger.info(f"Paused watching {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to pause watching {path}: {e}")
            return False

    def resume_watching(self, path: Path, recursive: bool = True) -> bool:
        """
        Resume watching a previously paused directory.

        Args:
            path: Directory path to resume watching.
            recursive: Whether to watch subdirectories recursively.

        Returns:
            True if successfully resumed, False otherwise.
        """
        if self.is_watching(path):
            logger.warning(f"Path {path} is already being watched")
            return True

        return self.add_watch(path, recursive)  # pyright: ignore[reportArgumentType]  # Path is a Path, expected Path
