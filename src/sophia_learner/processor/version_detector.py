"""
Version Detector - Extract and manage version information from filenames

This module provides utilities for detecting version numbers in filenames,
comparing versions, and grouping files by their logical base name.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# Global list of regex patterns for common version schemes
_VERSION_PATTERNS = [
    r'_v(\d+(?:\.\d+)*)',      # _v1, _v2.5, _v3.0.1
    r'-(\d+(?:\.\d+)*)',        # -1, -2.5.3, -10.2
    r'\((\d+(?:\.\d+)*)\)',     # (1), (2.0), (3.5.2)
    r'\.(\d+)(?=\.\w+$)',       # file.2.pdf → version "2"
    r'_(\d{8})',                # _20240101 (date as version YYYYMMDD)
]

# Additional patterns for special cases
_SPECIAL_VERSION_PATTERNS = [
    r'_v?(\d+\.\d+\.\d+)',      # v1.2.3, 1.2.3
    r'_r(\d+)',                  # _r123 (revision number)
    r'_(final|FINAL)',           # _final (maps to 999.999)
    r'_(draft|DRAFT)',           # _draft (maps to 0.001)
]


def detect_version(file_path: Path) -> Optional[str]:
    """
    Extract version from stem of filename using regex patterns.
    
    Args:
        file_path: Path object representing the file
        
    Returns:
        Version string if found, None otherwise
        
    Examples:
        >>> detect_version(Path("report_v2.pdf"))
        'v2'
        >>> detect_version(Path("data-1.5.csv"))
        '1.5'
        >>> detect_version(Path("notes(3).txt"))
        '3'
        >>> detect_version(Path("image.2.png"))
        '2'
        >>> detect_version(Path("backup_20240101.zip"))
        '20240101'
        >>> detect_version(Path("document.pdf"))
        None
    """
    # Get the stem (filename without extension)
    stem = file_path.stem
    
    # Try each pattern in order
    for pattern in _VERSION_PATTERNS:
        match = re.search(pattern, stem)
        if match:
            version = match.group(1)
            # Preserve the original format (keep prefix if it was part of pattern)
            if pattern.startswith(r'_v'):
                version = f"v{version}"
            elif pattern.startswith(r'\.'):
                # For pattern that matches before extension, keep as is
                version = version
            return version
    
    # Try special patterns (with mapping)
    for pattern in _SPECIAL_VERSION_PATTERNS:
        match = re.search(pattern, stem, re.IGNORECASE)
        if match:
            version = match.group(1)
            # Map special keywords to version numbers
            if version.lower() == 'final':
                return '999.999'
            elif version.lower() == 'draft':
                return '0.001'
            return version
    
    return None


def extract_version_number(version_str: str) -> Tuple[int, ...]:
    """
    Convert version string to a tuple of integers for comparison.
    
    Strips non-numeric prefixes (like 'v', 'r') and splits by dots.
    
    Args:
        version_str: Version string (e.g., "v2.5.1", "1.0", "r123")
        
    Returns:
        Tuple of integers for comparison (e.g., (2, 5, 1))
        
    Raises:
        ValueError: If no numeric version components can be extracted
        
    Examples:
        >>> extract_version_number("v2.5.1")
        (2, 5, 1)
        >>> extract_version_number("1.0")
        (1, 0)
        >>> extract_version_number("20240101")
        (20240101,)
        >>> extract_version_number("r123")
        (123,)
        >>> extract_version_number("final")
        (999, 999)
    """
    # Remove common prefixes
    cleaned = version_str.lower().lstrip('v').lstrip('r')
    
    # Handle special cases
    if cleaned == 'final':
        return (999, 999)
    elif cleaned == 'draft':
        return (0, 1)
    
    # Split by dots and convert to integers
    parts = cleaned.split('.')
    if not parts:
        raise ValueError(f"Cannot extract version number from: {version_str}")
    
    try:
        # Convert each part to integer
        version_tuple = tuple(int(part) for part in parts if part.isdigit())
        if not version_tuple:
            # If no digits found after stripping, try the whole string as a number
            if cleaned.isdigit():
                version_tuple = (int(cleaned),)
            else:
                raise ValueError(f"No numeric components in: {version_str}")
        return version_tuple
    except ValueError as e:
        raise ValueError(f"Invalid version format '{version_str}': {e}")


def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two version strings.
    
    Args:
        v1: First version string
        v2: Second version string
        
    Returns:
        -1 if v1 < v2
         0 if v1 == v2
         1 if v1 > v2
         
    Examples:
        >>> compare_versions("v1.0", "v2.0")
        -1
        >>> compare_versions("2.5", "1.10")
        1
        >>> compare_versions("1.2.3", "1.2.3")
        0
        >>> compare_versions("v2", "2.0")
        0
    """
    # Extract numeric tuples
    try:
        t1 = extract_version_number(v1)
        t2 = extract_version_number(v2)
    except ValueError:
        # If extraction fails, fall back to string comparison
        if v1 < v2:
            return -1
        elif v1 > v2:
            return 1
        else:
            return 0
    
    # Compare tuples element-wise
    # Pad shorter tuple with zeros for comparison
    max_len = max(len(t1), len(t2))
    t1_padded = t1 + (0,) * (max_len - len(t1))
    t2_padded = t2 + (0,) * (max_len - len(t2))
    
    for a, b in zip(t1_padded, t2_padded):
        if a < b:
            return -1
        elif a > b:
            return 1
    
    return 0


def get_base_filename(file_path: Path) -> Path:
    """
    Remove version suffix from filename to get the base logical name.
    
    Args:
        file_path: Path to the versioned file
        
    Returns:
        Path with version suffix removed
        
    Examples:
        >>> get_base_filename(Path("report_v2.pdf"))
        PosixPath('report.pdf')
        >>> get_base_filename(Path("data-1.5.csv"))
        PosixPath('data.csv')
        >>> get_base_filename(Path("notes(3).txt"))
        PosixPath('notes.txt')
        >>> get_base_filename(Path("document.pdf"))
        PosixPath('document.pdf')
    """
    stem = file_path.stem
    original_stem = stem
    suffix = file_path.suffix
    
    # Try each pattern to remove version
    for pattern in _VERSION_PATTERNS:
        # Remove version from the end of the stem
        # Pattern should match at the end of the string
        end_pattern = pattern + r'$'
        match = re.search(end_pattern, stem)
        if match:
            # Remove the matched version part
            stem = stem[:match.start()]
            break
    
    # Also check for patterns that might be at the end with underscore
    # Handle special case: "report_v2" -> "report"
    patterns_to_remove = [
        r'[-_]v?\d+(?:\.\d+)*$',  # -v2, _v2.5, -1.0, _r123
        r'\(\d+(?:\.\d+)*\)$',     # (3), (2.5)
        r'[._]\d{8}$',             # _20240101, .20240101
        r'[-_]final$',             # _final, -final
        r'[-_]draft$',             # _draft, -draft
    ]
    
    for pattern in patterns_to_remove:
        stem = re.sub(pattern, '', stem, flags=re.IGNORECASE)
    
    # If nothing was removed, return original
    if stem == original_stem:
        return file_path
    
    # Reconstruct path with same parent directory
    return file_path.parent / f"{stem}{suffix}"


def group_by_logical_file(file_paths: List[Path]) -> Dict[str, List[Path]]:
    """
    Group file paths by their logical base name (ignoring versions).
    
    Args:
        file_paths: List of file paths to group
        
    Returns:
        Dictionary mapping base name to list of versioned paths
        
    Examples:
        >>> paths = [
        ...     Path("report_v1.pdf"),
        ...     Path("report_v2.pdf"),
        ...     Path("data.csv"),
        ...     Path("data-1.5.csv"),
        ... ]
        >>> groups = group_by_logical_file(paths)
        >>> sorted(groups.keys())
        ['data', 'report']
        >>> len(groups['report'])
        2
    """
    groups = defaultdict(list)
    
    for file_path in file_paths:
        # Get base filename without version
        base_path = get_base_filename(file_path)
        base_name = base_path.stem
        
        # Also consider the full path string for uniqueness if needed
        # Use the parent directory to differentiate files with same name in different folders
        group_key = str(base_path.parent / base_name)
        
        groups[group_key].append(file_path)
    
    return dict(groups)


def get_version_chain(file_paths: List[Path]) -> Dict[str, List[Path]]:
    """
    Get version chain for a group of files, sorted by version.
    
    Args:
        file_paths: List of file paths (same logical file)
        
    Returns:
        Dictionary with 'versions' mapping version string to path,
        and 'sorted' list of (version, path) sorted ascending
        
    Examples:
        >>> paths = [Path("report_v2.pdf"), Path("report_v1.pdf")]
        >>> chain = get_version_chain(paths)
        >>> chain['sorted'][0][0]  # First version
        'v1'
    """
    version_map = {}
    
    for file_path in file_paths:
        version = detect_version(file_path)
        if version:
            version_map[version] = file_path
        else:
            # No version detected, treat as base/version 0
            version_map['0'] = file_path
    
    # Sort by version
    sorted_versions = sorted(version_map.items(), key=lambda x: extract_version_number(x[0]))
    
    return {
        'versions': version_map,
        'sorted': sorted_versions,
        'latest': sorted_versions[-1] if sorted_versions else None,
        'earliest': sorted_versions[0] if sorted_versions else None,
    }


def is_versioned(file_path: Path) -> bool:
    """
    Check if a file appears to have a version number in its name.
    
    Args:
        file_path: Path to check
        
    Returns:
        True if version pattern detected, False otherwise
    """
    return detect_version(file_path) is not None


def normalize_version(version_str: str, padding: int = 2) -> str:
    """
    Normalize version string for consistent display/storage.
    
    Pads each component to the specified width (default 2 digits).
    
    Args:
        version_str: Version string to normalize
        padding: Number of digits to pad each component to
        
    Returns:
        Normalized version string
        
    Examples:
        >>> normalize_version("v1.2")
        'v01.02'
        >>> normalize_version("2.5.1")
        '02.05.01'
        >>> normalize_version("10.2")
        '10.02'
    """
    try:
        components = extract_version_number(version_str)
        # Format each component with leading zeros
        formatted = '.'.join(str(c).zfill(padding) for c in components)
        
        # Preserve prefix if present
        if version_str.lower().startswith('v'):
            return f"v{formatted}"
        elif version_str.lower().startswith('r'):
            return f"r{formatted}"
        else:
            return formatted
    except ValueError:
        # If not a standard version, return as-is
        return version_str


def increment_version(version_str: str, position: int = -1) -> str:
    """
    Increment a version number at the specified position.
    
    Args:
        version_str: Version string to increment
        position: Which component to increment (-1 for last, 0 for first, etc.)
        
    Returns:
        Incremented version string
        
    Examples:
        >>> increment_version("v1.2.3")
        'v1.2.4'
        >>> increment_version("2.5", 0)
        '3.0'
        >>> increment_version("1.0.0", 1)
        '1.1.0'
    """
    try:
        components = list(extract_version_number(version_str))
        
        if not components:
            return version_str
        
        # Determine which component to increment
        idx = position if position >= 0 else len(components) + position
        idx = max(0, min(idx, len(components) - 1))
        
        # Increment the specified component
        components[idx] += 1
        
        # Reset subsequent components to 0
        for i in range(idx + 1, len(components)):
            components[i] = 0
        
        # Reconstruct version string
        new_version = '.'.join(str(c) for c in components)
        
        # Preserve prefix
        if version_str.lower().startswith('v'):
            return f"v{new_version}"
        elif version_str.lower().startswith('r'):
            return f"r{new_version}"
        else:
            return new_version
            
    except (ValueError, IndexError):
        return version_str
