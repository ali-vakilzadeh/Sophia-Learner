"""
XLS Parser Module

Provides parser for legacy Microsoft Excel .xls files using xlrd library
for text extraction and metadata retrieval.
"""

from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

import xlrd
from xlrd import XLRDError

from .base_parser import BaseParser, ParserError, EncryptedFileError
from ..security.sandbox import Sandbox


class XlsParser(BaseParser):
    """
    Parser for legacy Microsoft Excel .xls files.
    
    Uses xlrd library to extract text content from worksheets, including
    cell values converted to strings. Provides metadata about workbook
    structure including sheet names, row counts, and column counts.
    
    Security note: formatting_info=False is used to disable BIFF (Binary
    Interchange File Format) parsing which can be a security risk.
    
    Attributes:
        on_demand: Whether to load sheets on demand (memory efficient)
        formatting_info: Whether to load formatting info (disabled for security)
        sandbox: Optional sandbox for resource-limited execution
    """
    
    def __init__(
        self, 
        sandbox: Optional[Sandbox] = None,
        on_demand: bool = True,
        max_sheet_size_rows: int = 100000  # Safety limit for large sheets
    ):
        """
        Initialize the XLS parser.
        
        Args:
            sandbox: Optional Sandbox instance for resource-limited execution
            on_demand: Whether to load sheets on demand (default: True)
            max_sheet_size_rows: Maximum rows to process per sheet (safety limit)
        """
        super().__init__(sandbox)
        self.on_demand = on_demand
        self.max_sheet_size_rows = max_sheet_size_rows
        
        # formatting_info is forced to False for security
        self.formatting_info = False
    
    def _is_encrypted(self, file_path: Path) -> bool:
        """
        Check if the .xls file is encrypted/password-protected.
        
        Args:
            file_path: Path to the .xls file
            
        Returns:
            True if the file appears to be encrypted, False otherwise
        """
        try:
            # Try to open the workbook - xlrd will raise error if encrypted
            workbook = xlrd.open_workbook(
                str(file_path),
                formatting_info=self.formatting_info,
                on_demand=self.on_demand
            )
            # Check if workbook is encrypted
            if hasattr(workbook, 'encryption') and workbook.encryption:
                return True
            return False
        except XLRDError as e:
            error_msg = str(e).lower()
            if 'encrypted' in error_msg or 'password' in error_msg:
                return True
            return False
        except Exception:
            return False
    
    def _cell_to_string(self, cell) -> str:
        """
        Convert an xlrd cell to a string representation.
        
        Handles different cell types:
        - Empty cells: return empty string
        - Text cells: return value as is
        - Number cells: convert to string (preserves formatting where possible)
        - Date cells: convert to ISO format
        - Boolean cells: return 'True' or 'False'
        - Error cells: return error message
        
        Args:
            cell: xlrd Cell object
            
        Returns:
            String representation of the cell value
        """
        if cell is None:
            return ""
        
        # Get cell value based on type
        cell_type = cell.ctype
        
        try:
            # Empty cell
            if cell_type == xlrd.XL_CELL_EMPTY:
                return ""
            
            # Text cell
            elif cell_type == xlrd.XL_CELL_TEXT:
                value = cell.value
                if value is None:
                    return ""
                # Clean up whitespace and ensure string
                return str(value).strip()
            
            # Number cell
            elif cell_type == xlrd.XL_CELL_NUMBER:
                value = cell.value
                if value is None:
                    return ""
                
                # Check if it's a date (xlrd can detect dates)
                try:
                    if hasattr(cell, 'value') and hasattr(cell, 'ctype'):
                        # Try to convert to datetime if it's a date
                        if cell.ctype == xlrd.XL_CELL_DATE:
                            # Convert Excel date to datetime
                            date_tuple = xlrd.xldate_as_tuple(cell.value, 0)  # 0 = book.datemode
                            if date_tuple and len(date_tuple) >= 3:
                                # Check if it's just a time (year=0)
                                if date_tuple[0] == 0:
                                    # Time only
                                    if date_tuple[3] == 0 and date_tuple[4] == 0 and date_tuple[5] == 0:
                                        return "0"
                                    return f"{date_tuple[3]:02d}:{date_tuple[4]:02d}:{date_tuple[5]:02d}"
                                else:
                                    # Full date
                                    dt = datetime(*date_tuple[:6])
                                    return dt.isoformat()
                except Exception:
                    # Fall back to simple number
                    pass
                
                # Format number to avoid scientific notation for integers
                if isinstance(value, float) and value.is_integer():
                    return str(int(value))
                else:
                    return str(value)
            
            # Boolean cell
            elif cell_type == xlrd.XL_CELL_BOOLEAN:
                return "True" if cell.value else "False"
            
            # Error cell
            elif cell_type == xlrd.XL_CELL_ERROR:
                error_codes = {
                    0x00: "#NULL!",
                    0x07: "#DIV/0!",
                    0x0F: "#VALUE!",
                    0x17: "#REF!",
                    0x1D: "#NAME?",
                    0x24: "#NUM!",
                    0x2A: "#N/A",
                }
                error_code = cell.value
                return error_codes.get(error_code, f"#ERROR_{error_code}")
            
            # Blank cell (empty but with formatting)
            elif cell_type == xlrd.XL_CELL_BLANK:
                return ""
            
            else:
                # Unknown cell type
                return str(cell.value) if cell.value is not None else ""
        
        except Exception as e:
            # If any error occurs during conversion, return empty string
            self.logger.debug(f"Error converting cell to string: {e}")
            return ""
    
    def _extract_sheet_text(self, workbook, sheet_index: int) -> str:
        """
        Extract text from a specific worksheet.
        
        Args:
            workbook: xlrd Workbook object
            sheet_index: Index of the sheet to extract
            
        Returns:
            String containing all text from the sheet with row/column structure
        """
        try:
            # Get the sheet
            sheet = workbook.sheet_by_index(sheet_index)
            
            if sheet is None:
                return ""
            
            sheet_name = sheet.name
            rows_data = []
            
            # Determine number of rows and columns
            num_rows = min(sheet.nrows, self.max_sheet_size_rows)
            num_cols = sheet.ncols
            
            # Process each row
            for row_idx in range(num_rows):
                row_cells = []
                
                # Process each column in the row
                for col_idx in range(num_cols):
                    cell = sheet.cell(row_idx, col_idx)
                    cell_value = self._cell_to_string(cell)
                    
                    # Only include non-empty cells to reduce noise
                    if cell_value and cell_value.strip():
                        row_cells.append(cell_value)
                
                # If row has content, add it
                if row_cells:
                    # Use tabs to separate columns (maintains table structure)
                    rows_data.append('\t'.join(row_cells))
            
            # If we have data, add sheet header and content
            if rows_data:
                sheet_header = f"[SHEET: {sheet_name}]"
                sheet_content = '\n'.join(rows_data)
                return f"{sheet_header}\n{sheet_content}"
            else:
                return f"[SHEET: {sheet_name}] (empty)"
        
        except Exception as e:
            self.logger.warning(f"Error extracting text from sheet {sheet_index}: {e}")
            return f"[SHEET {sheet_index}] (error extracting: {e})"
    
    def extract_text(self, file_path: Path) -> str:
        """
        Extract plain text from a .xls file.
        
        Processes each worksheet in the workbook, extracting cell values
        and formatting them to preserve tabular structure.
        
        Args:
            file_path: Path to the .xls file
            
        Returns:
            Extracted plain text content with sheet structure preserved
            
        Raises:
            ParserError: If parsing fails
            EncryptedFileError: If the file is encrypted/password-protected
            FileNotFoundError: If file does not exist
            PermissionError: If file cannot be read
        """
        # Validate input
        self.validate_input(file_path)
        
        # Check for .xls extension
        if file_path.suffix.lower() not in ['.xls']:
            self.logger.warning(f"File {file_path} does not have .xls extension")
        
        # Check if file is encrypted
        if self._is_encrypted(file_path):
            raise EncryptedFileError(
                f"File {file_path} appears to be encrypted or password-protected. "
                "This parser does not support encrypted .xls files."
            )
        
        self.logger.info(f"Extracting text from {file_path}")
        
        try:
            # Open the workbook with security settings
            # formatting_info=False is critical for security (disables BIFF parsing)
            workbook = xlrd.open_workbook(
                str(file_path),
                formatting_info=self.formatting_info,  # False = secure
                on_demand=self.on_demand,
                logfile=None  # Disable logging to avoid console spam
            )
            
            # Extract text from all sheets
            sheet_texts = []
            num_sheets = workbook.nsheets
            
            self.logger.debug(f"Workbook has {num_sheets} sheets")
            
            for sheet_idx in range(num_sheets):
                self.logger.debug(f"Processing sheet {sheet_idx + 1}/{num_sheets}")
                sheet_text = self._extract_sheet_text(workbook, sheet_idx)
                if sheet_text:
                    sheet_texts.append(sheet_text)
            
            # Combine all sheets with double newlines
            full_text = '\n\n'.join(sheet_texts)
            
            # Sanitize output
            sanitized = self.sanitize_output(full_text)
            
            self.logger.debug(f"Extracted {len(sanitized)} characters from {file_path}")
            return sanitized
        
        except XLRDError as e:
            error_msg = str(e).lower()
            if 'encrypted' in error_msg or 'password' in error_msg:
                raise EncryptedFileError(f"File is encrypted: {file_path}")
            else:
                raise ParserError(f"Failed to parse .xls file: {e}")
        except Exception as e:
            raise ParserError(f"Failed to parse .xls file {file_path}: {e}")
    
    def get_metadata(self, file_path: Path) -> Dict[str, Any]:
        """
        Extract metadata from a .xls file.
        
        Extracts workbook information including sheet names, sheet dimensions,
        and file statistics.
        
        Args:
            file_path: Path to the .xls file
            
        Returns:
            Dictionary containing metadata key-value pairs
            
        Raises:
            ParserError: If metadata extraction fails
            FileNotFoundError: If file does not exist
        """
        # Validate input
        self.validate_input(file_path)
        
        self.logger.info(f"Extracting metadata from {file_path}")
        
        try:
            # Open the workbook (read-only, no formatting)
            workbook = xlrd.open_workbook(
                str(file_path),
                formatting_info=self.formatting_info,
                on_demand=self.on_demand,
                logfile=None
            )
            
            metadata = {}
            
            # Extract sheet information
            sheets_info = []
            total_rows = 0
            total_cols = 0
            total_cells = 0
            
            for sheet_idx in range(workbook.nsheets):
                try:
                    sheet = workbook.sheet_by_index(sheet_idx)
                    sheet_info = {
                        'name': sheet.name,
                        'index': sheet_idx,
                        'num_rows': min(sheet.nrows, self.max_sheet_size_rows),
                        'num_cols': sheet.ncols,
                        'estimated_cells': min(sheet.nrows, self.max_sheet_size_rows) * sheet.ncols
                    }
                    
                    # Count visible rows (those with content)
                    visible_rows = 0
                    for row_idx in range(min(sheet.nrows, self.max_sheet_size_rows)):
                        row_has_content = False
                        for col_idx in range(sheet.ncols):
                            cell = sheet.cell(row_idx, col_idx)
                            if cell.ctype != xlrd.XL_CELL_EMPTY and cell.ctype != xlrd.XL_CELL_BLANK:
                                row_has_content = True
                                break
                        if row_has_content:
                            visible_rows += 1
                    
                    sheet_info['visible_rows'] = visible_rows
                    sheets_info.append(sheet_info)
                    
                    total_rows += sheet_info['num_rows']
                    total_cols = max(total_cols, sheet_info['num_cols'])
                    total_cells += sheet_info['estimated_cells']
                
                except Exception as e:
                    self.logger.warning(f"Error processing sheet {sheet_idx}: {e}")
                    sheets_info.append({
                        'name': f"Sheet{sheet_idx + 1}",
                        'index': sheet_idx,
                        'error': str(e)
                    })
            
            metadata['sheets'] = sheets_info
            metadata['sheet_count'] = workbook.nsheets
            metadata['total_rows'] = total_rows
            metadata['max_columns'] = total_cols
            metadata['estimated_cells'] = total_cells
            
            # Extract workbook properties if available
            if hasattr(workbook, 'props'):
                props = workbook.props
                if props:
                    if hasattr(props, 'title') and props.title:
                        metadata['title'] = props.title
                    if hasattr(props, 'subject') and props.subject:
                        metadata['subject'] = props.subject
                    if hasattr(props, 'author') and props.author:
                        metadata['author'] = props.author
                    if hasattr(props, 'keywords') and props.keywords:
                        metadata['keywords'] = props.keywords
                    if hasattr(props, 'comments') and props.comments:
                        metadata['comments'] = props.comments
                    if hasattr(props, 'last_author') and props.last_author:
                        metadata['last_author'] = props.last_author
            
            # Add file information
            metadata['file_size_bytes'] = file_path.stat().st_size
            metadata['file_extension'] = file_path.suffix.lower()
            metadata['parser'] = 'xlrd'
            metadata['formatting_info'] = self.formatting_info  # Should be False for security
            metadata['on_demand_loading'] = self.on_demand
            
            self.logger.debug(f"Extracted {len(metadata)} metadata fields")
            return metadata
        
        except XLRDError as e:
            error_msg = str(e).lower()
            if 'encrypted' in error_msg or 'password' in error_msg:
                raise EncryptedFileError(f"File is encrypted: {file_path}")
            else:
                raise ParserError(f"Failed to extract metadata from .xls file: {e}")
        except Exception as e:
            raise ParserError(f"Failed to extract metadata from {file_path}: {e}")
    
    def supports_encryption(self) -> bool:
        """
        Check if parser supports encrypted files.
        
        Override from BaseParser. .xls files may be encrypted with password
        protection. xlrd cannot read encrypted files.
        
        Returns:
            False (encrypted .xls files are not supported)
        """
        return False
