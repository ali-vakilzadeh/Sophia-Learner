"""
PDF Parser Module

Provides parser for PDF files using pdfplumber as primary extractor
with PyPDF2 fallback. Includes automatic table detection and conversion
to JSON format embedded in text output.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from datetime import datetime

from .base_parser import BaseParser, ParserError, EncryptedFileError
from ..security.sandbox import Sandbox


class PdfParser(BaseParser):
    """
    Parser for PDF files with table detection and conversion.
    
    Uses pdfplumber as primary extractor (better table detection) with
    PyPDF2 as fallback. Automatically detects tables in PDFs and converts
    them to JSON format embedded in the text output, preserving table
    structure for AI training.
    
    Attributes:
        max_pages: Maximum number of pages to extract (None = all)
        extract_tables: Whether to detect and extract tables (default: True)
        table_format: Format for table output ('json', 'markdown', or 'text')
        min_table_rows: Minimum rows to consider a table (default: 2)
        min_table_cols: Minimum columns to consider a table (default: 2)
        sandbox: Optional sandbox for resource-limited execution
    """
    
    def __init__(
        self,
        sandbox: Optional[Sandbox] = None,
        max_pages: Optional[int] = None,
        extract_tables: bool = True,
        table_format: str = 'json',
        min_table_rows: int = 2,
        min_table_cols: int = 2
    ):
        """
        Initialize the PDF parser.
        
        Args:
            sandbox: Optional Sandbox instance for resource-limited execution
            max_pages: Maximum number of pages to extract (None = all pages)
            extract_tables: Whether to detect and extract tables (default: True)
            table_format: Format for table output ('json', 'markdown', or 'text')
            min_table_rows: Minimum rows to consider a table (default: 2)
            min_table_cols: Minimum columns to consider a table (default: 2)
        """
        super().__init__(sandbox)
        self.max_pages = max_pages
        self.extract_tables = extract_tables
        self.table_format = table_format if table_format in ['json', 'markdown', 'text'] else 'json'
        self.min_table_rows = min_table_rows
        self.min_table_cols = min_table_cols
    
    def _is_encrypted(self, file_path: Path) -> bool:
        """
        Check if the PDF file is encrypted/password-protected.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            True if the file appears to be encrypted, False otherwise
        """
        try:
            # Try with PyPDF2 first
            import PyPDF2
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                if reader.is_encrypted:
                    return True
            
            # Try with pdfplumber as backup
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    if pdf.metadata and pdf.metadata.get('Encrypted', False):
                        return True
            except ImportError:
                pass
            
            return False
        
        except Exception as e:
            error_msg = str(e).lower()
            if 'encrypted' in error_msg or 'password' in error_msg:
                return True
            return False
    
    def _convert_table_to_format(self, table: List[List[str]], format_type: str) -> str:
        """
        Convert a table to the specified format.
        
        Args:
            table: List of rows, each row is list of cell values
            format_type: Output format ('json', 'markdown', or 'text')
            
        Returns:
            Formatted table string
        """
        if not table or len(table) < self.min_table_rows:
            return ""
        
        # Clean and normalize table data
        cleaned_table = []
        for row in table:
            cleaned_row = []
            for cell in row:
                if cell is None:
                    cleaned_row.append("")
                else:
                    # Clean cell text
                    cell_str = self.sanitize_output(str(cell).strip())
                    cleaned_row.append(cell_str)
            cleaned_table.append(cleaned_row)
        
        # Check if table has sufficient dimensions
        if len(cleaned_table) < self.min_table_rows:
            return ""
        
        max_cols = max(len(row) for row in cleaned_table) if cleaned_table else 0
        if max_cols < self.min_table_cols:
            return ""
        
        # Format according to requested format
        if format_type == 'json':
            return json.dumps(cleaned_table, ensure_ascii=False, indent=2)
        
        elif format_type == 'markdown':
            # Build markdown table
            if not cleaned_table:
                return ""
            
            # Header row
            header = cleaned_table[0]
            markdown_lines = []
            
            # Ensure all rows have same number of columns
            for row in cleaned_table:
                while len(row) < max_cols:
                    row.append("")
            
            # Create table
            markdown_lines.append("| " + " | ".join(str(cell) for cell in header) + " |")
            markdown_lines.append("|" + "|".join(["---" for _ in header]) + "|")
            
            for row in cleaned_table[1:]:
                markdown_lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
            
            return "\n".join(markdown_lines)
        
        else:  # text format
            # Build text table with column alignment
            if not cleaned_table:
                return ""
            
            # Calculate column widths
            col_widths = [0] * max_cols
            for row in cleaned_table:
                for i, cell in enumerate(row):
                    if i < len(col_widths):
                        col_widths[i] = max(col_widths[i], len(str(cell)))
            
            # Create separator
            separator = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
            
            # Build table
            lines = [separator]
            for row_idx, row in enumerate(cleaned_table):
                # Pad row to max columns
                while len(row) < max_cols:
                    row.append("")
                
                # Create formatted row
                formatted_cells = []
                for i, cell in enumerate(row):
                    formatted_cells.append(f" {str(cell):<{col_widths[i]}} ")
                lines.append("|" + "|".join(formatted_cells) + "|")
                lines.append(separator)
            
            return "\n".join(lines)
    
    def _extract_pdfplumber(self, pdf_path: Path) -> str:
        """
        Extract text from PDF using pdfplumber with table detection.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Extracted text with tables converted to specified format
        """
        import pdfplumber
        
        all_content = []
        page_metadata = []
        
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            pages_to_process = min(total_pages, self.max_pages) if self.max_pages else total_pages
            
            self.logger.debug(f"Processing {pages_to_process} of {total_pages} pages with pdfplumber")
            
            for page_num in range(pages_to_process):
                page = pdf.pages[page_num]
                page_content = []
                
                # Add page header
                page_header = f"[PAGE {page_num + 1}]"
                page_content.append(page_header)
                
                # Extract regular text
                text = page.extract_text()
                if text:
                    page_content.append(text.strip())
                
                # Extract tables if enabled
                if self.extract_tables:
                    tables = page.extract_tables()
                    
                    for table_idx, table in enumerate(tables):
                        if table and len(table) >= self.min_table_rows:
                            formatted_table = self._convert_table_to_format(table, self.table_format)
                            if formatted_table:
                                table_label = f"[TABLE {table_idx + 1}]"
                                page_content.append(table_label)
                                page_content.append(formatted_table)
                                self.logger.debug(f"Extracted table {table_idx + 1} from page {page_num + 1}")
                
                # Add page metadata
                page_meta = {
                    'page_num': page_num + 1,
                    'width': page.width,
                    'height': page.height,
                    'has_tables': len(tables) if self.extract_tables else 0
                }
                page_metadata.append(page_meta)
                
                # Combine page content
                all_content.append('\n'.join(page_content))
        
        # Add summary of extracted tables
        if self.extract_tables and page_metadata:
            tables_summary = []
            tables_summary.append("[PDF TABLE SUMMARY]")
            for meta in page_metadata:
                if meta['has_tables'] > 0:
                    tables_summary.append(f"  Page {meta['page_num']}: {meta['has_tables']} table(s)")
            
            if len(tables_summary) > 1:
                all_content.append('\n'.join(tables_summary))
        
        return '\n\n'.join(all_content)
    
    def _extract_pypdf2(self, pdf_path: Path) -> str:
        """
        Extract text from PDF using PyPDF2 (fallback, no table detection).
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Extracted text
        """
        import PyPDF2
        
        all_text = []
        
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            
            # Check if encrypted
            if reader.is_encrypted:
                raise EncryptedFileError(f"PDF is encrypted: {pdf_path}")
            
            total_pages = len(reader.pages)
            pages_to_process = min(total_pages, self.max_pages) if self.max_pages else total_pages
            
            self.logger.debug(f"Processing {pages_to_process} of {total_pages} pages with PyPDF2")
            
            for page_num in range(pages_to_process):
                page = reader.pages[page_num]
                text = page.extract_text()
                
                if text:
                    page_header = f"[PAGE {page_num + 1}]"
                    all_text.append(page_header)
                    all_text.append(text.strip())
                else:
                    all_text.append(f"[PAGE {page_num + 1}] (no extractable text)")
        
        return '\n\n'.join(all_text)
    
    def extract_text(self, file_path: Path) -> str:
        """
        Extract plain text from a PDF file.
        
        Uses pdfplumber as primary extractor (with table detection) and
        falls back to PyPDF2 if pdfplumber is not available or fails.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Extracted plain text content with tables converted to JSON
            
        Raises:
            ParserError: If parsing fails
            EncryptedFileError: If the file is encrypted/password-protected
            FileNotFoundError: If file does not exist
            PermissionError: If file cannot be read
        """
        # Validate input
        self.validate_input(file_path)
        
        # Check for .pdf extension
        if file_path.suffix.lower() != '.pdf':
            self.logger.warning(f"File {file_path} does not have .pdf extension")
        
        # Check if file is encrypted
        if self._is_encrypted(file_path):
            raise EncryptedFileError(
                f"File {file_path} appears to be encrypted or password-protected. "
                "This parser does not support encrypted PDF files."
            )
        
        self.logger.info(f"Extracting text from {file_path}")
        
        # Try pdfplumber first (preferred, has table detection)
        try:
            import pdfplumber
            self.logger.debug("Using pdfplumber for PDF extraction")
            text = self._extract_pdfplumber(file_path)
            
            # Sanitize output
            sanitized = self.sanitize_output(text)
            self.logger.debug(f"Extracted {len(sanitized)} characters using pdfplumber")
            return sanitized
        
        except ImportError:
            self.logger.info("pdfplumber not available, falling back to PyPDF2")
        
        except Exception as e:
            self.logger.warning(f"pdfplumber extraction failed: {e}, falling back to PyPDF2")
        
        # Fallback to PyPDF2
        try:
            import PyPDF2
            self.logger.debug("Using PyPDF2 for PDF extraction")
            text = self._extract_pypdf2(file_path)
            
            # Sanitize output
            sanitized = self.sanitize_output(text)
            self.logger.debug(f"Extracted {len(sanitized)} characters using PyPDF2")
            return sanitized
        
        except ImportError:
            raise ParserError(
                "Neither pdfplumber nor PyPDF2 is available. "
                "Please install pdfplumber or PyPDF2 for PDF support."
            )
        
        except Exception as e:
            raise ParserError(f"Failed to parse PDF file {file_path}: {e}")
    
    def get_metadata(self, file_path: Path) -> Dict[str, Any]:
        """
        Extract metadata from a PDF file.
        
        Extracts document info, page count, and table statistics when using pdfplumber.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Dictionary containing metadata key-value pairs
            
        Raises:
            ParserError: If metadata extraction fails
            FileNotFoundError: If file does not exist
        """
        # Validate input
        self.validate_input(file_path)
        
        self.logger.info(f"Extracting metadata from {file_path}")
        
        metadata = {
            'file_size_bytes': file_path.stat().st_size,
            'file_extension': file_path.suffix.lower(),
            'parser': None
        }
        
        # Try pdfplumber first for richer metadata
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                metadata['page_count'] = len(pdf.pages)
                metadata['parser'] = 'pdfplumber'
                
                # Extract document metadata
                if pdf.metadata:
                    doc_info = pdf.metadata
                    if 'Title' in doc_info and doc_info['Title']:
                        metadata['title'] = doc_info['Title']
                    if 'Author' in doc_info and doc_info['Author']:
                        metadata['author'] = doc_info['Author']
                    if 'Subject' in doc_info and doc_info['Subject']:
                        metadata['subject'] = doc_info['Subject']
                    if 'Keywords' in doc_info and doc_info['Keywords']:
                        metadata['keywords'] = doc_info['Keywords']
                    if 'Creator' in doc_info and doc_info['Creator']:
                        metadata['creator'] = doc_info['Creator']
                    if 'Producer' in doc_info and doc_info['Producer']:
                        metadata['producer'] = doc_info['Producer']
                    if 'CreationDate' in doc_info:
                        metadata['creation_date'] = doc_info['CreationDate']
                    if 'ModDate' in doc_info:
                        metadata['modification_date'] = doc_info['ModDate']
                
                # Count tables if extraction is enabled
                if self.extract_tables:
                    pages_to_check = min(len(pdf.pages), self.max_pages) if self.max_pages else len(pdf.pages)
                    total_tables = 0
                    pages_with_tables = 0
                    
                    for page_num in range(pages_to_check):
                        page = pdf.pages[page_num]
                        tables = page.extract_tables()
                        if tables:
                            total_tables += len(tables)
                            pages_with_tables += 1
                    
                    metadata['total_tables'] = total_tables
                    metadata['pages_with_tables'] = pages_with_tables
                    metadata['table_format'] = self.table_format if self.extract_tables else None
                
                # Pages processed based on limit
                metadata['pages_processed'] = min(len(pdf.pages), self.max_pages) if self.max_pages else len(pdf.pages)
                
                return metadata
        
        except ImportError:
            self.logger.debug("pdfplumber not available for metadata extraction")
        
        except Exception as e:
            self.logger.warning(f"pdfplumber metadata extraction failed: {e}")
        
        # Fallback to PyPDF2
        try:
            import PyPDF2
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                
                metadata['page_count'] = len(reader.pages)
                metadata['parser'] = 'PyPDF2'
                
                # Extract document info
                if reader.metadata:
                    doc_info = reader.metadata
                    if '/Title' in doc_info and doc_info['/Title']:
                        metadata['title'] = doc_info['/Title']
                    if '/Author' in doc_info and doc_info['/Author']:
                        metadata['author'] = doc_info['/Author']
                    if '/Subject' in doc_info and doc_info['/Subject']:
                        metadata['subject'] = doc_info['/Subject']
                    if '/Keywords' in doc_info and doc_info['/Keywords']:
                        metadata['keywords'] = doc_info['/Keywords']
                    if '/Creator' in doc_info and doc_info['/Creator']:
                        metadata['creator'] = doc_info['/Creator']
                    if '/Producer' in doc_info and doc_info['/Producer']:
                        metadata['producer'] = doc_info['/Producer']
                    if '/CreationDate' in doc_info:
                        metadata['creation_date'] = doc_info['/CreationDate']
                    if '/ModDate' in doc_info:
                        metadata['modification_date'] = doc_info['/ModDate']
                
                metadata['pages_processed'] = min(len(reader.pages), self.max_pages) if self.max_pages else len(reader.pages)
                
                return metadata
        
        except ImportError:
            raise ParserError("Neither pdfplumber nor PyPDF2 is available for metadata extraction")
        
        except Exception as e:
            raise ParserError(f"Failed to extract metadata from {file_path}: {e}")
    
    def supports_encryption(self) -> bool:
        """
        Check if parser supports encrypted files.
        
        Override from BaseParser. PDF files may be encrypted with password
        protection. Neither pdfplumber nor PyPDF2 can read encrypted PDFs
        without a password.
        
        Returns:
            False (encrypted PDF files are not supported)
        """
        return False
