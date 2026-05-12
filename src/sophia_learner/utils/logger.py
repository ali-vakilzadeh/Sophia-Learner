"""
Logging configuration and management for Sophia Learner.

This module provides centralized logging setup with rotating file handlers,
structured logging for security events, and dynamic log level adjustment.
"""

import logging
import logging.handlers
import json
import sys
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

# Global state
_LOGGERS: Dict[str, logging.Logger] = {}
_SECURITY_LOGGER: Optional[logging.Logger] = None
_JSON_FORMAT_ENABLED: bool = False


def setup_logging(config) -> None:
    """
    Configure logging with rotating file handlers and console output.
    
    Args:
        config: LoggingConfig object with level, log_dir, max_log_size_mb,
                backup_count, and json_format settings
    """
    global _JSON_FORMAT_ENABLED
    
    # Get configuration values
    log_level = getattr(logging, config.level.upper(), logging.INFO)
    log_dir = Path(config.log_dir)
    max_bytes = config.max_log_size_mb * 1024 * 1024
    backup_count = config.backup_count
    _JSON_FORMAT_ENABLED = config.json_format
    
    # Create log directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Define formatters
    if _JSON_FORMAT_ENABLED:
        # JSON formatter for structured logging
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_entry = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                    "module": record.module,
                    "function": record.funcName,
                    "line": record.lineno
                }
                
                # Add exception info if present
                if record.exc_info:
                    log_entry["exception"] = self.formatException(record.exc_info)
                
                # Add extra fields if present
                if hasattr(record, 'extra_data'):
                    log_entry["extra"] = record.extra_data
                
                return json.dumps(log_entry)
        
        formatter = JSONFormatter()
        console_formatter = JSONFormatter()
    else:
        # Standard text formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_formatter = logging.Formatter(
            '%(levelname)s: %(message)s'
        )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # File handler for main log (rotating)
    main_log_path = log_dir / "sophia_learner.log"
    file_handler = logging.handlers.RotatingFileHandler(
        main_log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # Error log file (separate file for errors only)
    error_log_path = log_dir / "errors.log"
    error_handler = logging.handlers.RotatingFileHandler(
        error_log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)
    
    # Setup security logger (separate file)
    security_log_path = log_dir / "security.log"
    security_handler = logging.handlers.RotatingFileHandler(
        security_log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    security_handler.setLevel(logging.INFO)
    
    if _JSON_FORMAT_ENABLED:
        security_formatter = JSONFormatter()
    else:
        security_formatter = logging.Formatter(
            '%(asctime)s - SECURITY - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    security_handler.setFormatter(security_formatter)
    
    # Create security logger
    security_logger = logging.getLogger('security')
    security_logger.setLevel(logging.INFO)
    security_logger.addHandler(security_handler)
    security_logger.propagate = False  # Don't propagate to root logger
    
    global _SECURITY_LOGGER
    _SECURITY_LOGGER = security_logger
    
    # Log startup message
    root_logger.info(f"Logging initialized - Level: {config.level}, "
                     f"Directory: {log_dir}, JSON: {_JSON_FORMAT_ENABLED}")
    
    # Log Python version for debugging
    root_logger.debug(f"Python version: {sys.version}")
    
    # Set uncaught exception handler
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        root_logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    
    sys.excepthook = handle_exception


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with consistent formatting.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Logger instance (cached in _LOGGERS)
    """
    if name in _LOGGERS:
        return _LOGGERS[name]
    
    # Create new logger
    logger = logging.getLogger(name)
    
    # Ensure logger has at least one handler (fallback)
    if not logger.handlers:
        # Fallback: basic console logging if setup_logging wasn't called
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.warning("Logging not properly configured - using fallback handler")
    
    # Cache the logger
    _LOGGERS[name] = logger
    return logger


def get_security_logger() -> logging.Logger:
    """
    Get dedicated security logger for security events.
    
    Returns:
        Security logger instance
    """
    if _SECURITY_LOGGER is None:
        # Fallback: create security logger with basic config
        security_logger = logging.getLogger('security')
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s - SECURITY - %(message)s'
        )
        handler.setFormatter(formatter)
        security_logger.addHandler(handler)
        security_logger.setLevel(logging.INFO)
        security_logger.propagate = False
        return security_logger
    
    return _SECURITY_LOGGER


def log_security_event(event_type: str, file_path: Path, details: Dict) -> None:
    """
    Log a structured security event.
    
    Args:
        event_type: Type of security event (e.g., 'virus_detected', 'macro_found')
        file_path: Path to the file involved
        details: Dictionary with additional event details
    """
    security_logger = get_security_logger()
    
    # Build structured log entry
    log_entry = {
        'event_type': event_type,
        'file_path': str(file_path),
        'file_name': file_path.name,
        'timestamp': datetime.utcnow().isoformat(),
        **details
    }
    
    if _JSON_FORMAT_ENABLED:
        # JSON format already handled by formatter
        security_logger.info(json.dumps(log_entry))
    else:
        # Human-readable format
        # Remove sensitive or large data from message
        safe_details = {k: v for k, v in details.items() 
                       if k not in ['content', 'raw_data']}
        
        message = f"SECURITY_EVENT: {event_type} | File: {file_path.name}"
        if safe_details:
            message += f" | Details: {safe_details}"
        
        security_logger.info(message)
    
    # Also log to main logger for awareness
    main_logger = get_logger(__name__)
    main_logger.debug(f"Security event logged: {event_type} for {file_path}")


def set_log_level(level: str) -> None:
    """
    Dynamically adjust log level for all handlers.
    
    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {level}')
    
    # Update root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Update all handlers
    for handler in root_logger.handlers:
        handler.setLevel(numeric_level)
    
    # Update security logger handlers
    if _SECURITY_LOGGER:
        for handler in _SECURITY_LOGGER.handlers:
            handler.setLevel(numeric_level)
    
    # Update all cached loggers
    for logger in _LOGGERS.values():
        logger.setLevel(numeric_level)
    
    get_logger(__name__).info(f"Log level changed to {level.upper()}")


def add_file_handler(logger: logging.Logger, file_path: Path, level: str = "INFO") -> None:
    """
    Add a file handler to an existing logger.
    
    Args:
        logger: Logger instance
        file_path: Path to log file
        level: Log level for this handler
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Create handler
    handler = logging.FileHandler(file_path, encoding='utf-8')
    handler.setLevel(numeric_level)
    
    # Set formatter
    if _JSON_FORMAT_ENABLED:
        class SimpleJSONFormatter(logging.Formatter):
            def format(self, record):
                return json.dumps({
                    "timestamp": datetime.utcnow().isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                    "module": record.module
                })
        formatter = SimpleJSONFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def remove_all_handlers(logger: logging.Logger) -> None:
    """
    Remove all handlers from a logger.
    
    Args:
        logger: Logger instance
    """
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)


def get_logger_stats() -> Dict[str, Any]:
    """
    Get statistics about current logging configuration.
    
    Returns:
        Dictionary with logging statistics
    """
    root_logger = logging.getLogger()
    
    handlers_info = []
    for handler in root_logger.handlers:
        handler_type = type(handler).__name__
        handler_info = {
            'type': handler_type,
            'level': logging.getLevelName(handler.level)
        }
        
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            handler_info['file'] = str(handler.baseFilename)
            handler_info['max_bytes'] = handler.maxBytes
            handler_info['backup_count'] = handler.backupCount
        
        handlers_info.append(handler_info)
    
    return {
        'root_level': logging.getLevelName(root_logger.level),
        'handlers': handlers_info,
        'cached_loggers': len(_LOGGERS),
        'json_format': _JSON_FORMAT_ENABLED,
        'security_logger_configured': _SECURITY_LOGGER is not None
    }


# Convenience decorator for function logging
def log_function_call(logger: Optional[logging.Logger] = None):
    """
    Decorator to log function entry and exit.
    
    Args:
        logger: Logger instance (uses module logger if None)
    
    Returns:
        Decorated function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            nonlocal logger
            if logger is None:
                logger = get_logger(func.__module__)
            
            logger.debug(f"Entering {func.__name__}")
            try:
                result = func(*args, **kwargs)
                logger.debug(f"Exiting {func.__name__}")
                return result
            except Exception as e:
                logger.error(f"Exception in {func.__name__}: {e}", exc_info=True)
                raise
        
        return wrapper
    return decorator


# Example usage and testing
if __name__ == "__main__":
    import tempfile
    
    print("=== Logger Module Test ===\n")
    
    # Create temporary config
    class MockLoggingConfig:
        def __init__(self, log_dir, json_format=False):
            self.level = "DEBUG"
            self.log_dir = log_dir
            self.max_log_size_mb = 1
            self.backup_count = 3
            self.json_format = json_format
    
    # Test with text format
    print("1. Testing text format logging...")
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir)
        config = MockLoggingConfig(log_dir, json_format=False)
        
        setup_logging(config)
        
        # Get test logger
        logger = get_logger("test_module")
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        
        # Test security logging
        log_security_event(
            "test_event",
            Path("/tmp/test_file.txt"),
            {"user": "test_user", "action": "test"}
        )
        
        # Test set_log_level
        set_log_level("WARNING")
        logger.debug("This should not appear")
        logger.warning("This warning should appear")
        
        # Get stats
        stats = get_logger_stats()
        print(f"  Logger stats: {stats}")
        
        # Check log files
        log_files = list(log_dir.glob("*.log"))
        print(f"  Log files created: {[f.name for f in log_files]}")
        
        # Verify content of main log
        main_log = log_dir / "sophia_learner.log"
        if main_log.exists():
            content = main_log.read_text()
            print(f"  Main log size: {len(content)} bytes")
            print(f"  First line preview: {content[:100]}...")
    
    # Test with JSON format
    print("\n2. Testing JSON format logging...")
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir)
        config = MockLoggingConfig(log_dir, json_format=True)
        
        setup_logging(config)
        
        logger = get_logger("json_test")
        logger.info("JSON formatted log message")
        
        log_security_event(
            "virus_scan",
            Path("/malicious/file.exe"),
            {"virus_name": "EICAR_Test", "action": "quarantined"}
        )
        
        # Check JSON format
        main_log = log_dir / "sophia_learner.log"
        if main_log.exists():
            content = main_log.read_text()
            print(f"  JSON log preview: {content[:200]}...")
            
            # Try to parse JSON
            try:
                first_line = content.split('\n')[0]
                parsed = json.loads(first_line)
                print(f"  Successfully parsed JSON: {parsed.get('level')} - {parsed.get('message')[:50]}")
            except json.JSONDecodeError as e:
                print(f"  Failed to parse JSON: {e}")
    
    # Test decorator
    print("\n3. Testing function decorator...")
    
    @log_function_call()
    def test_function(x: int, y: int) -> int:
        return x + y
    
    result = test_function(3, 5)
    print(f"  Function result: {result}")
    
    # Test error handling
    print("\n4. Testing error logging...")
    
    @log_function_call()
    def failing_function():
        raise ValueError("Test error")
    
    try:
        failing_function()
    except ValueError:
        print("  Error caught and logged")
    
    print("\n5. Logger usage examples:")
    print("""
    # In your code:
    from sophia_learner.utils.logger import get_logger, log_security_event
    
    logger = get_logger(__name__)
    logger.info("Processing file...")
    
    # For security events:
    log_security_event(
        'macro_detected',
        file_path,
        {'macro_count': 3, 'action': 'stripped'}
    )
    
    # Dynamic log level change:
    from sophia_learner.utils.logger import set_log_level
    set_log_level('DEBUG')  # Enable debug logging
    """)
