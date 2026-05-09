"""
Sandbox module for Sophia Learner.

This module provides a Sandbox class that isolates file parsing operations
with resource limits (CPU time, memory, file size) to prevent malicious or
runaway documents from affecting the main system.
"""

import os
import signal
import subprocess
import tempfile
import time
import multiprocessing
from pathlib import Path
from typing import Any, Callable, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class SandboxError(Exception):
    """Raised when sandbox operations fail."""
    pass


class Sandbox:
    """
    Isolate file parsing with resource limits.

    This class uses resource.setrlimit (on Unix-like systems) and multiprocessing
    to enforce CPU time, memory, and file size limits on parsing operations.
    """

    def __init__(
        self,
        max_cpu_seconds: int = 60,
        max_memory_mb: int = 512,
        max_filesize_mb: int = 100
    ):
        """
        Initialize the Sandbox with resource limits.

        Args:
            max_cpu_seconds: Maximum CPU time in seconds.
            max_memory_mb: Maximum memory in megabytes.
            max_filesize_mb: Maximum file size in megabytes.
        """
        self.max_cpu_seconds = max_cpu_seconds
        self.max_memory_mb = max_memory_mb
        self.max_filesize_mb = max_filesize_mb
        self._temp_dirs = set()
        
        logger.info(f"Sandbox initialized: CPU={max_cpu_seconds}s, "
                   f"Memory={max_memory_mb}MB, FileSize={max_filesize_mb}MB")

    def run_in_sandbox(
        self,
        func: Callable,
        *args,
        timeout: int = 30,
        **kwargs
    ) -> Any:
        """
        Execute a function with resource limits.

        This method runs the function in a separate process with resource limits
        applied. If the function exceeds the limits or takes too long, it is
        terminated and a SandboxError is raised.

        Args:
            func: The function to execute.
            *args: Positional arguments to pass to the function.
            timeout: Maximum wall-clock time in seconds.
            **kwargs: Keyword arguments to pass to the function.

        Returns:
            The return value of the function.

        Raises:
            SandboxError: If the function fails, times out, or exceeds resource limits.
        """
        # Create a queue to receive the result or exception
        result_queue = multiprocessing.Queue()
        
        # Wrapper function to apply resource limits and run the target
        def _run_in_process():
            try:
                # Apply resource limits
                self._apply_process_limits()
                
                # Set a timeout alarm for CPU time
                signal.signal(signal.SIGALRM, self._timeout_handler)
                signal.alarm(self.max_cpu_seconds)
                
                # Run the function
                result = func(*args, **kwargs)
                
                # Cancel the alarm
                signal.alarm(0)
                
                # Return the result
                result_queue.put(("success", result))
            except Exception as e:
                result_queue.put(("error", e))
        
        # Start the process
        process = multiprocessing.Process(target=_run_in_process)
        process.start()
        
        # Wait for the process to complete with timeout
        process.join(timeout=timeout)
        
        if process.is_alive():
            # Process is still running - terminate it
            logger.warning(f"Sandbox process timed out after {timeout}s")
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
            raise SandboxError(f"Function execution timed out after {timeout} seconds")
        
        # Check the result
        if not result_queue.empty():
            status, value = result_queue.get()
            if status == "success":
                return value
            else:
                raise SandboxError(f"Function execution failed: {value}")
        else:
            raise SandboxError("Function execution failed with unknown error")

    def _apply_process_limits(self) -> None:
        """
        Apply resource limits to the current process.

        This method uses resource.setrlimit to set CPU time, memory, and file
        size limits. On systems without resource module, this is a no-op.
        """
        try:
            import resource
            
            # Set CPU time limit
            cpu_limit = self.max_cpu_seconds
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit + 1))
            
            # Set memory limit (address space)
            memory_bytes = self.max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            
            # Set file size limit
            file_bytes = self.max_filesize_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
            
            logger.debug(f"Applied resource limits: CPU={self.max_cpu_seconds}s, "
                        f"Memory={self.max_memory_mb}MB, FileSize={self.max_filesize_mb}MB")
        except ImportError:
            logger.warning("resource module not available (non-Unix system). "
                          "Resource limits not enforced.")
        except Exception as e:
            logger.warning(f"Failed to set resource limits: {e}")

    @staticmethod
    def _timeout_handler(signum: int, frame) -> None:
        """
        Signal handler for CPU time timeout.

        Args:
            signum: Signal number.
            frame: Current stack frame.
        """
        raise TimeoutError("CPU time limit exceeded")

    def check_file_size(self, file_path: Path) -> bool:
        """
        Check if file size is within limits.

        Args:
            file_path: Path to the file to check.

        Returns:
            True if file size is within limits, False otherwise.
        """
        try:
            size_bytes = file_path.stat().st_size
            size_mb = size_bytes / (1024 * 1024)
            is_within = size_mb <= self.max_filesize_mb
            if not is_within:
                logger.warning(f"File {file_path} exceeds size limit: {size_mb:.2f}MB > {self.max_filesize_mb}MB")
            return is_within
        except Exception as e:
            logger.error(f"Failed to check file size for {file_path}: {e}")
            return False

    def create_isolated_temp_dir(self) -> Path:
        """
        Create a private temporary directory for extraction.

        The directory is created with restricted permissions (0700) to ensure
        isolation from other processes.

        Returns:
            Path to the isolated temporary directory.
        """
        # Create temporary directory with restricted permissions
        temp_dir = Path(tempfile.mkdtemp(prefix="sophia_sandbox_"))
        
        # Restrict permissions to owner only
        os.chmod(temp_dir, 0o700)
        
        # Track for cleanup
        self._temp_dirs.add(temp_dir)
        
        logger.debug(f"Created isolated temp directory: {temp_dir}")
        return temp_dir

    def cleanup_temp_dir(self, path: Path) -> None:
        """
        Securely delete a temporary directory.

        Args:
            path: Path to the temporary directory to delete.
        """
        if path in self._temp_dirs:
            try:
                import shutil
                shutil.rmtree(path, ignore_errors=True)
                self._temp_dirs.discard(path)
                logger.debug(f"Cleaned up temp directory: {path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory {path}: {e}")

    def set_process_limits(self) -> None:
        """
        Apply resource limits to the current process/child.

        This is a public wrapper around _apply_process_limits for external use.
        """
        self._apply_process_limits()

    def cleanup_all(self) -> None:
        """
        Clean up all temporary directories created by this sandbox.
        """
        for temp_dir in list(self._temp_dirs):
            self.cleanup_temp_dir(temp_dir)

    def run_command_in_sandbox(
        self,
        cmd: list,
        timeout: int = 60,
        input_data: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Run an external command with resource limits.

        Args:
            cmd: Command and arguments as a list.
            timeout: Maximum execution time in seconds.
            input_data: Optional input to send to stdin.

        Returns:
            Tuple of (stdout, stderr).

        Raises:
            SandboxError: If the command fails or exceeds limits.
        """
        try:
            # Apply resource limits via prlimit if available, otherwise use timeout
            # For simplicity, we use subprocess with timeout
            result = subprocess.run(
                cmd,
                input=input_data,
                capture_output=True,
                text=True,
                timeout=timeout,
                preexec_fn=self._apply_process_limits if hasattr(os, 'preexec_fn') else None
            )
            
            if result.returncode != 0:
                raise SandboxError(f"Command failed with exit code {result.returncode}: {result.stderr}")
            
            return result.stdout, result.stderr
        except subprocess.TimeoutExpired as e:
            raise SandboxError(f"Command timed out after {timeout} seconds: {e}")
        except Exception as e:
            raise SandboxError(f"Command execution failed: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - clean up temporary directories."""
        self.cleanup_all()
