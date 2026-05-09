"""
Debouncer module for Sophia Learner.

This module implements a 24-hour hold policy and duplicate suppression for files
detected by the directory watcher. Files are held for the configured hold period
to ensure they are stable (complete writes) before processing.
"""

import logging
import queue
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from sophia_learner.scheduler.scheduler import ProcessingScheduler

logger = logging.getLogger(__name__)


class Debouncer:
    """
    Implements 24-hour hold policy and duplicate suppression.

    This class tracks file events and schedules release of files after a
    configurable hold period. During the hold period, additional events for the
    same file reset the timer. After hold expires, the file is pushed to the
    processing queue if it still needs processing.
    """

    def __init__(
        self,
        hold_hours: int,
        processing_queue: queue.Queue,
        scheduler: ProcessingScheduler
    ):
        """
        Initialize the Debouncer.

        Args:
            hold_hours: Number of hours to hold files before processing.
            processing_queue: Queue for files ready for processing.
            scheduler: ProcessingScheduler for window and rate limiting.
        """
        self._hold_hours = hold_hours
        self._processing_queue = processing_queue
        self._scheduler = scheduler
        self._tracker: Dict[Path, Dict] = {}  # file_path -> {timer, release_time, event_count}
        self._lock = threading.Lock()
        logger.info(f"Debouncer initialized with {hold_hours} hour hold period")

    def add_event(self, file_path: Path, event_time: datetime) -> None:
        """
        Add a file event to debounce tracking.

        If the file is already being tracked, the existing timer is cancelled
        and a new one is scheduled (reset the hold period).

        Args:
            file_path: Path to the file that triggered the event.
            event_time: Timestamp of the event.
        """
        with self._lock:
            release_time = event_time + timedelta(hours=self._hold_hours)
            
            if file_path in self._tracker:
                # Cancel existing timer
                old_timer = self._tracker[file_path].get("timer")
                if old_timer:
                    old_timer.cancel()
                
                # Update event count
                self._tracker[file_path]["event_count"] += 1
                self._tracker[file_path]["release_time"] = release_time
                logger.debug(f"Reset hold timer for {file_path} (event #{self._tracker[file_path]['event_count']})")
            else:
                # New file
                self._tracker[file_path] = {
                    "timer": None,
                    "release_time": release_time,
                    "event_count": 1,
                    "first_seen": event_time
                }
                logger.debug(f"Added {file_path} to debouncer (hold until {release_time})")
            
            # Schedule release
            self._schedule_release(file_path, release_time)

    def _schedule_release(self, file_path: Path, release_time: datetime) -> None:
        """
        Schedule file release after hold period using threading.Timer.

        Args:
            file_path: Path to the file to release.
            release_time: Datetime when the file should be released.
        """
        # Calculate delay in seconds
        delay_seconds = (release_time - datetime.now()).total_seconds()
        
        if delay_seconds <= 0:
            # Release immediately
            logger.debug(f"Release time already passed for {file_path}, releasing now")
            timer = threading.Timer(0.1, self._release_file, args=[file_path])
        else:
            timer = threading.Timer(delay_seconds, self._release_file, args=[file_path])
        
        timer.daemon = True
        
        with self._lock:
            if file_path in self._tracker:
                self._tracker[file_path]["timer"] = timer
        
        timer.start()
        logger.debug(f"Scheduled release for {file_path} in {delay_seconds:.2f} seconds")

    def _release_file(self, file_path: Path) -> None:
        """
        Called by timer to release a file after hold period.

        Checks if the file still needs processing (not already processed by other
        means) and pushes it to the processing queue if within schedule window.

        Args:
            file_path: Path to the file to release.
        """
        with self._lock:
            if file_path not in self._tracker:
                logger.debug(f"File {file_path} no longer in tracker, skipping release")
                return
            
            # Remove from tracker
            tracker_info = self._tracker.pop(file_path)
            event_count = tracker_info["event_count"]
        
        logger.info(f"Releasing {file_path} after {self._hold_hours} hour hold ({event_count} events)")
        
        # Check if file still exists
        if not file_path.exists():
            logger.warning(f"File {file_path} no longer exists, skipping processing")
            return
        
        # Push to processing queue
        self._push_to_processing(file_path)

    def _push_to_processing(self, file_path: Path) -> None:
        """
        Push file to processing queue if within schedule window.

        Args:
            file_path: Path to the file to process.
        """
        # Check if we can process now based on schedule window
        if self._scheduler.can_process_now():
            logger.debug(f"Pushing {file_path} to processing queue")
            self._processing_queue.put(file_path)
        else:
            # Schedule for next window
            next_window = self._scheduler.get_next_window_start()
            logger.info(f"Outside processing window, scheduling {file_path} for {next_window}")
            # In a real implementation, we would either:
            # 1. Queue the file to be processed when window starts
            # 2. Or write to database with pending status and let scheduler pick it up
            # For now, we'll just put it in the queue and let scheduler handle delays
            self._processing_queue.put(file_path)

    def cancel_file(self, file_path: Path) -> None:
        """
        Cancel pending release for a file (if file is deleted/moved).

        Args:
            file_path: Path to the file to cancel.
        """
        with self._lock:
            if file_path in self._tracker:
                timer = self._tracker[file_path].get("timer")
                if timer:
                    timer.cancel()
                del self._tracker[file_path]
                logger.debug(f"Cancelled pending release for {file_path}")

    def get_pending_count(self) -> int:
        """
        Get the number of files currently in hold.

        Returns:
            Number of files currently being tracked by the debouncer.
        """
        with self._lock:
            return len(self._tracker)

    def get_file_info(self, file_path: Path) -> Optional[Dict]:
        """
        Get tracking information for a specific file.

        Args:
            file_path: Path to the file.

        Returns:
            Dictionary with tracking info if file is being tracked, None otherwise.
        """
        with self._lock:
            if file_path in self._tracker:
                info = self._tracker[file_path].copy()
                # Don't return the timer object
                info.pop("timer", None)
                return info
        return None

    def clear(self) -> None:
        """
        Clear all pending files and cancel all timers.
        """
        with self._lock:
            for file_path, info in self._tracker.items():
                timer = info.get("timer")
                if timer:
                    timer.cancel()
            self._tracker.clear()
            logger.info("Cleared all pending debouncer entries")
