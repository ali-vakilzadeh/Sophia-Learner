# src/sophia_learner/utils/retry.py
import asyncio
import functools
import time
from typing import Tuple, Type, Union, Callable, Any, Optional
from typing_extensions import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


class RetryStrategy:
    """Collection of backoff strategies for retry delays."""
    
    @staticmethod
    def linear(delay: float, attempt: int) -> float:
        """
        Linear backoff: delay * attempt.
        
        Args:
            delay: Base delay in seconds.
            attempt: Current attempt number (1-indexed).
        
        Returns:
            Delay in seconds for this attempt.
        """
        if attempt <= 0:
            return 0.0
        return delay * attempt
    
    @staticmethod
    def exponential(delay: float, attempt: int, backoff: float = 2.0) -> float:
        """
        Exponential backoff: delay * (backoff ^ (attempt - 1)).
        
        Args:
            delay: Base delay in seconds.
            attempt: Current attempt number (1-indexed).
            backoff: Multiplier factor (default 2.0).
        
        Returns:
            Delay in seconds for this attempt.
        """
        if attempt <= 0:
            return 0.0
        return delay * (backoff ** (attempt - 1))
    
    @staticmethod
    def fibonacci(delay: float, attempt: int) -> float:
        """
        Fibonacci backoff: delay * fib(attempt + 1).
        
        Args:
            delay: Base delay in seconds.
            attempt: Current attempt number (1-indexed).
        
        Returns:
            Delay in seconds for this attempt.
        """
        if attempt <= 0:
            return 0.0
        
        def fib(n: int) -> int:
            a, b = 0, 1
            for _ in range(n):
                a, b = b, a + b
            return a
        
        return delay * fib(attempt + 1)


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    strategy: str = "exponential",
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator for retrying synchronous functions on specified exceptions.
    
    Args:
        max_attempts: Maximum number of retry attempts (including initial call).
        delay: Initial delay between retries in seconds.
        backoff: Backoff multiplier for exponential strategy.
        exceptions: Tuple of exception types to retry on.
        strategy: Backoff strategy ('linear', 'exponential', or 'fibonacci').
    
    Returns:
        Decorated function with retry logic.
    
    Raises:
        ValueError: If max_attempts < 1 or strategy invalid.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    
    valid_strategies = {"linear", "exponential", "fibonacci"}
    if strategy not in valid_strategies:
        raise ValueError(f"strategy must be one of {valid_strategies}")
    
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_attempts:
                        break
                    
                    # Calculate delay based on strategy
                    if strategy == "linear":
                        wait_time = RetryStrategy.linear(delay, attempt)
                    elif strategy == "exponential":
                        wait_time = RetryStrategy.exponential(delay, attempt, backoff)
                    else:  # fibonacci
                        wait_time = RetryStrategy.fibonacci(delay, attempt)
                    
                    time.sleep(wait_time)
            
            raise last_exception  # type: ignore
        
        return wrapper
    
    return decorator


def retry_async(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    strategy: str = "exponential",
) -> Callable[[Callable[P, Any]], Callable[P, Any]]:
    """
    Decorator for retrying asynchronous functions on specified exceptions.
    
    Args:
        max_attempts: Maximum number of retry attempts (including initial call).
        delay: Initial delay between retries in seconds.
        backoff: Backoff multiplier for exponential strategy.
        exceptions: Tuple of exception types to retry on.
        strategy: Backoff strategy ('linear', 'exponential', or 'fibonacci').
    
    Returns:
        Decorated async function with retry logic.
    
    Raises:
        ValueError: If max_attempts < 1 or strategy invalid.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    
    valid_strategies = {"linear", "exponential", "fibonacci"}
    if strategy not in valid_strategies:
        raise ValueError(f"strategy must be one of {valid_strategies}")
    
    def decorator(func: Callable[P, Any]) -> Callable[P, Any]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_attempts:
                        break
                    
                    # Calculate delay based on strategy
                    if strategy == "linear":
                        wait_time = RetryStrategy.linear(delay, attempt)
                    elif strategy == "exponential":
                        wait_time = RetryStrategy.exponential(delay, attempt, backoff)
                    else:  # fibonacci
                        wait_time = RetryStrategy.fibonacci(delay, attempt)
                    
                    await asyncio.sleep(wait_time)
            
            raise last_exception  # type: ignore
        
        return wrapper
    
    return decorator


def is_retryable_error(error: Exception, retryable_types: Tuple[Type[Exception], ...]) -> bool:
    """
    Check if an error instance matches any retryable exception type.
    
    Args:
        error: The exception to check.
        retryable_types: Tuple of exception types to consider retryable.
    
    Returns:
        True if error is an instance of any retryable type, False otherwise.
    """
    if not retryable_types:
        return False
    
    return isinstance(error, retryable_types)
