# src/sophia_learner/utils/time_utils.py
import time
from datetime import datetime, time as dt_time, timedelta
from typing import Tuple
import pytz


def wait_until(target_time: datetime, poll_interval: float = 1.0) -> None:
    """
    Sleep until the specified datetime.
    
    Args:
        target_time: The datetime to wait until.
        poll_interval: How often to check the time (seconds).
    
    Note:
        If target_time is in the past, this function returns immediately.
        Handles both naive and aware datetimes.
    """
    now = datetime.now(target_time.tzinfo) if target_time.tzinfo else datetime.now()
    
    if target_time <= now:
        return
    
    while True:
        now = datetime.now(target_time.tzinfo) if target_time.tzinfo else datetime.now()
        if target_time <= now:
            break
        sleep_seconds = min(poll_interval, (target_time - now).total_seconds())
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)


def parse_time_window(window_str: str) -> Tuple[dt_time, dt_time]:
    """
    Parse a time window string into start and end times.
    
    Args:
        window_str: String in format "HH:MM-HH:MM" (e.g., "17:00-07:00").
    
    Returns:
        Tuple of (start_time, end_time).
    
    Raises:
        ValueError: If the string format is invalid.
    """
    try:
        parts = window_str.strip().split('-')
        if len(parts) != 2:
            raise ValueError(f"Invalid time window format: {window_str}. Expected 'HH:MM-HH:MM'")
        
        start_str, end_str = parts
        start = datetime.strptime(start_str.strip(), "%H:%M").time()
        end = datetime.strptime(end_str.strip(), "%H:%M").time()
        return (start, end)
    except ValueError as e:
        raise ValueError(f"Failed to parse time window '{window_str}': {e}")


def human_duration(seconds: int) -> str:
    """
    Convert seconds to a human-readable duration string.
    
    Args:
        seconds: Number of seconds.
    
    Returns:
        String like "2 days, 3 hours, 15 minutes".
    
    Examples:
        >>> human_duration(3665)
        '1 hour, 5 seconds'
        >>> human_duration(90000)
        '1 day, 1 hour'
    """
    if seconds < 0:
        raise ValueError("Duration cannot be negative")
    
    if seconds == 0:
        return "0 seconds"
    
    # Calculate time units
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    
    # Build parts list
    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds > 0:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    
    # Join with commas and "and" if needed
    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    else:
        return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def to_iso8601(dt: datetime) -> str:
    """
    Format a datetime as ISO 8601 string.
    
    Args:
        dt: Datetime to format.
    
    Returns:
        ISO 8601 formatted string (e.g., "2024-01-01T12:00:00").
    
    Note:
        Microseconds are trimmed for cleaner output.
    """
    return dt.isoformat(timespec='seconds' if dt.microsecond else 'auto')


def from_iso8601(iso_str: str) -> datetime:
    """
    Parse an ISO 8601 datetime string.
    
    Args:
        iso_str: ISO 8601 formatted string.
    
    Returns:
        Datetime object (may be naive or aware).
    
    Raises:
        ValueError: If the string cannot be parsed.
    """
    # Python 3.11+ can handle many formats, but we provide compatibility
    try:
        # Handle UTC timezone indicator 'Z'
        if iso_str.endswith('Z'):
            iso_str = iso_str[:-1] + '+00:00'
        return datetime.fromisoformat(iso_str)
    except ValueError as e:
        raise ValueError(f"Failed to parse ISO 8601 string '{iso_str}': {e}")


def get_timezone_aware_now(timezone_str: str) -> datetime:
    """
    Get the current datetime in the specified timezone.
    
    Args:
        timezone_str: Timezone name (e.g., "UTC", "America/New_York", "Europe/London").
    
    Returns:
        Timezone-aware datetime object.
    
    Raises:
        pytz.UnknownTimeZoneError: If the timezone is invalid.
    """
    try:
        tz = pytz.timezone(timezone_str)
        return datetime.now(tz)
    except pytz.UnknownTimeZoneError as e:
        raise pytz.UnknownTimeZoneError(f"Unknown timezone: {timezone_str}") from e


def format_timestamp(dt: datetime, format: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format a datetime as a timestamp string.
    
    Args:
        dt: Datetime to format.
        format: Format string (uses same format as datetime.strftime).
    
    Returns:
        Formatted timestamp string.
    
    Examples:
        >>> format_timestamp(datetime(2024, 1, 1, 12, 0, 0))
        '2024-01-01 12:00:00'
    """
    return dt.strftime(format)
