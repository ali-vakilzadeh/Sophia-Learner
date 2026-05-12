"""
Secure file operations for Sophia Learner.

This module provides secure file handling utilities including atomic writes,
safe copies, directory creation with proper permissions, and path traversal
prevention.
"""

import os
import shutil
import tempfile
import time
import hashlib
from pathlib import Path
from typing import Union, Optional
import stat

from sophia_learner.utils.logger import get_logger


logger = get_logger(__name__)


def safe_copy(src: Path, dst: Path, preserve_metadata: bool = False) -> None:
    """
    Copy file with error handling and permission preservation.
    
    Args:
        src: Source file path
        dst: Destination file path
        preserve_metadata: If True, preserve file metadata (timestamps, permissions)
        
    Raises:
        FileNotFoundError: If source file doesn't exist
        PermissionError: If copy operation lacks permissions
        OSError: For other file operation errors
    """
    src = Path(src)
    dst = Path(dst)
    
    if not src.exists():
        raise FileNotFoundError(f"Source file does not exist: {src}")
    
    if not src.is_file():
        raise ValueError(f"Source is not a regular file: {src}")
    
    # Ensure destination directory exists
    dst.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        if preserve_metadata:
            # Copy with metadata preservation
            shutil.copy2(src, dst)
        else:
            # Basic copy without metadata
            shutil.copy(src, dst)
        
        # Ensure safe permissions (remove world write/read)
        dst.chmod(dst.stat().st_mode & 0o770)
        
        logger.debug(f"Copied {src} -> {dst} (metadata preserved: {preserve_metadata})")
        
    except PermissionError as e:
        logger.error(f"Permission denied copying {src} to {dst}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to copy {src} to {dst}: {e}")
        raise


def atomic_write(file_path: Path, content: Union[str, bytes]) -> None:
    """
    Write content to file atomically using a temporary file.
    
    Args:
        file_path: Path where content should be written
        content: String or bytes content to write
        
    Raises:
        IOError: If write operation fails
    """
    file_path = Path(file_path)
    
    # Ensure directory exists
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create temporary file in same directory (ensures same filesystem)
    fd, temp_path = tempfile.mkstemp(
        dir=file_path.parent,
        prefix=f".{file_path.name}.tmp",
        suffix=''
    )
    temp_path = Path(temp_path)
    
    try:
        # Write content
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        os.write(fd, content)
        os.close(fd)
        
        # Set safe permissions (owner rw, group r, others none)
        temp_path.chmod(0o640)
        
        # Atomic rename
        temp_path.rename(file_path)
        
        logger.debug(f"Atomically wrote {len(content)} bytes to {file_path}")
        
    except Exception as e:
        # Clean up temp file on error
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception:
            pass
        
        logger.error(f"Atomic write failed for {file_path}: {e}")
        raise IOError(f"Failed to write {file_path}: {e}")
    
    finally:
        # Ensure file descriptor is closed
        try:
            os.close(fd)
        except Exception:
            pass


def get_file_size_safe(file_path: Path) -> int:
    """
    Get file size safely, returning 0 on error.
    
    Args:
        file_path: Path to file
        
    Returns:
        File size in bytes, or 0 if error
    """
    try:
        return file_path.stat().st_size
    except (PermissionError, FileNotFoundError, OSError) as e:
        logger.debug(f"Could not get size for {file_path}: {e}")
        return 0


def ensure_directory(path: Path, mode: int = 0o750) -> None:
    """
    Create directory with safe permissions if it doesn't exist.
    
    Permissions: owner rwx (7), group r-x (5), others --- (0)
    
    Args:
        path: Directory path to create
        mode: Permission mode (default 0o750)
        
    Raises:
        PermissionError: If directory cannot be created
        OSError: For other filesystem errors
    """
    path = Path(path)
    
    if path.exists():
        if not path.is_dir():
            raise NotADirectoryError(f"Path exists but is not a directory: {path}")
        
        # Check and fix permissions if needed
        current_mode = path.stat().st_mode & 0o777
        if current_mode != mode:
            try:
                path.chmod(mode)
                logger.debug(f"Fixed permissions for {path}: {oct(current_mode)} -> {oct(mode)}")
            except Exception as e:
                logger.warning(f"Could not change permissions for {path}: {e}")
        
        return
    
    try:
        # Create directory with specified permissions
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(mode)
        logger.debug(f"Created directory: {path} (mode: {oct(mode)})")
        
    except PermissionError as e:
        logger.error(f"Permission denied creating directory {path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to create directory {path}: {e}")
        raise


def secure_delete(file_path: Path, passes: int = 1) -> None:
    """
    Securely delete file by overwriting before deletion.
    
    Args:
        file_path: Path to file to delete
        passes: Number of overwrite passes (default 1 for speed, 3-7 for high security)
        
    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If deletion lacks permissions
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if not file_path.is_file():
        raise ValueError(f"Not a regular file: {file_path}")
    
    try:
        file_size = file_path.stat().st_size
        
        # Overwrite file content
        with open(file_path, 'r+b') as f:
            for _ in range(passes):
                # Seek to beginning
                f.seek(0)
                
                # Write random data
                f.write(os.urandom(file_size))
                f.flush()
                os.fsync(f.fileno())
                
                # Additional pass with zeros for thoroughness (only if multiple passes)
                if passes > 1:
                    f.seek(0)
                    f.write(b'\x00' * file_size)
                    f.flush()
                    os.fsync(f.fileno())
        
        # Rename to temporary name (makes recovery harder)
        temp_name = file_path.parent / f".deleted_{hashlib.sha256(str(file_path).encode()).hexdigest()[:16]}"
        file_path.rename(temp_name)
        
        # Delete the file
        temp_name.unlink()
        
        logger.info(f"Securely deleted {file_path} ({file_size} bytes, {passes} passes)")
        
    except PermissionError as e:
        logger.error(f"Permission denied deleting {file_path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to securely delete {file_path}: {e}")
        raise


def is_path_safe(base_dir: Path, target_path: Path) -> bool:
    """
    Prevent path traversal attacks by checking resolved paths.
    
    Args:
        base_dir: Base directory that access should be limited to
        target_path: Path to check for safety
        
    Returns:
        True if target_path is within base_dir, False otherwise
    """
    try:
        # Resolve both paths to absolute (follows symlinks)
        base_resolved = base_dir.resolve()
        target_resolved = target_path.resolve()
        
        # Check if target is inside base directory
        is_safe = target_resolved.is_relative_to(base_resolved)
        
        if not is_safe:
            logger.warning(f"Path traversal attempt: {target_path} -> {target_resolved} "
                          f"is not within {base_resolved}")
        
        return is_safe
        
    except Exception as e:
        logger.error(f"Error checking path safety: {e}")
        return False


def get_unique_filename(directory: Path, prefix: str = "", suffix: str = "") -> Path:
    """
    Generate a unique filename in the specified directory.
    
    Args:
        directory: Directory where file will be created
        prefix: Optional filename prefix
        suffix: Optional filename suffix (including extension)
        
    Returns:
        Unique file path that doesn't exist yet
        
    Example:
        >>> get_unique_filename(Path("/tmp"), "file_", ".txt")
        PosixPath('/tmp/file_20240101_123456_1.txt')
    """
    directory = Path(directory)
    ensure_directory(directory)
    
    # Try timestamp-based filename first
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    base_name = f"{prefix}{timestamp}{suffix}"
    candidate = directory / base_name
    
    if not candidate.exists():
        return candidate
    
    # Add counter if timestamp already exists
    counter = 1
    while True:
        name = f"{prefix}{timestamp}_{counter}{suffix}"
        candidate = directory / name
        if not candidate.exists():
            return candidate
        counter += 1


def wait_for_file_stable(file_path: Path, check_interval: float = 0.5, 
                         max_wait_seconds: int = 30) -> bool:
    """
    Wait for file to become stable (complete write operation).
    
    Monitors file size changes to detect when writing is complete.
    
    Args:
        file_path: Path to file to monitor
        check_interval: Seconds between size checks
        max_wait_seconds: Maximum time to wait
        
    Returns:
        True if file became stable, False if timeout
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        logger.debug(f"File does not exist yet: {file_path}")
        # Wait for file to appear
        start_time = time.time()
        while not file_path.exists():
            if time.time() - start_time > max_wait_seconds:
                logger.warning(f"Timeout waiting for file to appear: {file_path}")
                return False
            time.sleep(check_interval)
    
    # Wait for file size to stabilize
    last_size = -1
    stable_count = 0
    start_time = time.time()
    
    while time.time() - start_time < max_wait_seconds:
        try:
            current_size = file_path.stat().st_size
            
            if current_size == last_size:
                stable_count += 1
                # File size stable for 3 consecutive checks
                if stable_count >= 3:
                    logger.debug(f"File stable: {file_path} ({current_size} bytes)")
                    return True
            else:
                stable_count = 0
                last_size = current_size
            
            time.sleep(check_interval)
            
        except FileNotFoundError:
            # File might have been moved/deleted
            logger.debug(f"File disappeared during monitoring: {file_path}")
            return False
        except Exception as e:
            logger.warning(f"Error checking file stability: {e}")
            time.sleep(check_interval)
    
    logger.warning(f"Timeout waiting for file to stabilize: {file_path}")
    return False


def safe_move(src: Path, dst: Path, overwrite: bool = False) -> None:
    """
    Safely move a file with error handling.
    
    Args:
        src: Source file path
        dst: Destination file path
        overwrite: If True, overwrite existing destination
        
    Raises:
        FileExistsError: If destination exists and overwrite is False
        FileNotFoundError: If source doesn't exist
    """
    src = Path(src)
    dst = Path(dst)
    
    if not src.exists():
        raise FileNotFoundError(f"Source file not found: {src}")
    
    if dst.exists() and not overwrite:
        raise FileExistsError(f"Destination exists and overwrite=False: {dst}")
    
    # Ensure destination directory exists
    dst.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Use atomic replace if available (Python 3.3+)
        src.replace(dst)
        logger.debug(f"Moved {src} -> {dst}")
    except Exception as e:
        logger.error(f"Failed to move {src} to {dst}: {e}")
        raise


def safe_remove(file_path: Path, secure: bool = False) -> bool:
    """
    Safely remove a file.
    
    Args:
        file_path: Path to file to remove
        secure: If True, use secure deletion (overwrite before delete)
        
    Returns:
        True if file was removed, False if file didn't exist
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        return False
    
    try:
        if secure:
            secure_delete(file_path, passes=1)
        else:
            file_path.unlink()
            logger.debug(f"Removed {file_path}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to remove {file_path}: {e}")
        raise


def get_directory_size(directory: Path) -> int:
    """
    Calculate total size of directory contents.
    
    Args:
        directory: Directory path
        
    Returns:
        Total size in bytes
    """
    directory = Path(directory)
    
    if not directory.exists():
        return 0
    
    total_size = 0
    try:
        for item in directory.rglob('*'):
            if item.is_file():
                total_size += get_file_size_safe(item)
    except Exception as e:
        logger.warning(f"Error calculating directory size for {directory}: {e}")
    
    return total_size


def list_files_by_age(directory: Path, pattern: str = "*", 
                      reverse: bool = False) -> list:
    """
    List files in directory sorted by modification time.
    
    Args:
        directory: Directory to scan
        pattern: Glob pattern for file matching
        reverse: If True, newest first (default: oldest first)
        
    Returns:
        List of Path objects sorted by modification time
    """
    directory = Path(directory)
    
    if not directory.exists():
        return []
    
    files = list(directory.glob(pattern))
    files = [f for f in files if f.is_file()]
    
    files.sort(key=lambda p: p.stat().st_mtime, reverse=reverse)
    
    return files


def create_temp_directory(prefix: str = "sophia_") -> Path:
    """
    Create a secure temporary directory.
    
    Args:
        prefix: Prefix for temporary directory name
        
    Returns:
        Path to created temporary directory
    """
    temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
    ensure_directory(temp_dir, mode=0o750)
    
    logger.debug(f"Created temporary directory: {temp_dir}")
    return temp_dir


def cleanup_temp_directory(temp_dir: Path, secure: bool = False) -> None:
    """
    Clean up temporary directory and its contents.
    
    Args:
        temp_dir: Temporary directory path
        secure: If True, securely delete files before removal
    """
    temp_dir = Path(temp_dir)
    
    if not temp_dir.exists():
        return
    
    try:
        if secure:
            # Securely delete all files
            for file_path in temp_dir.rglob('*'):
                if file_path.is_file():
                    secure_delete(file_path, passes=1)
        
        # Remove directory and contents
        shutil.rmtree(temp_dir)
        logger.debug(f"Cleaned up temporary directory: {temp_dir}")
        
    except Exception as e:
        logger.warning(f"Failed to cleanup temporary directory {temp_dir}: {e}")


# Example usage and testing
if __name__ == "__main__":
    import tempfile
    
    print("=== File Utilities Test ===\n")
    
    # Create test directory
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "test"
        test_dir.mkdir()
        
        print("1. Testing ensure_directory...")
        test_subdir = test_dir / "subdir"
        ensure_directory(test_subdir)
        print(f"  Created directory: {test_subdir} (exists: {test_subdir.exists()})")
        
        print("\n2. Testing atomic_write...")
        test_file = test_dir / "test.txt"
        atomic_write(test_file, "Hello, World!")
        print(f"  Wrote to {test_file}")
        print(f"  Content: {test_file.read_text()}")
        
        print("\n3. Testing safe_copy...")
        copy_file = test_dir / "copy.txt"
        safe_copy(test_file, copy_file)
        print(f"  Copied to {copy_file}")
        
        print("\n4. Testing get_file_size_safe...")
        size = get_file_size_safe(test_file)
        print(f"  File size: {size} bytes")
        
        print("\n5. Testing get_unique_filename...")
        unique1 = get_unique_filename(test_dir, "temp_", ".tmp")
        unique2 = get_unique_filename(test_dir, "temp_", ".tmp")
        print(f"  Unique filenames: {unique1.name}, {unique2.name}")
        
        print("\n6. Testing is_path_safe...")
        safe_path = is_path_safe(test_dir, test_subdir)
        unsafe_path = is_path_safe(test_dir, Path("/etc/passwd"))
        print(f"  Safe path: {safe_path}")
        print(f"  Unsafe path: {unsafe_path}")
        
        print("\n7. Testing wait_for_file_stable...")
        # Create a file with delay simulation
        slow_file = test_dir / "slow.txt"
        import threading
        
        def write_slowly():
            time.sleep(0.5)
            atomic_write(slow_file, "Content written slowly")
        
        thread = threading.Thread(target=write_slowly)
        thread.start()
        
        stable = wait_for_file_stable(slow_file, check_interval=0.2, max_wait_seconds=5)
        print(f"  File stable: {stable}")
        
        print("\n8. Testing list_files_by_age...")
        for i in range(3):
            f = test_dir / f"file_{i}.txt"
            f.write_text(f"Content {i}")
            time.sleep(0.1)
        
        files = list_files_by_age(test_dir, "*.txt")
        print(f"  Files by age (oldest first): {[f.name for f in files]}")
        
        print("\n9. Testing secure_delete...")
        sensitive_file = test_dir / "secret.txt"
        atomic_write(sensitive_file, "Sensitive data")
        secure_delete(sensitive_file, passes=1)
        print(f"  Sensitive file deleted: {not sensitive_file.exists()}")
        
        print("\n10. Testing create_temp_directory...")
        temp_work = create_temp_directory("sophia_test_")
        print(f"  Created temp dir: {temp_work}")
        cleanup_temp_directory(temp_work)
        print(f"  Cleaned up temp dir: {not temp_work.exists()}")
        
        print("\n✓ All file utility tests completed")
