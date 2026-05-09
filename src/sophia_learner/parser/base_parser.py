"""
Base Parser Module

Provides abstract base class for all document parsers in the Sophia Learner system.
Defines the contract that all concrete parser implementations must follow.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional

from ..security.sanitizer import sanitize_text

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """
    Abstract base class for all document parsers.
    
    This class defines the interface that all concrete parser implementations
    must implement, including text extraction, metadata retrieval, input validation,
    and output sanitization.
    
    Attributes:
        sandbox: Optional sandbox instance for resource-limited execution
    """
    
    def __init__(self, sandbox: Optional[Any] = None):
        """
        Initialize the base parser.
        
        Args:
            sandbox: Optional Sandbox instance for resource-limited execution.
                    If provided, parsers should use it for resource isolation.
        """
        self.sandbox = sandbox
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @abstractmethod
    def extract_text(self, file_path: Path) -> str:
        """
        Extract plain text content from the document.
        
        This method must be implemented by concrete parser classes to extract
        text content from their specific file format. The extracted text should
        be as clean and readable as possible, preserving document structure
        where appropriate (paragraphs, tables, etc.).
        
        Args:
            file_path: Path to the document file to extract text from
            
        Returns:
            Extracted plain text content
            
        Raises:
            FileNotFoundError: If the file does not exist
            PermissionError: If the file cannot be read
            ParserError: If parsing fails for any reason
            SandboxError: If sandbox execution fails (when sandbox is used)
            SecurityError: If file fails security validation
            EncryptedFileError: If file is encrypted and not supported
        """
        pass
    
    @abstractmethod
    def get_metadata(self, file_path: Path) -> Dict[str, Any]:
        """
        Extract metadata from the document.
        
        This method must be implemented by concrete parser classes to extract
        metadata such as author, creation date, modification date, page count,
        and other format-specific properties.
        
        Args:
            file_path: Path to the document file to extract metadata from
            
        Returns:
            Dictionary containing metadata key-value pairs.
            Common keys include:
                - 'author': Document author
                - 'creation_date': Creation date/time
                - 'modification_date': Last modification date/time
                - 'page_count': Number of pages (for page-based formats)
                - 'sheet_count': Number of sheets (for spreadsheet formats)
                - 'title': Document title
                - 'subject': Document subject/subtitle
                - 'keywords': Document keywords/tags
                - 'creator': Application that created the document
                - 'producer': Application that produced the document
            
        Raises:
            FileNotFoundError: If the file does not exist
            PermissionError: If the file cannot be read
            ParserError: If metadata extraction fails
        """
        pass
    
    def sanitize_output(self, text: str) -> str:
        """
        Sanitize extracted text before returning.
        
        This method applies common sanitization operations to the extracted text,
        including removing null bytes, control characters, and potentially dangerous
        escape sequences.
        
        Args:
            text: Raw extracted text to sanitize
            
        Returns:
            Sanitized text safe for further processing
        """
        if not text:
            return ""
        
        try:
            # Use the centralized sanitizer module
            sanitized = sanitize_text(text)
            self.logger.debug(f"Sanitized text: {len(text)} -> {len(sanitized)} characters")
            return sanitized
        except Exception as e:
            self.logger.error(f"Error during text sanitization: {e}")
            # Return original text as fallback (but this should be rare)
            return text
    
    def validate_input(self, file_path: Path) -> None:
        """
        Validate input file before parsing.
        
        Checks that the file exists, is readable, and meets basic requirements.
        Raises appropriate exceptions if validation fails.
        
        Args:
            file_path: Path to validate
            
        Raises:
            FileNotFoundError: If file does not exist
            PermissionError: If file cannot be read
            ValueError: If file_path is not a file or has no extension
            FileSizeError: If file exceeds configured size limits
        """
        # Check if path exists
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Check if it's a file (not directory)
        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")
        
        # Check if readable
        if not file_path.is_readable():
            raise PermissionError(f"File is not readable: {file_path}")
        
        # Check if file has extension
        if not file_path.suffix:
            raise ValueError(f"File has no extension, cannot determine parser: {file_path}")
        
        # Check if file is empty
        if file_path.stat().st_size == 0:
            raise ValueError(f"File is empty: {file_path}")
        
        # Additional validation for encryption will be handled by subclasses
        # through the supports_encryption() method
        self.logger.debug(f"Input validation passed for: {file_path}")
    
    def supports_encryption(self) -> bool:
        """
        Check if the parser supports encrypted files.
        
        By default, encrypted files are not supported. Subclasses that can handle
        encrypted files (e.g., with password support) should override this method.
        
        Returns:
            True if the parser can handle encrypted files, False otherwise
        """
        return False
    
    def __str__(self) -> str:
        """Return string representation of the parser."""
        return f"{self.__class__.__name__}(sandbox={self.sandbox is not None})"
    
    def __repr__(self) -> str:
        """Return detailed string representation of the parser."""
        return f"{self.__class__.__name__}(sandbox={self.sandbox is not None})"


# Custom exception classes for parser errors

class ParserError(Exception):
    """Base exception for parser-related errors."""
    pass


class SandboxError(ParserError):
    """Exception raised when sandbox execution fails."""
    pass


class SecurityError(ParserError):
    """Exception raised when file fails security validation."""
    pass


class EncryptedFileError(ParserError):
    """Exception raised when attempting to parse an encrypted file without support."""
    pass


class FileSizeError(ParserError):
    """Exception raised when file size exceeds configured limits."""
    pass


class UnsupportedFormatError(ParserError):
    """Exception raised when file format is not supported by the parser."""
    pass
