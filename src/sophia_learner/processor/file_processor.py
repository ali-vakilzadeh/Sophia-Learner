"""
File Processor - Core orchestration for single file processing pipeline

This module implements the main processing logic that coordinates all components
of the Sophia Learner system to transform a document into AI training data.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from ..config.settings import Settings
from ..db.file_tracker import FileTracker
from ..db.version_tracker import VersionTracker
from ..db.models import FileRecord
from ..ai.base_client import AIClient
from ..output.writer import OutputWriter
from ..security.sandbox import Sandbox
from ..parser.base_parser import BaseParser
from ..parser.parser_registry import ParserRegistry
from .version_detector import detect_version, compare_versions
from .quarantine import Quarantine
from ..utils.hash_utils import compute_sha256
from ..utils.logger import get_logger, log_security_event

logger = get_logger(__name__)


class FileProcessor:
    """
    Orchestrates the complete document processing pipeline for a single file.
    
    This class coordinates:
    1. Security validation
    2. Version detection and conflict resolution
    3. Sandboxed text extraction via appropriate parser
    4. AI processing to generate training samples
    5. Output writing with proper formatting
    6. Database updates and file archiving
    """
    
    def __init__(
        self,
        config: Settings,
        db_tracker: FileTracker,
        version_tracker: VersionTracker,
        ai_client: AIClient,
        writer: OutputWriter,
        sandbox: Sandbox
    ):
        """
        Initialize the FileProcessor with all required dependencies.
        
        Args:
            config: System configuration
            db_tracker: Database operations for file records
            version_tracker: Version detection and conflict management
            ai_client: AI backend client for generating training samples
            writer: Output writer for persisting training data
            sandbox: Sandbox for secure resource-limited execution
        """
        self.config = config
        self.db_tracker = db_tracker
        self.version_tracker = version_tracker
        self.ai_client = ai_client
        self.writer = writer
        self.sandbox = sandbox
        self.parser_registry = ParserRegistry()
        
        # Initialize quarantine manager
        self.quarantine = Quarantine(config.security.quarantine_dir)
        
        # Configuration shortcuts
        self.max_retries = 3
        self.sandbox_timeout = config.security.max_extraction_time_seconds
        
    def process(self, file_path: Path, version: Optional[str] = None) -> bool:
        """
        Main entry point - process a single file through the complete pipeline.
        
        Args:
            file_path: Path to the file to process
            version: Optional version string (auto-detected if not provided)
            
        Returns:
            True if processing succeeded, False otherwise
        """
        logger.info(f"Starting processing for file: {file_path}")
        start_time = datetime.now()
        
        try:
            # Step 1: Validate file (security checks)
            is_valid, error_msg = self._validate(file_path)
            if not is_valid:
                logger.error(f"File validation failed for {file_path}: {error_msg}")
                log_security_event("validation_failed", file_path, {"error": error_msg})
                self._mark_failed(file_path, error_msg)
                return False
            
            # Step 2: Check if already processed (by SHA256)
            sha256_hash = compute_sha256(file_path)
            existing_file = self.db_tracker.get_file_by_sha256(sha256_hash)
            if existing_file and existing_file.status == "processed":
                logger.info(f"File already processed (duplicate): {file_path}")
                return True
            
            # Step 3: Detect or use provided version
            if version is None:
                version = detect_version(file_path)
            
            # Step 4: Check for version conflicts
            has_conflict = self._check_conflicts(file_path, version)
            if has_conflict:
                logger.warning(f"Version conflict detected for {file_path}")
                self._mark_conflict(file_path, version)
                return False
            
            # Step 5: Move to quarantine sandbox
            quarantine_path = self.quarantine.move_to_quarantine(
                file_path, "processing"
            )
            logger.debug(f"Moved file to quarantine: {quarantine_path}")
            
            # Step 6: Get appropriate parser
            parser = self.parser_registry.get_parser_for_file(quarantine_path)
            if parser is None:
                error_msg = f"No parser available for file: {quarantine_path}"
                logger.error(error_msg)
                self._mark_failed(file_path, error_msg)
                return False
            
            # Step 7: Extract text (within sandbox)
            extracted_text = self._extract(parser, quarantine_path)
            if not extracted_text:
                error_msg = "Text extraction failed or returned empty content"
                logger.error(error_msg)
                self._mark_failed(file_path, error_msg)
                return False
            
            # Step 8: Sanitize extracted content
            sanitized_text = parser.sanitize_output(extracted_text)
            logger.debug(f"Extracted {len(sanitized_text)} characters of text")
            
            # Step 9: Get metadata and send to AI
            metadata = parser.get_metadata(quarantine_path)
            metadata.update({
                "filename": file_path.name,
                "version": version,
                "file_size_bytes": file_path.stat().st_size,
                "sha256": sha256_hash
            })
            
            # Step 10: Generate training samples via AI
            samples = self._ai_process(self.ai_client, sanitized_text, metadata)
            if not samples:
                error_msg = "AI processing failed or returned no samples"
                logger.error(error_msg)
                self._mark_failed(file_path, error_msg)
                return False
            
            # Step 11: Write training data
            success = self._write_output(samples)
            if not success:
                error_msg = "Failed to write output samples"
                logger.error(error_msg)
                self._mark_failed(file_path, error_msg)
                return False
            
            # Step 12: Update database with success
            self._record_success(
                file_path, version, sha256_hash, sanitized_text, samples, metadata
            )
            
            # Step 13: Move to processed archive
            self.quarantine.mark_processed(quarantine_path)
            
            # Log success metrics
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(
                f"Successfully processed {file_path} in {duration:.2f}s, "
                f"generated {len(samples)} samples"
            )
            
            return True
            
        except Exception as e:
            logger.exception(f"Unexpected error processing {file_path}: {e}")
            self._mark_failed(file_path, str(e))
            return False
    
    def _validate(self, file_path: Path) -> Tuple[bool, str]:
        """
        Perform security validation on the file.
        
        Args:
            file_path: Path to file to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        from ..security.validator import (
            validate_filename,
            check_mime_type,
            scan_for_macros,
            detect_zip_bomb
        )
        from ..security.scanner import VirusScanner
        
        # Check if file exists and is readable
        if not file_path.exists():
            return False, f"File does not exist: {file_path}"
        
        if not file_path.is_file():
            return False, f"Path is not a file: {file_path}"
        
        # Validate filename (prevent path traversal)
        if not validate_filename(file_path.name):
            return False, f"Invalid filename: {file_path.name}"
        
        # Check file size
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        max_size_mb = self.config.security.max_file_size_mb
        if file_size_mb > max_size_mb:
            return False, f"File size {file_size_mb:.2f}MB exceeds limit {max_size_mb}MB"
        
        # Verify MIME type
        allowed_types = self.config.security.allowed_mime_types
        if allowed_types and not check_mime_type(file_path, allowed_types):
            return False, f"MIME type not in allowed list: {allowed_types}"
        
        # Check for zip bombs
        if detect_zip_bomb(file_path):
            return False, "File detected as potential zip bomb"
        
        # Check for macros (Office files)
        if self.config.security.strip_macros:
            ext = file_path.suffix.lower()
            if ext in ['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']:
                if scan_for_macros(file_path, ext[1:]):
                    return False, "Macros detected and stripping is enabled"
        
        # Optional virus scan
        if self.config.security.enable_virus_scan:
            scanner = VirusScanner(self.config.security.virus_scan_command)
            is_clean, message = scanner.scan_file(file_path)
            if not is_clean:
                # Move to quarantine
                self.quarantine.move_to_quarantine(file_path, "rejected")
                log_security_event("virus_detected", file_path, {"message": message})
                return False, f"Virus detected: {message}"
        
        return True, ""
    
    def _check_conflicts(self, file_path: Path, version: str) -> bool:
        """
        Check for version conflicts with existing files.
        
        Args:
            file_path: Path to the file
            version: Version string of this file
            
        Returns:
            True if conflict exists and requires manual resolution
        """
        # Get the base filename (without version)
        from .version_detector import get_base_filename
        
        base_path = get_base_filename(file_path)
        base_name = base_path.stem
        
        # Get all versions of this logical file
        version_records = self.version_tracker.get_version_chain(base_name)
        
        if not version_records:
            # No existing versions, register this one
            return False
        
        # Compare versions
        versions_list = [vr.version_number for vr in version_records]
        versions_list.append(version)
        
        # Check if this version already exists
        if version in versions_list[:-1]:  # exclude current
            logger.warning(f"Duplicate version {version} for {base_name}")
            return True
        
        # Sort versions and find latest
        from .version_detector import extract_version_number
        
        version_tuples = []
        for v in versions_list:
            try:
                version_tuples.append((v, extract_version_number(v)))
            except ValueError:
                # If version parsing fails, treat as string comparison
                version_tuples.append((v, (0,)))
        
        version_tuples.sort(key=lambda x: x[1])
        latest_version = version_tuples[-1][0]
        
        # If this isn't the latest version, check config
        if version != latest_version:
            resolution_mode = self.config.management.conflict_resolution
            if resolution_mode == "auto_keep_latest":
                logger.info(f"Auto-resolving: keeping latest version {latest_version}")
                return False
            else:
                # Create conflict record
                conflict_id = self.version_tracker.create_conflict(
                    base_name, versions_list
                )
                logger.warning(f"Created conflict {conflict_id} for {base_name}")
                return True
        
        # Register this version
        # (Find the parent version ID first - simplified for now)
        parent_id = None
        for vr in version_records:
            if vr.version_number == version:
                parent_id = vr.file_id
                break
        
        # Get file_id for parent (if we have it)
        file_record = self.db_tracker.get_file_by_path(file_path)
        if file_record:
            self.version_tracker.register_version(
                file_record.id, version, parent_id
            )
        
        return False
    
    def _extract(self, parser: BaseParser, file_path: Path) -> str:
        """
        Extract text from the file within a sandbox environment.
        
        Args:
            parser: Parser instance for the file type
            file_path: Path to the quarantined file
            
        Returns:
            Extracted and partially sanitized text
        """
        try:
            # Run extraction in sandbox with resource limits
            extracted_text = self.sandbox.run_in_sandbox(
                parser.extract_text,
                file_path,
                timeout=self.sandbox_timeout
            )
            
            # Basic validation of extracted content
            if not extracted_text or not isinstance(extracted_text, str):
                logger.warning(f"Extraction returned empty or invalid content")
                return ""
            
            # Trim if too large (prevent AI context overflow)
            max_chars = 100000  # ~25k tokens
            if len(extracted_text) > max_chars:
                logger.warning(f"Truncating extracted text from {len(extracted_text)} to {max_chars} chars")
                extracted_text = extracted_text[:max_chars]
            
            return extracted_text
            
        except Exception as e:
            logger.error(f"Sandbox extraction failed for {file_path}: {e}")
            return ""
    
    def _ai_process(
        self, 
        ai_client: AIClient, 
        text: str, 
        metadata: Dict
    ) -> List[Dict]:
        """
        Send extracted text to AI for training sample generation.
        
        The AI generates question-answer pairs, instructions, and other
        training data formats suitable for fine-tuning language models.
        
        Args:
            ai_client: AI backend client
            text: Extracted document text
            metadata: Document metadata (filename, type, etc.)
            
        Returns:
            List of training samples (each a dict matching output schema)
        """
        try:
            # Add document context to metadata
            context = {
                "document_type": metadata.get("mime_type", "unknown"),
                "filename": metadata.get("filename", "unknown"),
                "page_count": metadata.get("page_count", 0),
                "word_count": len(text.split())
            }
            metadata.update(context)
            
            # Call AI to generate training samples
            samples = ai_client.process_text(text, metadata)
            
            # Validate samples
            if not samples:
                logger.warning("AI processing returned no samples")
                return []
            
            if not isinstance(samples, list):
                logger.error(f"AI returned non-list result: {type(samples)}")
                return []
            
            # Apply any additional post-processing
            for sample in samples:
                # Ensure sample has required fields
                if "instruction" not in sample and "input" not in sample:
                    logger.warning(f"Sample missing instruction/input fields: {sample.keys()}")
                
                # Add provenance metadata
                sample["_source"] = metadata.get("filename", "unknown")
                sample["_processed_at"] = datetime.now().isoformat()
            
            logger.info(f"Generated {len(samples)} training samples from document")
            return samples
            
        except Exception as e:
            logger.error(f"AI processing failed: {e}")
            return []
    
    def _write_output(self, samples: List[Dict]) -> bool:
        """
        Write training samples to output files.
        
        Args:
            samples: List of training samples
            
        Returns:
            True if write succeeded, False otherwise
        """
        try:
            # Write samples in batch for efficiency
            written = self.writer.append_batch(samples)
            
            if written != len(samples):
                logger.warning(f"Only wrote {written} of {len(samples)} samples")
                return written > 0
            
            # Flush to ensure persistence
            self.writer.flush()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to write output samples: {e}")
            return False
    
    def _record_success(
        self,
        file_path: Path,
        version: Optional[str],
        sha256_hash: str,
        extracted_text: str,
        samples: List[Dict],
        metadata: Dict
    ):
        """
        Record successful processing in the database.
        
        Args:
            file_path: Original file path
            version: Detected or provided version
            sha256_hash: File hash for deduplication
            extracted_text: Extracted text content
            samples: Generated training samples
            metadata: Document metadata
        """
        # Create file record
        file_record = FileRecord(
            id=None,  # Will be assigned by DB
            path=file_path,
            filename=file_path.name,
            version=version,
            sha256=sha256_hash,
            size_bytes=file_path.stat().st_size,
            mime_type=metadata.get("mime_type", "unknown"),
            first_seen=datetime.now(),
            last_modified=datetime.fromtimestamp(file_path.stat().st_mtime),
            status="processed",
            assigned_priority=5  # Normal priority
        )
        
        # Add to database
        file_id = self.db_tracker.add_file(file_record)
        
        # Log processing details
        from ..db.models import ProcessingLog
        
        processing_log = ProcessingLog(
            id=None,
            file_id=file_id,
            status="success",
            stage="complete",
            message=f"Generated {len(samples)} training samples, "
                    f"text length: {len(extracted_text)} chars",
            created_at=datetime.now(),
            retry_count=0
        )
        
        # Record metrics (using direct SQL for simplicity)
        self._record_metrics(file_id, len(extracted_text), len(samples))
    
    def _record_metrics(self, file_id: int, text_length: int, sample_count: int):
        """
        Record processing metrics in the database.
        
        Args:
            file_id: Database ID of the processed file
            text_length: Length of extracted text
            sample_count: Number of training samples generated
        """
        try:
            # Simple metric recording - can be expanded
            query = """
                INSERT INTO processing_log (file_id, status, stage, message, created_at, retry_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """
            self.db_tracker._db.execute(
                query,
                (file_id, "success", "metrics", 
                 f"text_length={text_length}, samples={sample_count}",
                 datetime.now(), 0),
                commit=True
            )
        except Exception as e:
            logger.warning(f"Failed to record metrics: {e}")
    
    def _mark_failed(self, file_path: Path, error_message: str):
        """
        Mark a file as failed and update database.
        
        Args:
            file_path: Path to the failed file
            error_message: Description of the failure
        """
        try:
            # Try to get existing record
            existing = self.db_tracker.get_file_by_path(file_path)
            
            if existing:
                self.db_tracker.update_file_status(
                    existing.id, 
                    "failed", 
                    error_message
                )
                
                # Increment retry count
                self.db_tracker.increment_retry_count(existing.id)
            else:
                # Create failure record
                from ..db.models import FileRecord
                
                file_record = FileRecord(
                    id=None,
                    path=file_path,
                    filename=file_path.name,
                    version=None,
                    sha256=compute_sha256(file_path),
                    size_bytes=file_path.stat().st_size if file_path.exists() else 0,
                    mime_type="unknown",
                    first_seen=datetime.now(),
                    last_modified=datetime.now(),
                    status="failed",
                    assigned_priority=5
                )
                
                file_id = self.db_tracker.add_file(file_record)
                
                # Add error log
                from ..db.models import ProcessingLog
                error_log = ProcessingLog(
                    id=None,
                    file_id=file_id,
                    status="failed",
                    stage="validation",
                    message=error_message,
                    created_at=datetime.now(),
                    retry_count=1
                )
            
            # Move to rejected quarantine if file exists
            if file_path.exists():
                self.quarantine.mark_rejected(file_path, error_message)
                
        except Exception as e:
            logger.error(f"Failed to mark file as failed: {e}")
    
    def _mark_conflict(self, file_path: Path, version: str):
        """
        Mark a file as having version conflict.
        
        Args:
            file_path: Path to the conflicting file
            version: Detected version
        """
        try:
            # Create or update file record with conflict status
            existing = self.db_tracker.get_file_by_path(file_path)
            
            if existing:
                self.db_tracker.update_file_status(
                    existing.id, 
                    "conflicting", 
                    f"Version conflict with existing version {version}"
                )
            else:
                from ..db.models import FileRecord
                
                file_record = FileRecord(
                    id=None,
                    path=file_path,
                    filename=file_path.name,
                    version=version,
                    sha256=compute_sha256(file_path),
                    size_bytes=file_path.stat().st_size,
                    mime_type="unknown",
                    first_seen=datetime.now(),
                    last_modified=datetime.now(),
                    status="conflicting",
                    assigned_priority=3  # Lower priority for conflicting files
                )
                
                self.db_tracker.add_file(file_record)
            
            # Move to conflicts quarantine
            self.quarantine.move_to_quarantine(file_path, "conflicts")
            
        except Exception as e:
            logger.error(f"Failed to mark conflict for {file_path}: {e}")
