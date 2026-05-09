"""
Security Validator Module

Provides functions for validating file security including header verification,
MIME type checking, macro detection, zip bomb detection, filename validation,
and embedded object detection.
"""

import magic
import zipfile
import olefile
from pathlib import Path
from typing import Dict, List, Optional
import re
from datetime import datetime


def validate_file_header(file_path: Path, expected_magic_bytes: Dict[str, bytes]) -> bool:
    """
    Check magic bytes match extension.
    
    Args:
        file_path: Path to the file to validate
        expected_magic_bytes: Dictionary mapping extensions to expected magic bytes
        
    Returns:
        True if the file's magic bytes match the expected pattern for its extension,
        False otherwise
    """
    if not file_path.exists() or not file_path.is_file():
        return False
    
    # Get file extension
    extension = file_path.suffix.lower()
    
    # Check if we have expected magic bytes for this extension
    if extension not in expected_magic_bytes:
        # No expectation for this extension, consider valid
        return True
    
    expected_bytes = expected_magic_bytes[extension]
    
    # Read the first few bytes of the file (enough to compare)
    try:
        with open(file_path, 'rb') as f:
            actual_bytes = f.read(len(expected_bytes))
        
        # Compare actual bytes with expected magic bytes
        return actual_bytes == expected_bytes
    
    except (IOError, OSError):
        return False


def check_mime_type(file_path: Path, allowed_types: List[str]) -> bool:
    """
    Verify MIME type using libmagic.
    
    Args:
        file_path: Path to the file to check
        allowed_types: List of allowed MIME types (e.g., ['application/pdf'])
        
    Returns:
        True if the file's MIME type is in the allowed list, False otherwise
    """
    if not file_path.exists() or not file_path.is_file():
        return False
    
    try:
        # Use python-magic to detect MIME type
        mime = magic.from_file(str(file_path), mime=True)
        
        # Check if the detected MIME type is allowed
        return mime in allowed_types
    
    except (magic.MagicException, IOError, OSError):
        # If magic detection fails, fall back to extension-based check
        # But this is less secure, so we return False for safety
        return False


def scan_for_macros(file_path: Path, file_format: str) -> bool:
    """
    Detect VBA macros in Office files.
    
    Args:
        file_path: Path to the Office file
        file_format: Format of the file ('doc', 'xls', 'ppt', or 'docx', 'xlsx', 'pptx')
        
    Returns:
        True if macros are found, False otherwise
    """
    if not file_path.exists() or not file_path.is_file():
        return False
    
    # For newer Office formats (docx, xlsx, pptx), check for vbaProject.bin
    if file_format in ['docx', 'xlsx', 'pptx']:
        try:
            import zipfile
            with zipfile.ZipFile(file_path, 'r') as zip_file:
                # Check for VBA project file
                for name in zip_file.namelist():
                    if 'vbaProject.bin' in name.lower():
                        return True
        except (zipfile.BadZipFile, IOError, OSError):
            pass
    
    # For legacy OLE formats (doc, xls, ppt)
    elif file_format in ['doc', 'xls', 'ppt']:
        try:
            ole = olefile.OleFileIO(str(file_path))
            
            # Check for VBA streams
            if ole.exists('Macros') or ole.exists('VBA') or ole.exists('_VBA_PROJECT_CUR'):
                ole.close()
                return True
            
            # Check for project streams that might contain macros
            if ole.exists('PROJECT') or ole.exists('PROJECTwm'):
                # Read project stream to check for macro indicators
                try:
                    project_data = ole.openstream('PROJECT').read().decode('utf-8', errors='ignore')
                    if 'VBA' in project_data or 'Module' in project_data:
                        ole.close()
                        return True
                except (IOError, OSError):
                    pass
            
            ole.close()
        
        except (olefile.OleFileIOError, IOError, OSError):
            pass
    
    return False


def detect_zip_bomb(file_path: Path, ratio_threshold: int = 100) -> bool:
    """
    Check if compressed file has unrealistic compression ratio.
    
    Args:
        file_path: Path to the zip file to check
        ratio_threshold: Threshold for suspicious compression ratio (default: 100)
        
    Returns:
        True if the file appears to be a zip bomb, False otherwise
    """
    if not file_path.exists() or not file_path.is_file():
        return False
    
    try:
        with zipfile.ZipFile(file_path, 'r') as zip_file:
            # Get compressed size and estimated uncompressed size
            compressed_size = 0
            uncompressed_size = 0
            
            for file_info in zip_file.infolist():
                compressed_size += file_info.compress_size
                uncompressed_size += file_info.file_size
            
            # Check for zip bomb indicators
            if compressed_size > 0 and uncompressed_size > 0:
                # Check compression ratio
                ratio = uncompressed_size / compressed_size
                if ratio > ratio_threshold:
                    return True
                
                # Check for exponential growth patterns (nested zip bombs)
                for file_info in zip_file.infolist():
                    if (file_info.file_size > 0 and 
                        file_info.compress_size < 100 and 
                        file_info.file_size > 1000000):
                        # Very small compressed size but large uncompressed size
                        return True
            
            return False
    
    except (zipfile.BadZipFile, IOError, OSError):
        return False


def validate_filename(filename: str) -> bool:
    """
    Reject path traversal chars (.., ./, null bytes).
    
    Args:
        filename: The filename to validate
        
    Returns:
        True if the filename is safe, False otherwise
    """
    # Check for null bytes
    if '\0' in filename:
        return False
    
    # Check for path traversal patterns
    dangerous_patterns = [
        r'\.\.[/\\]',  # Directory traversal (../ or ..\)
        r'\.\.$',      # Trailing ..
        r'^\.\.',      # Starting with ..
        r'[/\\]\.\.',  # /.. or \..
        r'\.\.\.',     # Triple dots
        r'~',          # Tilde (can be used in some path traversal)
        r'%2e%2e',     # URL encoded ..
        r'%2E%2E',     # URL encoded .. (uppercase)
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, filename, re.IGNORECASE):
            return False
    
    # Check for reserved characters in Windows/Linux
    reserved_chars = r'[<>:"|?*\\]'  # Reserved chars in Windows
    if re.search(reserved_chars, filename):
        # Allow forward slash? No, that's also dangerous
        return False
    
    # Check for leading/trailing dots or spaces
    if filename.startswith('.') or filename.startswith(' ') or filename.endswith(' ') or filename.endswith('.'):
        return False
    
    # Maximum reasonable filename length
    if len(filename) > 255:
        return False
    
    return True


def check_embedded_objects(file_path: Path) -> List[str]:
    """
    List potentially dangerous embedded objects (OLE, scripts).
    
    Args:
        file_path: Path to the file to check
        
    Returns:
        List of object types found (e.g., ['ole_object', 'javascript', 'vba_macro'])
    """
    found_objects = []
    
    if not file_path.exists() or not file_path.is_file():
        return found_objects
    
    # Check for OLE objects in various file formats
    try:
        # For OLE files (old Office, etc.)
        if olefile.isOleFile(str(file_path)):
            ole = olefile.OleFileIO(str(file_path))
            
            # Check for various OLE object types
            if ole.exists('ObjectPool') or ole.exists('Objects'):
                found_objects.append('ole_object')
            
            # Check for embedded packages
            if ole.exists('Package'):
                found_objects.append('embedded_package')
            
            # Check for linked objects
            if ole.exists('OLELinks'):
                found_objects.append('linked_object')
            
            # Check for macros (already covered, but add if found)
            if scan_for_macros(file_path, 'doc'):  # Use generic check
                if 'vba_macro' not in found_objects:
                    found_objects.append('vba_macro')
            
            ole.close()
        
        # For newer Office formats
        elif file_path.suffix.lower() in ['.docx', '.xlsx', '.pptx']:
            try:
                import zipfile
                with zipfile.ZipFile(file_path, 'r') as zip_file:
                    for name in zip_file.namelist():
                        # Check for embedded objects
                        if 'embeddings' in name.lower() or 'oleobject' in name.lower():
                            found_objects.append('embedded_object')
                        
                        # Check for ActiveX controls
                        if 'activex' in name.lower():
                            found_objects.append('activex_control')
                        
                        # Check for VBA
                        if 'vba' in name.lower():
                            if 'vba_macro' not in found_objects:
                                found_objects.append('vba_macro')
                        
                        # Check for external relationships
                        if name.endswith('.rels'):
                            try:
                                rels_data = zip_file.read(name).decode('utf-8', errors='ignore')
                                if 'External' in rels_data:
                                    found_objects.append('external_link')
                            except (KeyError, IOError):
                                pass
            
            except (zipfile.BadZipFile, IOError, OSError):
                pass
        
        # For PDF files
        elif file_path.suffix.lower() == '.pdf':
            try:
                import PyPDF2
                with open(file_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    
                    # Check for JavaScript
                    if reader.get('/Names') and reader.get('/JavaScript'):
                        found_objects.append('javascript')
                    
                    # Check for embedded files
                    if reader.get('/EmbeddedFiles'):
                        found_objects.append('embedded_file')
                    
                    # Check for Launch actions
                    for page_num, page in enumerate(reader.pages):
                        if page.get('/Annots'):
                            for annot in page.get('/Annots', []):
                                annot_obj = annot.get_object()
                                if annot_obj.get('/A') and annot_obj['/A'].get('/S') == '/Launch':
                                    found_objects.append('launch_action')
                                elif annot_obj.get('/A') and annot_obj['/A'].get('/S') == '/URI':
                                    found_objects.append('external_link')
            
            except (PyPDF2.PdfReadError, IOError, OSError):
                pass
        
        # For HTML/XML files
        elif file_path.suffix.lower() in ['.html', '.htm', '.xml']:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    # Check for scripts
                    if '<script' in content.lower():
                        found_objects.append('script')
                    
                    # Check for embedded objects
                    if '<object' in content.lower():
                        found_objects.append('html_object')
                    
                    # Check for embedded Flash
                    if '.swf' in content.lower() or 'application/x-shockwave-flash' in content.lower():
                        found_objects.append('flash_embed')
                    
                    # Check for iframes
                    if '<iframe' in content.lower():
                        found_objects.append('iframe')
            
            except (IOError, UnicodeDecodeError):
                pass
    
    except Exception:
        # Silently handle any unexpected errors
        pass
    
    # Remove duplicates while preserving order
    seen = set()
    unique_found = []
    for obj in found_objects:
        if obj not in seen:
            seen.add(obj)
            unique_found.append(obj)
    
    return unique_found
