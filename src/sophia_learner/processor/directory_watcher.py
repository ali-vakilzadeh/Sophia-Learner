"""
Directory Watcher - Manages filesystem monitoring across multiple directories

This module provides a wrapper around the watchdog library to monitor multiple
directories for file events (creation, modification, moves) and route them
to the processing pipeline via a debouncer queue.
"""

import logging
from pathlib import Path
from typing import Optional, List, Dict
import queue

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from ..config.settings import WatcherConfig
from .event_handler import SophiaEventHandler
from ..utils.logger import get_logger

logger = get_logger(__name__)

# Global observer instance for singleton-like access
_OBSERVER: Optional[Observer] = None


class DirectoryWatcher:
    """
    Manages watchdog observers for multiple directories.
    
    This class wraps the watchdog library to provide a clean interface for
    starting, stopping, and managing file system watches across multiple
    directories. It uses the SophiaEventHandler to process filesystem events
    and push them to the debouncer queue.
    
    Attributes:
        _observer: The watchdog observer instance
        _watches: Dictionary mapping paths to watch objects
        _event_queue: Queue for sending events to debouncer
        _config: Watcher configuration
        _handlers: Dictionary mapping paths to event handlers
    """
    
    def __init__(self, event_queue: queue.Queue, config: WatcherConfig):
        """
        Initialize the directory watcher.
        
        Args:
            event_queue: Queue for sending file events to the debouncer
            config: Watcher configuration (watch_folders, extensions, etc.)
        """
        global _OBSERVER
        
        self._event_queue = event_queue
        self._config = config
        self._watches: Dict[Path, Optional[watchdog.observers.api.ObservedWatch]] = {}
        self._handlers: Dict[Path, SophiaEventHandler] = {}
        
        # Create or reuse global observer
        if _OBSERVER is None:
            _OBSERVER = Observer()
        self._observer = _OBSERVER
        
        self._is_running = False
        
        logger.info(f"DirectoryWatcher initialized with config: {config}")
        
        # Initialize watches for configured folders
        for watch_path in config.watch_folders:
            self.add_watch(watch_path, recursive=True)
    
    def add_watch(self, path: Path, recursive: bool = True) -> bool:
        """
        Start watching a folder for filesystem events.
        
        Args:
            path: Directory path to watch
            recursive: Whether to watch subdirectories recursively
            
        Returns:
            True if watch was successfully added, False otherwise
        """
        try:
            # Resolve and validate path
            resolved_path = path.resolve()
            if not resolved_path.exists():
                logger.error(f"Cannot watch non-existent path: {resolved_path}")
                return False
            
            if not resolved_path.is_dir():
                logger.error(f"Cannot watch non-directory path: {resolved_path}")
                return False
            
            # Check if already watching
            if resolved_path in self._watches:
                logger.debug(f"Already watching {resolved_path}")
                return True
            
            # Create event handler for this directory
            handler = SophiaEventHandler(
                debouncer=None,  # Will be set by watcher
                extensions=self._config.file_extensions
            )
            
            # Schedule the watch
            watch = self._observer.schedule(
                handler, 
                str(resolved_path), 
                recursive=recursive
            )
            
            # Store references
            self._watches[resolved_path] = watch
            self._handlers[resolved_path] = handler
            
            logger.info(f"Added watch on {resolved_path} (recursive={recursive})")
            return True
            
        except PermissionError as e:
            logger.error(f"Permission denied watching {path}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to add watch on {path}: {e}")
            return False
    
    def remove_watch(self, path: Path) -> bool:
        """
        Stop watching a folder.
        
        Args:
            path: Directory path to stop watching
            
        Returns:
            True if watch was removed, False if not found
        """
        try:
            resolved_path = path.resolve()
            
            if resolved_path not in self._watches:
                logger.warning(f"Watch not found for {resolved_path}")
                return False
            
            # Unscheduled the watch
            self._observer.unschedule(self._watches[resolved_path])
            
            # Clean up references
            del self._watches[resolved_path]
            if resolved_path in self._handlers:
                del self._handlers[resolved_path]
            
            logger.info(f"Removed watch on {resolved_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove watch on {path}: {e}")
            return False
    
    def start(self):
        """
        Start the observer thread to begin monitoring for events.
        
        This method starts the watchdog observer in a background thread.
        Events will be processed as they occur.
        """
        if self._is_running:
            logger.warning("DirectoryWatcher already running")
            return
        
        if not self._watches:
            logger.warning("No watches configured. Use add_watch() first.")
        
        # Connect handlers to debouncer (deferred setup)
        from .debouncer import Debouncer
        # Note: Debouncer will be set by the main orchestrator
        # For now, handlers are created without debouncer
        
        # Start the observer
        self._observer.start()
        self._is_running = True
        
        logger.info(f"DirectoryWatcher started with {len(self._watches)} active watches")
        
        # Log all watched directories
        for watch_path in self._watches.keys():
            logger.info(f"Watching: {watch_path}")
    
    def stop(self):
        """
        Stop the observer thread gracefully.
        
        This stops the background thread and waits for it to finish
        processing any pending events.
        """
        if not self._is_running:
            logger.debug("DirectoryWatcher already stopped")
            return
        
        logger.info("Stopping DirectoryWatcher...")
        
        # Stop the observer
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join(timeout=10)
            
            if self._observer.is_alive():
                logger.warning("Observer did not stop gracefully within timeout")
        
        self._is_running = False
        logger.info("DirectoryWatcher stopped")
    
    def on_any_event(self, event: FileSystemEvent):
        """
        Callback for logging all filesystem events (debugging).
        
        This method is called for every event received by the observer.
        It can be used for debugging and monitoring purposes.
        
        Args:
            event: Watchdog filesystem event
        """
        # Log interesting events at debug level
        event_type = event.event_type
        src_path = getattr(event, 'src_path', 'unknown')
        
        # Skip directory events to reduce noise
        if hasattr(event, 'is_directory') and event.is_directory:
            logger.debug(f"Directory event: {event_type} - {src_path}")
            return
        
        # Log file events
        if event_type in ['created', 'modified', 'moved', 'deleted']:
            logger.debug(f"File event: {event_type} - {src_path}")
            
            # For moved events, also log destination
            if event_type == 'moved' and hasattr(event, 'dest_path'):
                logger.debug(f"  Moved to: {event.dest_path}")
    
    def get_active_watches(self) -> List[Path]:
        """
        Get list of currently watched directories.
        
        Returns:
            List of Path objects for actively watched directories
        """
        return list(self._watches.keys())
    
    def is_watching(self, path: Path) -> bool:
        """
        Check if a directory is currently being watched.
        
        Args:
            path: Directory path to check
            
        Returns:
            True if the directory is being watched
        """
        resolved_path = path.resolve()
        return resolved_path in self._watches
    
    def get_watch_count(self) -> int:
        """
        Get the number of active watches.
        
        Returns:
            Count of watched directories
        """
        return len(self._watches)
    
    def is_running(self) -> bool:
        """
        Check if the watcher is currently running.
        
        Returns:
            True if observer thread is running
        """
        return self._is_running and self._observer.is_alive() if self._observer else False
    
    def set_debouncer_for_handler(self, path: Path, debouncer):
        """
        Set the debouncer reference for a specific handler.
        
        This is used to connect the event handler to the debouncer
        after the debouncer has been created.
        
        Args:
            path: Directory path whose handler should receive the debouncer
            debouncer: Debouncer instance to set on the handler
        """
        resolved_path = path.resolve()
        if resolved_path in self._handlers:
            self._handlers[resolved_path].set_debouncer(debouncer)
            logger.debug(f"Set debouncer for handler watching {resolved_path}")
        else:
            logger.warning(f"No handler found for {resolved_path}")
    
    def set_debouncer_for_all_handlers(self, debouncer):
        """
        Set the debouncer reference for all event handlers.
        
        Args:
            debouncer: Debouncer instance to set on all handlers
        """
        for path, handler in self._handlers.items():
            handler.set_debouncer(debouncer)
            logger.debug(f"Set debouncer for handler watching {path}")
    
    def reload_config(self, new_config: WatcherConfig):
        """
        Reload configuration and update watches if needed.
        
        This method compares the new configuration with the current one
        and adds/removes watches accordingly.
        
        Args:
            new_config: New watcher configuration
        """
        old_watches = set(self._watches.keys())
        new_watches = set(p.resolve() for p in new_config.watch_folders)
        
        # Add new watches
        to_add = new_watches - old_watches
        for watch_path in to_add:
            self.add_watch(watch_path)
        
        # Remove old watches
        to_remove = old_watches - new_watches
        for watch_path in to_remove:
            self.remove_watch(watch_path)
        
        # Update extensions in handlers
        if self._config.file_extensions != new_config.file_extensions:
            for handler in self._handlers.values():
                handler.update_extensions(new_config.file_extensions)
        
        # Update config reference
        self._config = new_config
        
        logger.info(f"Reloaded config: added {len(to_add)} watches, removed {len(to_remove)} watches")


# Convenience function to get the global observer instance
def get_global_observer() -> Optional[Observer]:
    """
    Get the global observer instance.
    
    Returns:
        The global Observer instance or None if not created
    """
    return _OBSERVER


def reset_global_observer():
    """
    Reset the global observer instance (for testing).
    
    This should only be used in test environments.
    """
    global _OBSERVER
    if _OBSERVER and _OBSERVER.is_alive():
        _OBSERVER.stop()
        _OBSERVER.join()
    _OBSERVER = None
