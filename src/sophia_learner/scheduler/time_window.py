"""
Time window management for processing schedules.

This module provides the TimeWindow class which handles daily time window logic
with support for crossing midnight boundaries and timezone awareness.
"""

from datetime import datetime, time, timedelta, date
from typing import Optional, Tuple
import re

from sophia_learner.utils.logger import get_logger
from sophia_learner.utils.time_utils import get_timezone_aware_now


# Try to import pytz for timezone support, fall back to standard library
try:
    import pytz
    HAS_PYTZ = True
except ImportError:
    from datetime import timezone as tz
    HAS_PYTZ = False
    # Create a simple UTC timezone for fallback
    class SimpleTimeZone:
        @staticmethod
        def localize(dt):
            return dt.replace(tzinfo=tz.utc)
    
    pytz = SimpleTimeZone()


logger = get_logger(__name__)


class TimeWindow:
    """
    Daily time window logic with support for crossing midnight.
    
    This class handles time windows that may span across midnight
    (e.g., 17:00 to 07:00 next day) and provides methods to check
    if current time is within the window and calculate when the
    next window starts.
    
    Attributes:
        start_time: Time object representing window start (UTC)
        end_time: Time object representing window end (UTC)
        timezone_str: IANA timezone string (e.g., 'America/New_York')
        timezone: pytz timezone object
        crosses_midnight: Boolean indicating if window crosses midnight
    """
    
    # Regex pattern for validating time strings (HH:MM format)
    TIME_PATTERN = re.compile(r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$')
    
    def __init__(self, start_str: str, end_str: str, timezone_str: str = "UTC"):
        """
        Initialize TimeWindow with start and end times.
        
        Args:
            start_str: Start time string in format "HH:MM" (24-hour)
            end_str: End time string in format "HH:MM" (24-hour)
            timezone_str: IANA timezone name (e.g., 'UTC', 'America/New_York')
            
        Raises:
            ValueError: If time strings are invalid or timezone not found
        """
        # Validate and parse time strings
        self.start_time = self._parse_time(start_str)
        self.end_time = self._parse_time(end_str)
        
        # Store timezone
        self.timezone_str = timezone_str
        try:
            if HAS_PYTZ:
                self.timezone = pytz.timezone(timezone_str)
            else:
                # Fallback to UTC only if pytz not available
                if timezone_str.upper() != "UTC":
                    logger.warning(f"pytz not available, using UTC instead of {timezone_str}")
                self.timezone = pytz
        except Exception as e:
            raise ValueError(f"Invalid timezone '{timezone_str}': {e}")
        
        # Determine if window crosses midnight
        self.crosses_midnight = self.start_time > self.end_time
        
        logger.debug(f"TimeWindow initialized: {start_str}-{end_str} "
                    f"({timezone_str}), crosses_midnight={self.crosses_midnight}")
    
    def _parse_time(self, time_str: str) -> time:
        """
        Parse time string into time object.
        
        Args:
            time_str: Time string in format "HH:MM"
            
        Returns:
            time object
            
        Raises:
            ValueError: If time string format is invalid
        """
        if not self.TIME_PATTERN.match(time_str):
            raise ValueError(
                f"Invalid time format: '{time_str}'. Expected format 'HH:MM' "
                f"(e.g., '17:00', '07:00')"
            )
        
        hours, minutes = map(int, time_str.split(':'))
        
        if hours < 0 or hours > 23:
            raise ValueError(f"Hours must be between 0 and 23, got {hours}")
        if minutes < 0 or minutes > 59:
            raise ValueError(f"Minutes must be between 0 and 59, got {minutes}")
        
        return time(hour=hours, minute=minutes)
    
    def _get_datetime_with_timezone(self, dt: Optional[datetime] = None) -> datetime:
        """
        Get datetime object with proper timezone.
        
        Args:
            dt: Optional datetime (if None, uses current time)
            
        Returns:
            Timezone-aware datetime
        """
        if dt is None:
            dt = datetime.now()
        
        # If dt is naive, make it timezone-aware
        if dt.tzinfo is None:
            dt = self.timezone.localize(dt)
        else:
            # Convert to target timezone
            dt = dt.astimezone(self.timezone)
        
        return dt
    
    def _get_target_date_for_time(self, target_time: time, 
                                  base_dt: datetime) -> datetime:
        """
        Get a datetime for a specific time on the appropriate date.
        
        For windows that cross midnight, this method determines whether
        the target_time should be on the same day as base_dt or the next day.
        
        Args:
            target_time: Desired time of day
            base_dt: Reference datetime
            
        Returns:
            Datetime with the target time on the appropriate date
        """
        # Start with the same date as base_dt
        target_dt = datetime.combine(base_dt.date(), target_time)
        target_dt = self.timezone.localize(target_dt)
        
        # For windows crossing midnight, the end time is on the next day
        if self.crosses_midnight and target_time == self.end_time:
            # If we're checking the end time and base_dt time is after start,
            # the end time belongs to the next day
            base_time = base_dt.time()
            if base_time >= self.start_time or base_time < self.end_time:
                target_dt += timedelta(days=1)
        
        return target_dt
    
    def is_within_window(self, dt: Optional[datetime] = None) -> bool:
        """
        Check if the given datetime is within the processing window.
        
        Args:
            dt: Optional datetime to check (defaults to now)
            
        Returns:
            True if within window, False otherwise
        """
        dt = self._get_datetime_with_timezone(dt)
        current_time = dt.time()
        
        if not self.crosses_midnight:
            # Simple case: start <= current <= end
            return self.start_time <= current_time <= self.end_time
        else:
            # Window crosses midnight: current >= start OR current <= end
            return current_time >= self.start_time or current_time <= self.end_time
    
    def get_next_window_start(self, dt: Optional[datetime] = None) -> datetime:
        """
        Calculate the next datetime when the window starts.
        
        If currently within window, returns the start of the current window.
        If outside window, returns the start of the next window.
        
        Args:
            dt: Optional datetime to calculate from (defaults to now)
            
        Returns:
            Datetime of the next window start
        """
        dt = self._get_datetime_with_timezone(dt)
        current_time = dt.time()
        
        if not self.crosses_midnight:
            # Simple case: window is within a single day
            start_dt = datetime.combine(dt.date(), self.start_time)
            start_dt = self.timezone.localize(start_dt)
            
            if self.is_within_window(dt):
                # If within window, return today's start
                return start_dt
            elif current_time < self.start_time:
                # Before window today
                return start_dt
            else:
                # After window today, return tomorrow's start
                return start_dt + timedelta(days=1)
        else:
            # Window crosses midnight
            start_dt = datetime.combine(dt.date(), self.start_time)
            start_dt = self.timezone.localize(start_dt)
            
            if self.is_within_window(dt):
                # Within window - return today's start
                return start_dt
            elif current_time < self.end_time:
                # Before window (early morning), window started yesterday
                return start_dt - timedelta(days=1)
            else:
                # After window, next window starts today
                return start_dt
    
    def seconds_until_window(self, dt: Optional[datetime] = None) -> float:
        """
        Calculate seconds until the next window starts.
        
        Args:
            dt: Optional datetime to calculate from (defaults to now)
            
        Returns:
            Seconds until window start (0 if currently within window)
        """
        if self.is_within_window(dt):
            return 0.0
        
        next_start = self.get_next_window_start(dt)
        current = self._get_datetime_with_timezone(dt)
        
        delta = next_start - current
        seconds = max(0.0, delta.total_seconds())
        
        return seconds
    
    def get_window_duration_seconds(self) -> int:
        """
        Calculate the duration of the window in seconds.
        
        Returns:
            Window duration in seconds
        """
        start_seconds = self.start_time.hour * 3600 + self.start_time.minute * 60
        end_seconds = self.end_time.hour * 3600 + self.end_time.minute * 60
        
        if not self.crosses_midnight:
            duration = end_seconds - start_seconds
        else:
            # Window crosses midnight: (24h - start) + end
            duration = (24 * 3600 - start_seconds) + end_seconds
        
        return duration
    
    def get_window_description(self) -> str:
        """
        Get human-readable description of the window.
        
        Returns:
            String describing the window
        """
        start_str = self.start_time.strftime("%H:%M")
        end_str = self.end_time.strftime("%H:%M")
        
        if self.crosses_midnight:
            return f"{start_str} to {end_str} (next day)"
        else:
            return f"{start_str} to {end_str}"
    
    def get_remaining_window_time(self, dt: Optional[datetime] = None) -> float:
        """
        Calculate seconds remaining in the current window.
        
        Args:
            dt: Optional datetime to calculate from (defaults to now)
            
        Returns:
            Seconds remaining in window (0 if outside window)
        """
        if not self.is_within_window(dt):
            return 0.0
        
        dt = self._get_datetime_with_timezone(dt)
        current_seconds = dt.hour * 3600 + dt.minute * 60 + dt.second
        
        if not self.crosses_midnight:
            end_seconds = self.end_time.hour * 3600 + self.end_time.minute * 60
            remaining = end_seconds - current_seconds
        else:
            # For windows crossing midnight, we need to know if we're before or after midnight
            current_time = dt.time()
            if current_time >= self.start_time:
                # In the evening portion (before midnight)
                end_of_day = 24 * 3600
                remaining = end_of_day - current_seconds
                # Add the next day's portion
                end_seconds = self.end_time.hour * 3600 + self.end_time.minute * 60
                remaining += end_seconds
            else:
                # In the morning portion (after midnight)
                end_seconds = self.end_time.hour * 3600 + self.end_time.minute * 60
                remaining = end_seconds - current_seconds
        
        return max(0.0, float(remaining))
    
    def get_window_boundaries(self, dt: Optional[datetime] = None) -> Tuple[datetime, datetime]:
        """
        Get the start and end datetimes of the current or next window.
        
        Args:
            dt: Optional datetime to reference (defaults to now)
            
        Returns:
            Tuple of (window_start, window_end) datetimes
        """
        dt = self._get_datetime_with_timezone(dt)
        
        if self.is_within_window(dt):
            # Current window
            start = self.get_next_window_start(dt)
        else:
            # Next window
            start = self.get_next_window_start(dt)
        
        # Calculate end time
        if not self.crosses_midnight:
            end = datetime.combine(start.date(), self.end_time)
            end = self.timezone.localize(end)
        else:
            # End time is on the next day
            end_date = start.date() + timedelta(days=1)
            end = datetime.combine(end_date, self.end_time)
            end = self.timezone.localize(end)
        
        return (start, end)
    
    def __repr__(self) -> str:
        """String representation of TimeWindow."""
        return (f"TimeWindow(start={self.start_time.strftime('%H:%M')}, "
                f"end={self.end_time.strftime('%H:%M')}, "
                f"timezone='{self.timezone_str}', "
                f"crosses_midnight={self.crosses_midnight})")


# Helper function for common window configurations
def create_night_window(timezone_str: str = "UTC") -> TimeWindow:
    """
    Create a typical night processing window (e.g., 17:00 to 07:00).
    
    Args:
        timezone_str: IANA timezone name
        
    Returns:
        TimeWindow configured for overnight processing
    """
    return TimeWindow("17:00", "07:00", timezone_str)


def create_business_hours_window(timezone_str: str = "UTC") -> TimeWindow:
    """
    Create a business hours window (09:00 to 17:00).
    
    Args:
        timezone_str: IANA timezone name
        
    Returns:
        TimeWindow configured for business hours
    """
    return TimeWindow("09:00", "17:00", timezone_str)


def create_custom_window(start_str: str, end_str: str, 
                         timezone_str: str = "UTC") -> TimeWindow:
    """
    Create a custom time window with validation.
    
    Args:
        start_str: Start time in HH:MM format
        end_str: End time in HH:MM format
        timezone_str: IANA timezone name
        
    Returns:
        TimeWindow instance
    """
    return TimeWindow(start_str, end_str, timezone_str)


# Example usage and testing
if __name__ == "__main__":
    # Example 1: Overnight window (crosses midnight)
    print("=== Overnight Window (17:00 to 07:00) ===")
    night_window = TimeWindow("17:00", "07:00", "America/New_York")
    print(f"Window: {night_window.get_window_description()}")
    print(f"Duration: {night_window.get_window_duration_seconds() / 3600} hours")
    print(f"Crosses midnight: {night_window.crosses_midnight}")
    
    # Test current time
    now = datetime.now()
    print(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Within window: {night_window.is_within_window(now)}")
    print(f"Seconds until window: {night_window.seconds_until_window(now)}")
    
    # Test specific times
    test_times = [
        datetime(2024, 1, 15, 15, 0, 0),  # 3 PM - before window
        datetime(2024, 1, 15, 18, 0, 0),  # 6 PM - in window (evening)
        datetime(2024, 1, 15, 23, 0, 0),  # 11 PM - in window
        datetime(2024, 1, 16, 2, 0, 0),   # 2 AM - in window (morning)
        datetime(2024, 1, 16, 8, 0, 0),   # 8 AM - after window
    ]
    
    print("\nTest times:")
    for test_time in test_times:
        in_window = night_window.is_within_window(test_time)
        next_start = night_window.get_next_window_start(test_time)
        print(f"  {test_time.strftime('%Y-%m-%d %H:%M')}: "
              f"in_window={in_window}, next_start={next_start.strftime('%Y-%m-%d %H:%M')}")
    
    # Example 2: Business hours (no midnight crossing)
    print("\n=== Business Hours Window (09:00 to 17:00) ===")
    business_window = TimeWindow("09:00", "17:00", "UTC")
    print(f"Window: {business_window.get_window_description()}")
    print(f"Duration: {business_window.get_window_duration_seconds() / 3600} hours")
    print(f"Crosses midnight: {business_window.crosses_midnight}")
    
    # Get window boundaries
    start, end = business_window.get_window_boundaries()
    print(f"Current window boundaries: {start} to {end}")
    
    # Example 3: Helper functions
    print("\n=== Helper Functions ===")
    default_night = create_night_window("Europe/London")
    print(f"Night window: {default_night.get_window_description()}")
    
    business = create_business_hours_window("Asia/Tokyo")
    print(f"Business hours: {business.get_window_description()}")
    
    # Example 4: Calculate remaining time
    custom = create_custom_window("22:00", "06:00", "UTC")
    now_utc = datetime.now()
    print(f"\nCustom window {custom.get_window_description()}:")
    print(f"  Within window: {custom.is_within_window(now_utc)}")
    print(f"  Remaining: {custom.get_remaining_window_time(now_utc) / 60:.1f} minutes")
