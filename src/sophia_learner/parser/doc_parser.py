"""
DOC Parser Module

Provides parser for legacy Microsoft Word .doc files using antiword or catdoc
command-line tools for text extraction and metadata retrieval.
"""

import subprocess
import shutil
import re
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from .base_parser import BaseParser, ParserError
from ..security.sandbox import Sandbox


class DocParser(BaseParser):
    """
    Parser for legacy Microsoft Word .doc files.
    
    Uses antiword (preferred) or catdoc (fallback) command-line tools to extract
    text and metadata from binary .doc files. Both tools must be installed on
    the system.
    
    Attributes:
        use_antiword: Whether to try antiword first (if available)
        use_catdoc: Whether to try catdoc as fallback
        sandbox: Optional sandbox for resource-limited execution
    """
    
    def __init__(self, sandbox: Optional[Sandbox] = None, use_antiword: bool = True, use_catdoc: bool = True):
        """
        Initialize the DOC parser.
        
        Args:
            sandbox: Optional Sandbox instance for resource-limited execution
            use_antiword: Whether to attempt using antiword (default: True)
            use_catdoc: Whether to attempt using catdoc as fallback (default: True)
        """
        super().__init__(sandbox)
        self.use_antiword = use_antiword
        self.use_catdoc = use_catdoc
        
        # Cache tool availability
        self._antiword_available = None
        self._catdoc_available = None
        
        # Validate that at least one tool is available
        if not self._is_tool_available():
            raise ParserError(
                "Neither antiword nor catdoc is available. "
                "Please install antiword (sudo apt install antiword) "
                "or catdoc (sudo apt install catdoc) for .doc file support."
            )
    
    def _check_tool_available(self, tool_name: str) -> bool:
        """
        Check if a command-line tool is available on the system.
        
        Args:
            tool_name: Name of the tool to check (e.g., 'antiword', 'catdoc')
            
        Returns:
            True if the tool is found in PATH, False otherwise
        """
        return shutil.which(tool_name) is not None
    
    def _is_tool_available(self) -> bool:
        """
        Check if at least one supported tool is available.
        
        Returns:
            True if antiword or catdoc is available
        """
        if self.use_antiword and self._antiword_available is None:
            self._antiword_available = self._check_tool_available('antiword')
        
        if self.use_catdoc and self._catdoc_available is None:
            self._catdoc_available = self._check_tool_available('catdoc')
        
        return (self.use_antiword and self._antiword_available) or \
               (self.use_catdoc and self._catdoc_available)
    
    def _run_command(self, cmd: list, tool_name: str) -> str:
        """
        Run a command and return its stdout.
        
        Args:
            cmd: Command and arguments as list
            tool_name: Name of the tool for error messages
            
        Returns:
            Command's stdout as string
            
        Raises:
            ParserError: If command fails or returns non-zero exit code
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,  # 60 second timeout
                check=False
            )
            
            if result.returncode != 0:
                error_msg = f"{tool_name} failed with exit code {result.returncode}"
                if result.stderr:
                    error_msg += f": {result.stderr}"
                raise ParserError(error_msg)
            
            return result.stdout
        
        except subprocess.TimeoutExpired:
            raise ParserError(f"{tool_name} timed out after 60 seconds")
        except FileNotFoundError:
            raise ParserError(f"{tool_name} not found at path: {cmd[0]}")
        except Exception as e:
            raise ParserError(f"Error running {tool_name}: {e}")
    
    def extract_text(self, file_path: Path) -> str:
        """
        Extract plain text from a .doc file.
        
        Attempts to use antiword first (better formatting), then falls back
        to catdoc if available.
        
        Args:
            file_path: Path to the .doc file
            
        Returns:
            Extracted plain text content
            
        Raises:
            ParserError: If no extraction tool is available or extraction fails
            FileNotFoundError: If file does not exist
            PermissionError: If file cannot be read
        """
        # Validate input
        self.validate_input(file_path)
        
        # Check if file has .doc extension
        if file_path.suffix.lower() not in ['.doc']:
            self.logger.warning(f"File {file_path} does not have .doc extension")
        
        # Try antiword first (preferred)
        if self.use_antiword and self._check_tool_available('antiword'):
            self.logger.info(f"Extracting text from {file_path} using antiword")
            try:
                # antiword options:
                # -w 0: Use ASCII character set (no UTF-8 mapping)
                # -m: Include metadata (handled separately)
                # -t: Use text output (default)
                cmd = ['antiword', '-w', '0', str(file_path)]
                text = self._run_command(cmd, 'antiword')
                
                # Sanitize output
                sanitized = self.sanitize_output(text)
                self.logger.debug(f"Extracted {len(sanitized)} characters using antiword")
                return sanitized
            
            except ParserError as e:
                self.logger.warning(f"antiword extraction failed: {e}, trying catdoc")
        
        # Fallback to catdoc
        if self.use_catdoc and self._check_tool_available('catdoc'):
            self.logger.info(f"Extracting text from {file_path} using catdoc")
            try:
                # catdoc options:
                # -a: Use ASCII output instead of UTF-8
                # -d: Use '---' as page delimiter
                # -u: Don't output unicode (use ASCII)
                cmd = ['catdoc', '-a', '-d', '---', str(file_path)]
                text = self._run_command(cmd, 'catdoc')
                
                # Sanitize output
                sanitized = self.sanitize_output(text)
                self.logger.debug(f"Extracted {len(sanitized)} characters using catdoc")
                return sanitized
            
            except ParserError as e:
                self.logger.error(f"catdoc extraction failed: {e}")
                raise
        
        # No tools available
        raise ParserError(
            "No tool available for .doc file extraction. "
            "Please install antiword or catdoc."
        )
    
    def get_metadata(self, file_path: Path) -> Dict[str, Any]:
        """
        Extract metadata from a .doc file.
        
        Uses antiword -m command to extract document metadata including
        author, title, subject, creation date, modification date, etc.
        
        Args:
            file_path: Path to the .doc file
            
        Returns:
            Dictionary containing metadata key-value pairs
            
        Raises:
            ParserError: If metadata extraction fails or no tool available
            FileNotFoundError: If file does not exist
        """
        # Validate input
        self.validate_input(file_path)
        
        metadata = {}
        
        # Try antiword first for metadata (it provides better metadata extraction)
        if self.use_antiword and self._check_tool_available('antiword'):
            self.logger.info(f"Extracting metadata from {file_path} using antiword -m")
            try:
                cmd = ['antiword', '-m', str(file_path)]
                output = self._run_command(cmd, 'antiword (metadata)')
                
                # Parse antiword metadata output
                # Format is typically: key: value
                for line in output.split('\n'):
                    line = line.strip()
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip().lower().replace(' ', '_')
                        value = value.strip()
                        
                        if value and value != '(unknown)':
                            # Convert date strings to datetime objects when possible
                            if key in ['create_date', 'creation_date', 'mod_date', 'modification_date', 'date']:
                                try:
                                    # Try to parse common date formats
                                    for fmt in ['%a %b %d %H:%M:%S %Y', '%Y-%m-%d %H:%M:%S', '%b %d %Y']:
                                        try:
                                            value = datetime.strptime(value, fmt)
                                            break
                                        except ValueError:
                                            continue
                                except Exception:
                                    # Keep as string if parsing fails
                                    pass
                            
                            metadata[key] = value
                
                # Add additional metadata
                metadata['parser'] = 'antiword'
                metadata['file_size_bytes'] = file_path.stat().st_size
                metadata['file_extension'] = file_path.suffix.lower()
                
                self.logger.debug(f"Extracted {len(metadata)} metadata fields using antiword")
                return metadata
            
            except ParserError as e:
                self.logger.warning(f"antiword metadata extraction failed: {e}")
        
        # Try catdoc for basic metadata if antiword failed
        if self.use_catdoc and self._check_tool_available('catdoc'):
            self.logger.info(f"Extracting basic metadata from {file_path} using catdoc")
            try:
                # catdoc -v provides version info but not extensive metadata
                cmd = ['catdoc', '-v', str(file_path)]
                output = self._run_command(cmd, 'catdoc')
                
                # catdoc doesn't provide structured metadata, just add basic file info
                metadata['parser'] = 'catdoc'
                metadata['file_size_bytes'] = file_path.stat().st_size
                metadata['file_extension'] = file_path.suffix.lower()
                
                # Try to extract title from first few lines of document
                try:
                    text_cmd = ['catdoc', '-a', str(file_path)]
                    text = self._run_command(text_cmd, 'catdoc (text for metadata)')
                    lines = [l.strip() for l in text.split('\n')[:10] if l.strip()]
                    if lines:
                        metadata['title_hint'] = lines[0][:200]  # First 200 chars
                except ParserError:
                    pass
                
                self.logger.debug(f"Extracted {len(metadata)} metadata fields using catdoc")
                return metadata
            
            except ParserError as e:
                self.logger.error(f"catdoc metadata extraction failed: {e}")
                raise
        
        # If we get here, no tool is available
        raise ParserError(
            "No tool available for .doc file metadata extraction. "
            "Please install antiword or catdoc."
        )
    
    def supports_encryption(self) -> bool:
        """
        Check if parser supports encrypted files.
        
        Override from BaseParser. Legacy .doc files may be encrypted with
        Microsoft Office password protection. Antiword and catdoc generally
        cannot read encrypted files.
        
        Returns:
            False (encrypted .doc files are not supported)
        """
        return False
