"""
Parser Registry Module

Provides a singleton registry for managing document parsers, mapping file extensions
to parser classes, and caching parser instances for efficiency.
"""

from pathlib import Path
from typing import Dict, Type, Optional, List, Any
import logging

from .base_parser import BaseParser
from ..security.sandbox import Sandbox

# Global dictionary for parser registry
_PARSERS: Dict[str, Type[BaseParser]] = {}

logger = logging.getLogger(__name__)


class ParserRegistry:
    """
    Singleton registry for document parsers.
    
    Manages the registration and retrieval of parsers for different file
    extensions. Caches parser instances to avoid re-instantiation.
    Supports automatic registration of built-in parsers.
    
    Attributes:
        _instance: Singleton instance
        _parser_cache: Cache of parser instances by extension
        _sandbox: Optional sandbox for parsers
    """
    
    _instance: Optional['ParserRegistry'] = None
    _parser_cache: Dict[str, BaseParser] = {}
    
    def __new__(cls) -> 'ParserRegistry':
        """
        Create singleton instance if it doesn't exist.
        
        Returns:
            Singleton ParserRegistry instance
        """
        if cls._instance is None:
            cls._instance = super(ParserRegistry, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        """
        Initialize the registry (only once).
        """
        if self._initialized:
            return
        
        self._initialized = True
        self._parser_cache = {}
        self._sandbox: Optional[Sandbox] = None
        self._registered_extensions: Dict[str, Type[BaseParser]] = {}
        
        # Auto-register built-in parsers
        self.auto_register_builtins()
        
        logger.info("ParserRegistry initialized")
    
    def set_sandbox(self, sandbox: Optional[Sandbox]) -> None:
        """
        Set the sandbox to be used for all parsers.
        
        Args:
            sandbox: Sandbox instance or None
        """
        self._sandbox = sandbox
        # Clear cache so new instances will use the sandbox
        self._parser_cache.clear()
        logger.debug(f"Sandbox set for parser registry: {sandbox is not None}")
    
    def register(self, extension: str, parser_class: Type[BaseParser]) -> None:
        """
        Register a parser class for a file extension.
        
        Args:
            extension: File extension (with or without dot, e.g., '.pdf' or 'pdf')
            parser_class: Parser class (must inherit from BaseParser)
            
        Raises:
            ValueError: If extension is empty or parser_class is not a BaseParser subclass
            TypeError: If parser_class is not a class
        """
        if not extension:
            raise ValueError("Extension cannot be empty")
        
        if not isinstance(parser_class, type):
            raise TypeError(f"parser_class must be a class, got {type(parser_class)}")
        
        if not issubclass(parser_class, BaseParser):
            raise TypeError(f"parser_class must be a subclass of BaseParser, got {parser_class}")
        
        # Normalize extension: ensure it starts with dot and is lowercase
        normalized_ext = extension.lower()
        if not normalized_ext.startswith('.'):
            normalized_ext = '.' + normalized_ext
        
        # Register in global dictionary
        _PARSERS[normalized_ext] = parser_class
        
        # Register in instance dictionary
        self._registered_extensions[normalized_ext] = parser_class
        
        # Clear cached instance for this extension
        if normalized_ext in self._parser_cache:
            del self._parser_cache[normalized_ext]
        
        logger.debug(f"Registered parser {parser_class.__name__} for extension {normalized_ext}")
    
    def get_parser(self, extension: str) -> Optional[BaseParser]:
        """
        Get a parser instance for the given extension.
        
        Parsers are cached after first instantiation for efficiency.
        
        Args:
            extension: File extension (with or without dot, e.g., '.pdf' or 'pdf')
            
        Returns:
            Parser instance or None if no parser is registered for the extension
        """
        # Normalize extension
        normalized_ext = extension.lower()
        if not normalized_ext.startswith('.'):
            normalized_ext = '.' + normalized_ext
        
        # Check cache first
        if normalized_ext in self._parser_cache:
            return self._parser_cache[normalized_ext]
        
        # Check if registered
        if normalized_ext not in self._registered_extensions:
            logger.debug(f"No parser registered for extension {normalized_ext}")
            return None
        
        # Create new parser instance
        parser_class = self._registered_extensions[normalized_ext]
        try:
            # Instantiate parser with sandbox
            parser_instance = parser_class(sandbox=self._sandbox)
            self._parser_cache[normalized_ext] = parser_instance
            logger.debug(f"Created parser instance for extension {normalized_ext}")
            return parser_instance
        
        except Exception as e:
            logger.error(f"Failed to instantiate parser for {normalized_ext}: {e}")
            return None
    
    def list_supported_extensions(self) -> List[str]:
        """
        List all registered file extensions.
        
        Returns:
            List of supported file extensions (with leading dots)
        """
        return sorted(self._registered_extensions.keys())
    
    def get_parser_for_file(self, file_path: Path) -> Optional[BaseParser]:
        """
        Get a parser instance for a file based on its extension.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Parser instance or None if no parser is registered for the file's extension
        """
        if not file_path.suffix:
            logger.warning(f"File has no extension: {file_path}")
            return None
        
        return self.get_parser(file_path.suffix)
    
    def auto_register_builtins(self) -> None:
        """
        Automatically register all built-in parsers.
        
        Attempts to import and register parsers for common document formats.
        Silent failures if optional dependencies are not available.
        """
        # Register document parsers
        try:
            from .doc_parser import DocParser
            self.register('.doc', DocParser)
            logger.debug("Registered .doc parser")
        except ImportError as e:
            logger.debug(f"Could not register .doc parser: {e}")
        
        try:
            from .docx_parser import DocxParser
            self.register('.docx', DocxParser)
            logger.debug("Registered .docx parser")
        except ImportError as e:
            logger.debug(f"Could not register .docx parser: {e}")
        
        # Register spreadsheet parsers
        try:
            from .xls_parser import XlsParser
            self.register('.xls', XlsParser)
            logger.debug("Registered .xls parser")
        except ImportError as e:
            logger.debug(f"Could not register .xls parser: {e}")
        
        try:
            from .xlsx_parser import XlsxParser
            self.register('.xlsx', XlsxParser)
            logger.debug("Registered .xlsx parser")
        except ImportError as e:
            logger.debug(f"Could not register .xlsx parser: {e}")
        
        # Register PDF parser
        try:
            from .pdf_parser import PdfParser
            self.register('.pdf', PdfParser)
            logger.debug("Registered .pdf parser")
        except ImportError as e:
            logger.debug(f"Could not register .pdf parser: {e}")
        
        # Register text-based formats (simple parsers)
        self._register_text_parsers()
        
        logger.info(f"Auto-registered built-in parsers for extensions: {self.list_supported_extensions()}")
    
    def _register_text_parsers(self) -> None:
        """
        Register simple text-based parsers for common text formats.
        
        These are lightweight parsers that don't require external dependencies.
        """
        from .base_parser import BaseParser
        
        # Create simple text parser class dynamically
        class TextParser(BaseParser):
            """Simple parser for plain text files."""
            
            def extract_text(self, file_path: Path) -> str:
                self.validate_input(file_path)
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                return self.sanitize_output(text)
            
            def get_metadata(self, file_path: Path) -> Dict[str, Any]:
                self.validate_input(file_path)
                stat = file_path.stat()
                return {
                    'file_size_bytes': stat.st_size,
                    'file_extension': file_path.suffix.lower(),
                    'parser': 'text_parser'
                }
            
            def supports_encryption(self) -> bool:
                return False
        
        class MarkdownParser(BaseParser):
            """Simple parser for Markdown files."""
            
            def extract_text(self, file_path: Path) -> str:
                self.validate_input(file_path)
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                # Simple Markdown cleaning (remove formatting)
                lines = []
                for line in text.split('\n'):
                    # Remove markdown headers
                    if line.startswith('#'):
                        line = line.lstrip('#').strip()
                    # Remove bold/italic markers
                    line = line.replace('**', '').replace('*', '').replace('__', '').replace('_', '')
                    # Remove code block markers
                    if not line.startswith('```'):
                        lines.append(line)
                cleaned = '\n'.join(lines)
                return self.sanitize_output(cleaned)
            
            def get_metadata(self, file_path: Path) -> Dict[str, Any]:
                self.validate_input(file_path)
                stat = file_path.stat()
                return {
                    'file_size_bytes': stat.st_size,
                    'file_extension': file_path.suffix.lower(),
                    'parser': 'markdown_parser'
                }
            
            def supports_encryption(self) -> bool:
                return False
        
        # Register text and markdown parsers
        self.register('.txt', TextParser)
        self.register('.text', TextParser)
        self.register('.md', MarkdownParser)
        self.register('.markdown', MarkdownParser)
    
    def clear_cache(self) -> None:
        """
        Clear the parser instance cache.
        
        Useful when changing sandbox or configuration.
        """
        self._parser_cache.clear()
        logger.debug("Parser registry cache cleared")
    
    def unregister(self, extension: str) -> bool:
        """
        Unregister a parser for a file extension.
        
        Args:
            extension: File extension to unregister
            
        Returns:
            True if successfully unregistered, False otherwise
        """
        normalized_ext = extension.lower()
        if not normalized_ext.startswith('.'):
            normalized_ext = '.' + normalized_ext
        
        if normalized_ext in self._registered_extensions:
            del self._registered_extensions[normalized_ext]
            if normalized_ext in _PARSERS:
                del _PARSERS[normalized_ext]
            if normalized_ext in self._parser_cache:
                del self._parser_cache[normalized_ext]
            logger.debug(f"Unregistered parser for extension {normalized_ext}")
            return True
        
        logger.debug(f"No parser registered for extension {normalized_ext}")
        return False
    
    def is_registered(self, extension: str) -> bool:
        """
        Check if an extension has a registered parser.
        
        Args:
            extension: File extension to check
            
        Returns:
            True if a parser is registered for the extension
        """
        normalized_ext = extension.lower()
        if not normalized_ext.startswith('.'):
            normalized_ext = '.' + normalized_ext
        
        return normalized_ext in self._registered_extensions
    
    def get_registered_parsers_info(self) -> Dict[str, str]:
        """
        Get information about all registered parsers.
        
        Returns:
            Dictionary mapping extensions to parser class names
        """
        return {
            ext: parser_class.__name__
            for ext, parser_class in self._registered_extensions.items()
        }
    
    def get_parser_count(self) -> int:
        """
        Get the number of registered parsers.
        
        Returns:
            Number of registered extensions
        """
        return len(self._registered_extensions)
    
    def reload_parsers(self) -> None:
        """
        Reload all parsers by clearing cache and re-registering builtins.
        """
        self.clear_cache()
        self._registered_extensions.clear()
        self.auto_register_builtins()
        logger.info("Parsers reloaded")


# Convenience functions for direct access

def get_registry() -> ParserRegistry:
    """
    Get the global parser registry instance.
    
    Returns:
        ParserRegistry singleton instance
    """
    return ParserRegistry()


def register_parser(extension: str, parser_class: Type[BaseParser]) -> None:
    """
    Convenience function to register a parser.
    
    Args:
        extension: File extension (e.g., '.pdf')
        parser_class: Parser class to register
    """
    registry = get_registry()
    registry.register(extension, parser_class)


def get_parser(extension: str) -> Optional[BaseParser]:
    """
    Convenience function to get a parser for an extension.
    
    Args:
        extension: File extension (e.g., '.pdf')
        
    Returns:
        Parser instance or None
    """
    registry = get_registry()
    return registry.get_parser(extension)


def get_parser_for_file(file_path: Path) -> Optional[BaseParser]:
    """
    Convenience function to get a parser for a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Parser instance or None
    """
    registry = get_registry()
    return registry.get_parser_for_file(file_path)


def list_supported_extensions() -> List[str]:
    """
    Convenience function to list supported extensions.
    
    Returns:
        List of supported file extensions
    """
    registry = get_registry()
    return registry.list_supported_extensions()
