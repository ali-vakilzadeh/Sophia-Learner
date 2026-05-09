"""
Processing scheduler module for Sophia Learner.

This module provides a ProcessingScheduler class that enforces time windows
and rate limiting for file processing.
"""

import logging
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from sophia_learner.config.settings import SchedulerConfig
from sophia_learner.scheduler.time_window import TimeWindow
from sophia_learner.scheduler.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class ProcessingScheduler:
    """
    Time-window and delay enforcement for file processing.

    This class combines time window restrictions (e.g., only process between
    17:00 and 07:00) with rate limiting (delay between files) to control
    when and how quickly files are processed.
    """

    def __init__(self, config: SchedulerConfig):
        """
        Initialize the ProcessingScheduler.

        Args:
            config: Scheduler configuration containing window, timezone, and delay settings.
        """
        self._config = config
        
        # Initialize time window for processing schedule
        self._time_window = TimeWindow(
            start_str=config.processing_window.get("start", "00:00"),
            end_str=config.processing_window.get("end", "23:59"),
            timezone_str=config.timezone
        )
        
        # Initialize rate limiter for delay between files
        self._rate_limiter = RateLimiter(config.delay_between_files_seconds)
        
        # Pause flag for manual control
        self._paused = False
        self._pause_lock = threading.Lock()
        
        logger.info(f"ProcessingScheduler initialized with window {config.processing_window}, "
                   f"delay {config.delay_between_files_seconds}s, timezone {config.timezone}")

    def can_process_now(self) -> bool:
        """
        Check if processing is currently allowed.

        Processing is allowed if:
        1. The scheduler is not paused
        2. Current time is within the configured time window

        Returns:
            True if processing can proceed now, False otherwise.
        """
        with self._pause_lock:
            if self._paused:
                logger.debug("Processing is paused")
                return False
        
        return self._time_window.is_within_window()

    def schedule_processing(self, file_path: Path, priority: int = 5) -> bool:
        """
        Schedule a file for processing.

        If processing is currently allowed, the file can be processed immediately
        (subject to rate limiting). Otherwise, it will be queued for the next window.

        Args:
            file_path: Path to the file to process.
            priority: Priority level (1-10, higher = more important).

        Returns:
            True if the file was queued for processing (or will be queued),
            False if it was rejected (e.g., system is paused and not accepting).
        """
        with self._pause_lock:
            if self._paused:
                logger.warning(f"Processing is paused, rejecting {file_path}")
                return False
        
        # In a real implementation, this would write to a queue or database
        # For now, we'll just log and return True
        if self.can_process_now():
            logger.debug(f"File {file_path} can be processed now (priority {priority})")
        else:
            next_window = self.get_next_window_start()
            logger.info(f"File {file_path} scheduled for next window at {next_window} (priority {priority})")
        
        # In production, this would add to a persistent queue
        return True

    def get_next_window_start(self) -> datetime:
        """
        Calculate when the next processing window begins.

        Returns:
            Datetime of the next window start.
        """
        return self._time_window.get_next_window_start()

    def wait_for_window(self) -> None:
        """
        Sleep until the next processing window starts.

        If already within a window, returns immediately.
        """
        if self.can_process_now():
            logger.debug("Already within processing window")
            return
        
        seconds_until = self._time_window.seconds_until_window()
        if seconds_until > 0:
            logger.info(f"Waiting {seconds_until:.0f} seconds for next processing window")
            time.sleep(seconds_until)
        else:
            # Check again - might be in window now
            logger.debug("Window may have started during calculation, checking again")
            if not self.can_process_now():
                # Fallback: wait a short time and retry
                time.sleep(5)

    def wait_if_rate_limited(self) -> None:
        """
        Wait if rate limiting requires a delay between files.

        This should be called before processing each file.
        """
        self._rate_limiter.wait_if_needed()

    def record_processing(self) -> None:
        """
        Record that a file was processed.

        This updates the rate limiter's last process time.
        """
        self._rate_limiter.record_processing()

    def pause_processing(self) -> None:
        """
        Pause processing (soft pause for user-defined maintenance).

        While paused, can_process_now() will return False.
        """
        with self._pause_lock:
            if not self._paused:
                self._paused = True
                logger.info("Processing paused")
            else:
                logger.debug("Processing already paused")

    def resume_processing(self) -> None:
        """
        Resume processing after a pause.
        """
        with self._pause_lock:
            if self._paused:
                self._paused = False
                logger.info("Processing resumed")
            else:
                logger.debug("Processing already running")

    def is_paused(self) -> bool:
        """
        Check if processing is currently paused.

        Returns:
            True if paused, False otherwise.
        """
        with self._pause_lock:
            return self._paused

    def get_remaining_cooldown(self) -> float:
        """
        Get the remaining cooldown time until next file can be processed.

        Returns:
            Seconds remaining (0 if ready to process).
        """
        return self._rate_limiter.get_remaining_cooldown()

    def set_delay_between_files(self, delay_seconds: int) -> None:
        """
        Dynamically adjust the delay between files.

        Args:
            delay_seconds: New delay in seconds.
        """
        self._rate_limiter.set_delay(delay_seconds)
        logger.info(f"Rate limit delay changed to {delay_seconds} seconds")

    def get_window_duration(self) -> int:
        """
        Get the duration of the processing window in seconds.

        Returns:
            Window duration in seconds.
        """
        return self._time_window.get_window_duration_seconds()

    def get_current_window_status(self) -> dict:
        """
        Get detailed status of the current processing window.

        Returns:
            Dictionary with window information.
        """
        now = datetime.now(self._time_window._tz)
        in_window = self.can_process_now()
        
        status = {
            "in_window": in_window,
            "timezone": self._config.timezone,
            "current_time": now.isoformat(),
            "window_start": self._config.processing_window.get("start"),
            "window_end": self._config.processing_window.get("end"),
            "paused": self.is_paused(),
            "remaining_cooldown": self.get_remaining_cooldown()
        }
        
        if not in_window:
            status["next_window_start"] = self.get_next_window_start().isoformat()
        
        return status
