"""
Security Scanner Module

Provides virus scanning functionality using ClamAV (Clam AntiVirus).
Handles file and directory scanning, quarantine management, and availability checking.
"""

import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Tuple, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class VirusScanner:
    """
    Interface to ClamAV for virus scanning.
    
    This class provides methods to scan files and directories for malware
    using the ClamAV antivirus engine, with quarantine functionality for
    infected files.
    
    Attributes:
        scan_command: Base command for clamscan
        timeout: Maximum time in seconds for a scan operation
    """
    
    def __init__(self, scan_command: str = "clamscan --no-summary --infected", timeout: int = 300):
        """
        Initialize the VirusScanner with ClamAV configuration.
        
        Args:
            scan_command: ClamAV scan command with default options.
                         Default: "clamscan --no-summary --infected"
            timeout: Maximum time in seconds for scan operations (default: 300)
        """
        self.scan_command = scan_command
        self.timeout = timeout
        self._available = None  # Cache for availability check
        
        # Common ClamAV command variations to try
        self._clamav_variants = [
            "clamscan",
            "/usr/bin/clamscan",
            "/usr/local/bin/clamscan",
        ]
    
    def _get_clamav_command(self) -> Optional[str]:
        """
        Find the actual ClamAV scanner command path.
        
        Returns:
            Full path to clamscan if found, None otherwise
        """
        # Split the command to get the executable
        base_cmd = self.scan_command.split()[0]
        
        # Check if the command exists in PATH or at absolute path
        for variant in [base_cmd] + self._clamav_variants:
            if shutil.which(variant):
                return variant
        
        return None
    
    def _run_clamav_command(self, cmd: list) -> Tuple[int, str, str]:
        """
        Execute a ClamAV command with timeout and error handling.
        
        Args:
            cmd: List of command arguments
            
        Returns:
            Tuple of (return_code, stdout, stderr)
            
        Raises:
            subprocess.TimeoutExpired: If command exceeds timeout
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False  # Don't raise on non-zero exit
            )
            return result.returncode, result.stdout, result.stderr
        
        except subprocess.TimeoutExpired as e:
            logger.error(f"ClamAV scan timed out after {self.timeout} seconds")
            raise
        except FileNotFoundError:
            logger.error(f"ClamAV command not found: {cmd[0]}")
            raise
        except Exception as e:
            logger.error(f"Error running ClamAV command: {e}")
            raise
    
    def is_clamav_available(self) -> bool:
        """
        Check if ClamAV is available and properly configured.
        
        Returns:
            True if ClamAV is available and can be used, False otherwise
        """
        if self._available is not None:
            return self._available
        
        # Find the actual clamscan command
        clam_path = self._get_clamav_command()
        if not clam_path:
            logger.warning("ClamAV not found in system PATH")
            self._available = False
            return False
        
        # Try to run a simple version check
        try:
            result = subprocess.run(
                [clam_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False
            )
            
            if result.returncode == 0 and result.stdout:
                logger.info(f"ClamAV available: {result.stdout.strip()}")
                self._available = True
                return True
            else:
                logger.warning(f"ClamAV version check failed: {result.stderr}")
                self._available = False
                return False
        
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.warning(f"ClamAV availability check failed: {e}")
            self._available = False
            return False
    
    def scan_file(self, file_path: Path) -> Tuple[bool, str]:
        """
        Scan a single file for viruses.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            Tuple of (is_clean, message) where:
                is_clean: True if file is clean (no viruses found)
                message: Scan result message or virus name if infected
            
        Raises:
            FileNotFoundError: If file does not exist
            RuntimeError: If ClamAV is not available
            subprocess.TimeoutExpired: If scan exceeds timeout
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if not self.is_clamav_available():
            raise RuntimeError("ClamAV is not available. Please install clamav and clamav-daemon.")
        
        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")
        
        # Build the scan command
        clam_path = self._get_clamav_command()
        cmd = [clam_path]
        
        # Parse existing arguments from scan_command
        existing_args = self.scan_command.split()[1:] if len(self.scan_command.split()) > 1 else []
        cmd.extend(existing_args)
        
        # Add the file to scan
        cmd.append(str(file_path))
        
        logger.debug(f"Running ClamAV scan on {file_path}")
        
        # Execute the scan
        returncode, stdout, stderr = self._run_clamav_command(cmd)
        
        # Parse the result
        # ClamAV exit codes:
        # 0: Clean
        # 1: Virus found
        # 2: Error
        if returncode == 0:
            # File is clean
            message = "File is clean"
            logger.info(f"Scan result for {file_path}: CLEAN")
            return True, message
        elif returncode == 1:
            # Virus found - extract virus name from output
            # Output format example: "filename: virusname FOUND"
            if stdout:
                lines = stdout.strip().split('\n')
                for line in lines:
                    if 'FOUND' in line:
                        # Extract virus name
                        parts = line.split(':')
                        if len(parts) >= 2:
                            virus_part = parts[1].strip()
                            virus_name = virus_part.replace('FOUND', '').strip()
                            message = f"Virus detected: {virus_name}"
                        else:
                            message = line.strip()
                        break
                else:
                    message = stdout.strip()
            else:
                message = "Virus detected (no details available)"
            
            logger.warning(f"Scan result for {file_path}: {message}")
            return False, message
        else:
            # Error occurred
            error_msg = f"ClamAV scan error (code {returncode}): {stderr or stdout}"
            logger.error(f"Scan error for {file_path}: {error_msg}")
            raise RuntimeError(error_msg)
    
    def scan_directory(self, directory: Path) -> Dict[Path, str]:
        """
        Scan all files in a directory for viruses.
        
        Args:
            directory: Path to the directory to scan
            
        Returns:
            Dictionary mapping infected file paths to virus names/messages
            
        Raises:
            FileNotFoundError: If directory does not exist
            RuntimeError: If ClamAV is not available
        """
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        if not directory.is_dir():
            raise ValueError(f"Path is not a directory: {directory}")
        
        if not self.is_clamav_available():
            raise RuntimeError("ClamAV is not available. Please install clamav and clamav-daemon.")
        
        infected_files = {}
        
        # Get all files in directory recursively
        files_to_scan = list(directory.rglob('*'))
        files_to_scan = [f for f in files_to_scan if f.is_file()]
        
        if not files_to_scan:
            logger.info(f"No files found in {directory}")
            return infected_files
        
        logger.info(f"Scanning {len(files_to_scan)} files in {directory}")
        
        # Build recursive scan command for directory
        clam_path = self._get_clamav_command()
        cmd = [clam_path]
        
        # Parse existing arguments from scan_command
        existing_args = self.scan_command.split()[1:] if len(self.scan_command.split()) > 1 else []
        cmd.extend(existing_args)
        
        # Add recursive flag if not already present
        if '-r' not in cmd and '--recursive' not in cmd:
            cmd.append('-r')
        
        # Add the directory to scan
        cmd.append(str(directory))
        
        # Execute the scan
        try:
            returncode, stdout, stderr = self._run_clamav_command(cmd)
            
            # Parse output for infected files
            # ClamAV output format for infected files: "./path/to/file.txt: virusname FOUND"
            if stdout:
                for line in stdout.strip().split('\n'):
                    if 'FOUND' in line and not line.startswith('-----------'):
                        # Parse the line to extract file path and virus name
                        parts = line.split(':')
                        if len(parts) >= 2:
                            file_path_str = parts[0].strip()
                            virus_part = parts[1].strip()
                            virus_name = virus_part.replace('FOUND', '').strip()
                            
                            # Convert to absolute path
                            infected_path = Path(file_path_str)
                            if not infected_path.is_absolute():
                                infected_path = directory / infected_path
                            
                            infected_files[infected_path.resolve()] = virus_name or "Unknown virus"
            
            if infected_files:
                logger.warning(f"Found {len(infected_files)} infected files in {directory}")
            else:
                logger.info(f"No infected files found in {directory}")
            
            return infected_files
        
        except (subprocess.TimeoutExpired, RuntimeError) as e:
            logger.error(f"Directory scan failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during directory scan: {e}")
            raise
    
    def quarantine_infected(self, file_path: Path, quarantine_dir: Path) -> Path:
        """
        Move an infected file to quarantine directory.
        
        Args:
            file_path: Path to the infected file
            quarantine_dir: Directory where quarantined files should be stored
            
        Returns:
            Path to the quarantined file location
            
        Raises:
            FileNotFoundError: If file does not exist
            RuntimeError: If quarantine directory cannot be created or file cannot be moved
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")
        
        # Create quarantine directory if it doesn't exist
        try:
            quarantine_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Cannot create quarantine directory {quarantine_dir}: {e}")
        
        # Create a timestamp for the quarantine file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        
        # Create quarantine subdirectories by date
        date_subdir = datetime.now().strftime("%Y/%m/%d")
        full_quarantine_path = quarantine_dir / date_subdir
        full_quarantine_path.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename in quarantine
        original_filename = file_path.name
        stem = file_path.stem
        suffix = file_path.suffix
        
        # Add source path hash to avoid collisions
        source_hash = abs(hash(str(file_path.parent))) % 10000
        quarantined_name = f"{stem}_{timestamp}_{source_hash}{suffix}"
        
        quarantine_path = full_quarantine_path / quarantined_name
        
        # Also create metadata file with original location information
        metadata_path = quarantine_path.with_suffix(quarantine_path.suffix + '.meta')
        
        try:
            # Move the file to quarantine
            shutil.move(str(file_path), str(quarantine_path))
            
            # Write metadata
            metadata = {
                "original_path": str(file_path.resolve()),
                "original_name": original_filename,
                "quarantine_date": timestamp,
                "quarantine_path": str(quarantine_path),
            }
            
            with open(metadata_path, 'w') as f:
                import json
                json.dump(metadata, f, indent=2)
            
            logger.info(f"Quarantined infected file: {file_path} -> {quarantine_path}")
            
            return quarantine_path
        
        except Exception as e:
            raise RuntimeError(f"Failed to quarantine file {file_path}: {e}")
    
    def update_virus_definitions(self) -> bool:
        """
        Update ClamAV virus definitions using freshclam.
        
        Returns:
            True if update was successful, False otherwise
        """
        if not self.is_clamav_available():
            logger.warning("Cannot update definitions: ClamAV not available")
            return False
        
        try:
            # Try to run freshclam
            result = subprocess.run(
                ["freshclam", "--stdout"],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes for update
                check=False
            )
            
            if result.returncode == 0:
                logger.info("Virus definitions updated successfully")
                return True
            else:
                logger.warning(f"Failed to update virus definitions: {result.stderr}")
                return False
        
        except subprocess.TimeoutExpired:
            logger.error("Virus definition update timed out")
            return False
        except FileNotFoundError:
            logger.warning("freshclam not found - cannot update definitions")
            return False
        except Exception as e:
            logger.error(f"Error updating virus definitions: {e}")
            return False
    
    def get_version(self) -> Optional[str]:
        """
        Get ClamAV version information.
        
        Returns:
            Version string if available, None otherwise
        """
        if not self.is_clamav_available():
            return None
        
        clam_path = self._get_clamav_command()
        
        try:
            result = subprocess.run(
                [clam_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False
            )
            
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip()
            else:
                return None
        
        except (subprocess.TimeoutExpired, Exception):
            return None
