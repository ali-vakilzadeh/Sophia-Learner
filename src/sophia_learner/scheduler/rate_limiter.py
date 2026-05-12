"""
Rate limiting for file processing to prevent resource exhaustion.

This module provides the RateLimiter class which enforces configurable delays
between file processing operations to ensure system stability and fair
resource allocation across multiple files.
"""

import time
import threading
from typing import Optional

from sophia_learner.utils.logger import get_logger


logger = get_logger(__name__)


class RateLimiter:
    """
    Enforce delay between file processing operations.
    
    This class ensures that consecutive processing operations are spaced
    by at least a minimum delay, preventing resource exhaustion and
    ensuring fair distribution of system resources.
    
    Attributes:
        delay_seconds: Minimum seconds to wait between processing operations
        _last_process_time: Timestamp of the last recorded processing operation
        _lock: Thread lock for thread-safe operations
    """
    
    def __init__(self, delay_seconds: int):
        """
        Initialize RateLimiter with specified delay.
        
        Args:
            delay_seconds: Minimum seconds to wait between processing operations.
                          Must be >= 0. Zero means no rate limiting.
                          
        Raises:
            ValueError: If delay_seconds is negative
        """
        if delay_seconds < 0:
            raise ValueError(f"delay_seconds must be >= 0, got {delay_seconds}")
        
        self.delay_seconds = delay_seconds
        self._last_process_time: Optional[float] = None
        self._lock = threading.Lock()
        
        logger.debug(f"RateLimiter initialized with {delay_seconds} second delay")
    
    def wait_if_needed(self) -> None:
        """
        Wait (sleep) if the required delay hasn't elapsed since last processing.
        
        This method is thread-safe and will sleep for the remaining cooldown
        time if processing would occur too soon after the last recorded
        processing operation.
        
        If delay_seconds is 0, this method returns immediately without waiting.
        """
        if self.delay_seconds <= 0:
            return
        
        with self._lock:
            if self._last_process_time is None:
                # No previous processing, no need to wait
                return
            
            elapsed = time.time() - self._last_process_time
            remaining = self.delay_seconds - elapsed
            
            if remaining > 0:
                # Need to wait
                logger.debug(f"Rate limiting: waiting {remaining:.2f} seconds "
                           f"(delay={self.delay_seconds}s, elapsed={elapsed:.2f}s)")
                
                # Release lock while sleeping to allow other operations
                # Note: We release the lock before sleeping to avoid blocking
                # other threads that might want to check cooldown or record
                # processing. The wait is based on the timestamp, so sleeping
                # outside the lock is safe.
                pass
        
        # Sleep outside the lock to allow concurrent access
        if remaining > 0:
            time.sleep(remaining)
    
    def record_processing(self) -> None:
        """
        Record that a processing operation has occurred.
        
        This updates the timestamp used for future rate limiting checks.
        Should be called immediately after a file has been processed.
        
        This method is thread-safe.
        """
        with self._lock:
            self._last_process_time = time.time()
            logger.debug(f"Recorded processing at {self._last_process_time}")
    
    def set_delay(self, delay_seconds: int) -> None:
        """
        Dynamically adjust the delay between processing operations.
        
        This allows runtime adjustment of the rate limit based on system
        load or other conditions.
        
        Args:
            delay_seconds: New delay in seconds (must be >= 0)
            
        Raises:
            ValueError: If delay_seconds is negative
        """
        if delay_seconds < 0:
            raise ValueError(f"delay_seconds must be >= 0, got {delay_seconds}")
        
        with self._lock:
            old_delay = self.delay_seconds
            self.delay_seconds = delay_seconds
            logger.info(f"Rate limit changed from {old_delay}s to {delay_seconds}s")
    
    def reset(self) -> None:
        """
        Reset the rate limiter state.
        
        This clears the recorded last processing time, effectively allowing
        the next processing operation to proceed immediately without waiting.
        
        Useful for error recovery or when restarting processing batches.
        """
        with self._lock:
            self._last_process_time = None
            logger.debug("RateLimiter reset - next processing will not wait")
    
    def get_remaining_cooldown(self) -> float:
        """
        Get the remaining cooldown time in seconds.
        
        Returns:
            Seconds remaining until next processing is allowed.
            Returns 0.0 if no cooldown is active or if delay_seconds is 0.
        """
        if self.delay_seconds <= 0:
            return 0.0
        
        with self._lock:
            if self._last_process_time is None:
                return 0.0
            
            elapsed = time.time() - self._last_process_time
            remaining = self.delay_seconds - elapsed
            
            return max(0.0, remaining)
    
    def get_time_since_last_processing(self) -> Optional[float]:
        """
        Get the time elapsed since the last processing operation.
        
        Returns:
            Seconds since last processing, or None if no processing has occurred.
        """
        with self._lock:
            if self._last_process_time is None:
                return None
            
            return time.time() - self._last_process_time
    
    def is_rate_limited(self) -> bool:
        """
        Check if the next processing operation would be rate limited.
        
        Returns:
            True if a wait would be required before next processing,
            False if processing can proceed immediately.
        """
        remaining = self.get_remaining_cooldown()
        return remaining > 0.01  # Small epsilon for floating point
    
    def get_stats(self) -> dict:
        """
        Get current rate limiter statistics.
        
        Returns:
            Dictionary containing current rate limiter state.
        """
        with self._lock:
            return {
                'delay_seconds': self.delay_seconds,
                'last_process_time': self._last_process_time,
                'time_since_last': self.get_time_since_last_processing(),
                'is_rate_limited': self.is_rate_limited(),
                'remaining_cooldown': self.get_remaining_cooldown()
            }
    
    def __enter__(self):
        """
        Context manager entry - waits for rate limit if needed.
        
        This allows using RateLimiter as a context manager that automatically
        enforces the delay before executing the block.
        
        Example:
            with rate_limiter:
                process_file()
        """
        self.wait_if_needed()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit - records processing if no exception occurred.
        
        Records the processing time only if the block completed successfully,
        allowing failed operations to be retried without waiting.
        """
        if exc_type is None:
            # No exception - record successful processing
            self.record_processing()
        else:
            # Exception occurred - don't record, allowing immediate retry
            logger.debug("Exception in context block, not recording processing time")


class AdaptiveRateLimiter(RateLimiter):
    """
    Rate limiter that adapts based on processing times and system load.
    
    This extension of RateLimiter dynamically adjusts the delay based on
    observed processing times and configurable target utilization.
    
    Attributes:
        target_utilization: Target CPU/utilization (0.0 to 1.0)
        min_delay_seconds: Minimum allowed delay
        max_delay_seconds: Maximum allowed delay
        adaptation_factor: How quickly to adapt (0.0 to 1.0)
        _processing_times: List of recent processing times
        _max_history: Maximum number of processing times to track
    """
    
    def __init__(self, initial_delay_seconds: int = 10,
                 target_utilization: float = 0.7,
                 min_delay_seconds: int = 1,
                 max_delay_seconds: int = 300,
                 adaptation_factor: float = 0.1,
                 max_history: int = 10):
        """
        Initialize adaptive rate limiter.
        
        Args:
            initial_delay_seconds: Initial delay between operations
            target_utilization: Target resource utilization (0.0 to 1.0)
            min_delay_seconds: Minimum allowed delay
            max_delay_seconds: Maximum allowed delay
            adaptation_factor: Adaptation speed (0.0 = slow, 1.0 = fast)
            max_history: Number of recent processing times to track
        """
        super().__init__(initial_delay_seconds)
        
        if not 0.0 <= target_utilization <= 1.0:
            raise ValueError(f"target_utilization must be between 0 and 1, got {target_utilization}")
        if not 0.0 <= adaptation_factor <= 1.0:
            raise ValueError(f"adaptation_factor must be between 0 and 1, got {adaptation_factor}")
        
        self.target_utilization = target_utilization
        self.min_delay_seconds = min_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.adaptation_factor = adaptation_factor
        self._processing_times: list = []
        self._max_history = max_history
        
        logger.info(f"AdaptiveRateLimiter initialized: target_util={target_utilization}, "
                   f"delay_range=[{min_delay_seconds}, {max_delay_seconds}]")
    
    def record_processing(self) -> None:
        """
        Record processing time and adapt delay based on observed duration.
        
        This method tracks the time taken for processing and adjusts
        the rate limit to achieve the target utilization.
        """
        with self._lock:
            current_time = time.time()
            if self._last_process_time is not None:
                processing_time = current_time - self._last_process_time
                
                # Store processing time (clamp to reasonable values)
                self._processing_times.append(min(processing_time, 3600))
                if len(self._processing_times) > self._max_history:
                    self._processing_times.pop(0)
                
                # Calculate average processing time
                avg_processing = sum(self._processing_times) / len(self._processing_times)
                
                # Calculate optimal delay based on target utilization
                # Ideal: delay = processing_time * (1/target_utilization - 1)
                if self.target_utilization > 0:
                    optimal_delay = avg_processing * (1.0 / self.target_utilization - 1.0)
                    
                    # Apply exponential moving average for smooth adaptation
                    current_delay = self.delay_seconds
                    new_delay = (current_delay * (1 - self.adaptation_factor) +
                                optimal_delay * self.adaptation_factor)
                    
                    # Clamp to configured range
                    new_delay = max(self.min_delay_seconds, 
                                   min(self.max_delay_seconds, new_delay))
                    
                    # Apply integer delay (round to nearest second)
                    new_delay_int = int(round(new_delay))
                    
                    if new_delay_int != current_delay:
                        logger.debug(f"Adapting delay: {current_delay}s -> {new_delay_int}s "
                                   f"(avg_processing={avg_processing:.2f}s, "
                                   f"optimal={optimal_delay:.2f}s)")
                        self.delay_seconds = new_delay_int
            
            self._last_process_time = current_time
    
    def get_adaptive_stats(self) -> dict:
        """
        Get statistics about adaptive behavior.
        
        Returns:
            Dictionary with adaptation-related statistics.
        """
        with self._lock:
            avg_processing = sum(self._processing_times) / len(self._processing_times) if self._processing_times else 0
            
            return {
                **self.get_stats(),
                'target_utilization': self.target_utilization,
                'min_delay_seconds': self.min_delay_seconds,
                'max_delay_seconds': self.max_delay_seconds,
                'adaptation_factor': self.adaptation_factor,
                'avg_processing_time': avg_processing,
                'processing_time_samples': len(self._processing_times),
                'sample_count': len(self._processing_times)
            }
    
    def reset_adaptation(self) -> None:
        """
        Reset adaptation history while preserving current delay.
        """
        with self._lock:
            self._processing_times.clear()
            logger.debug("Adaptation history reset")


# Example usage and testing
if __name__ == "__main__":
    import time
    
    # Example 1: Basic rate limiting
    print("=== Basic Rate Limiter ===")
    limiter = RateLimiter(delay_seconds=2)
    
    print("Processing file 1...")
    limiter.wait_if_needed()
    limiter.record_processing()
    
    print("Processing file 2 (will wait)...")
    start = time.time()
    limiter.wait_if_needed()
    limiter.record_processing()
    elapsed = time.time() - start
    print(f"  Waited {elapsed:.2f} seconds (expected ~2 seconds)")
    
    # Check cooldown
    remaining = limiter.get_remaining_cooldown()
    print(f"Remaining cooldown: {remaining:.2f} seconds")
    
    # Reset and check
    limiter.reset()
    print(f"After reset, is_rate_limited: {limiter.is_rate_limited()}")
    
    # Example 2: Using context manager
    print("\n=== Context Manager Usage ===")
    limiter2 = RateLimiter(delay_seconds=1)
    
    for i in range(3):
        with limiter2:
            print(f"Processing batch {i+1} at {time.time():.2f}")
            time.sleep(0.1)  # Simulate processing
    
    # Example 3: Adaptive rate limiting
    print("\n=== Adaptive Rate Limiter ===")
    adaptive = AdaptiveRateLimiter(
        initial_delay_seconds=5,
        target_utilization=0.6,
        min_delay_seconds=2,
        max_delay_seconds=30,
        adaptation_factor=0.3
    )
    
    # Simulate varying processing times
    processing_times = [1, 2, 4, 8, 6, 4, 3]  # Varying durations
    
    for i, proc_time in enumerate(processing_times):
        print(f"\nIteration {i+1}:")
        print(f"  Current delay: {adaptive.delay_seconds}s")
        
        # Simulate waiting if needed
        adaptive.wait_if_needed()
        
        # Simulate processing
        print(f"  Processing (takes {proc_time}s)...")
        time.sleep(proc_time)
        
        # Record processing (this will adapt the delay)
        adaptive.record_processing()
        
        stats = adaptive.get_adaptive_stats()
        print(f"  Stats: avg_processing={stats['avg_processing_time']:.2f}s, "
              f"new_delay={stats['delay_seconds']}s")
    
    # Example 4: Thread safety test
    print("\n=== Thread Safety Test ===")
    import threading
    
    shared_limiter = RateLimiter(delay_seconds=0.5)
    results = []
    
    def process_file(worker_id: int):
        shared_limiter.wait_if_needed()
        start = time.time()
        shared_limiter.record_processing()
        elapsed = time.time() - start
        results.append((worker_id, elapsed))
        print(f"Worker {worker_id} processed at {start:.3f}")
    
    threads = []
    for i in range(5):
        t = threading.Thread(target=process_file, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    # Verify rate limiting across threads
    timestamps = [r[1] for r in results]
    print(f"Processing timestamps: {[f'{t:.3f}' for t in timestamps]}")
    
    # Example 5: Error handling in context manager
    print("\n=== Error Handling ===")
    error_limiter = RateLimiter(delay_seconds=1)
    
    for attempt in range(2):
        try:
            with error_limiter:
                print(f"Attempt {attempt+1}: Processing...")
                if attempt == 0:
                    raise ValueError("Simulated processing error")
                print("  Success!")
        except ValueError as e:
            print(f"  Error occurred: {e}")
            print(f"  Rate limiter not affected (can retry immediately)")
            
            # Check if we can retry immediately (should be True)
            if not error_limiter.is_rate_limited():
                print("  Can retry immediately - waiting not required")
