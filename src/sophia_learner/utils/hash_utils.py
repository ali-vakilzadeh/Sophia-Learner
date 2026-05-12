# src/sophia_learner/utils/hash_utils.py
import hashlib
import json
from pathlib import Path
from typing import Dict, Optional


def compute_sha256(file_path: Path, chunk_size: int = 8192) -> str:
    """
    Compute the SHA256 hash of a file.

    Args:
        file_path: Path to the file.
        chunk_size: Number of bytes to read per chunk.

    Returns:
        Hexadecimal digest of the SHA256 hash.

    Raises:
        FileNotFoundError: If the file does not exist.
        IsADirectoryError: If the path is a directory.
        PermissionError: If the file cannot be read.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_hash_chunked(file_path: Path, max_bytes: Optional[int] = None, chunk_size: int = 8192) -> str:
    """
    Compute SHA256 of only the first `max_bytes` of a file for quick deduplication.

    If `max_bytes` is None, the entire file is hashed (same as `compute_sha256`).

    Args:
        file_path: Path to the file.
        max_bytes: Maximum number of bytes to read from the start.
        chunk_size: Size of each read chunk.

    Returns:
        Hexadecimal digest of the SHA256 hash of the prefix.

    Raises:
        FileNotFoundError: If the file does not exist.
        IsADirectoryError: If the path is a directory.
        PermissionError: If the file cannot be read.
    """
    sha256 = hashlib.sha256()
    bytes_remaining = max_bytes if max_bytes is not None else None
    with open(file_path, "rb") as f:
        while bytes_remaining is None or bytes_remaining > 0:
            read_size = chunk_size if bytes_remaining is None else min(chunk_size, bytes_remaining)
            if read_size <= 0:
                break
            chunk = f.read(read_size)
            if not chunk:
                break
            sha256.update(chunk)
            if bytes_remaining is not None:
                bytes_remaining -= len(chunk)
    return sha256.hexdigest()


def verify_hash(file_path: Path, expected_hash: str, chunk_size: int = 8192) -> bool:
    """
    Verify that a file matches an expected SHA256 hash.

    Args:
        file_path: Path to the file.
        expected_hash: Hexadecimal hash to compare against.
        chunk_size: Number of bytes to read per chunk.

    Returns:
        True if the computed hash matches the expected hash, False otherwise.
    """
    try:
        actual_hash = compute_sha256(file_path, chunk_size)
        return actual_hash.lower() == expected_hash.lower()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return False


def hash_string(text: str) -> str:
    """
    Compute SHA256 hash of a UTF-8 string.

    Args:
        text: Input string.

    Returns:
        Hexadecimal digest of the SHA256 hash.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_dict(data: Dict) -> str:
    """
    Compute a stable SHA256 hash of a JSON-serializable dictionary.

    Keys are sorted to ensure equal dictionaries produce the same hash.

    Args:
        data: Dictionary to hash (must be JSON-serializable).

    Returns:
        Hexadecimal digest of the SHA256 hash of the canonical JSON representation.
    """
    # Sort keys and use compact separators to avoid whitespace variations
    json_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()
