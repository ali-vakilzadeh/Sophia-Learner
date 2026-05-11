"""
Training Formatter - Format AI output to standard training data formats

This module provides utilities for formatting training samples into
standard formats like JSONL and JSON, with validation, metadata enrichment,
and deduplication capabilities.
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, List, TextIO, Optional, Any, Set, Tuple
from datetime import datetime
from collections import OrderedDict

from ..utils.logger import get_logger

logger = get_logger(__name__)


class TrainingFormatter:
    """
    Format AI output to standard training data formats.
    
    This class handles the conversion of training samples to JSONL and JSON
    formats, validates samples against a schema, enriches samples with metadata,
    and removes duplicate samples based on content hashing.
    
    Attributes:
        output_schema: JSON schema for validating samples
        required_fields: List of required field names from schema
        field_types: Dictionary mapping field names to expected types
    """
    
    def __init__(self, output_schema: Dict):
        """
        Initialize the training formatter with an output schema.
        
        Args:
            output_schema: JSON schema defining expected structure of samples
                         (e.g., {"required": ["type", "input", "output"], ...})
        """
        self.output_schema = output_schema
        
        # Extract required fields from schema
        self.required_fields = output_schema.get('required', [])
        
        # Extract field type information
        self.field_types = {}
        properties = output_schema.get('properties', {})
        for field_name, field_spec in properties.items():
            if isinstance(field_spec, dict):
                self.field_types[field_name] = field_spec.get('type')
        
        logger.debug(f"TrainingFormatter initialized with schema: required={self.required_fields}")
    
    def to_jsonl(self, samples: List[Dict], file_handle: TextIO) -> int:
        """
        Write samples to a file handle in JSONL format (one JSON object per line).
        
        Args:
            samples: List of training sample dictionaries
            file_handle: Open file handle (must be writable)
            
        Returns:
            Number of samples successfully written
        """
        if not samples:
            logger.warning("No samples to write")
            return 0
        
        written_count = 0
        
        for sample in samples:
            try:
                # Validate sample before writing
                if self.validate_sample(sample):
                    # Write as JSON line
                    json_line = json.dumps(sample, ensure_ascii=False)
                    file_handle.write(json_line + '\n')
                    written_count += 1
                else:
                    logger.warning(f"Skipping invalid sample: {sample.get('type', 'unknown')}")
            except Exception as e:
                logger.error(f"Failed to write sample to JSONL: {e}")
        
        # Flush to ensure data is written
        file_handle.flush()
        
        logger.info(f"Wrote {written_count} of {len(samples)} samples to JSONL")
        return written_count
    
    def to_json(self, samples: List[Dict], file_handle: TextIO, indent: int = 2) -> int:
        """
        Write samples to a file handle in JSON format (array of objects).
        
        Args:
            samples: List of training sample dictionaries
            file_handle: Open file handle (must be writable)
            indent: Number of spaces for indentation (0 for minified)
            
        Returns:
            Number of samples successfully written
        """
        if not samples:
            logger.warning("No samples to write")
            return 0
        
        # Filter valid samples
        valid_samples = [s for s in samples if self.validate_sample(s)]
        
        if not valid_samples:
            logger.warning("No valid samples to write")
            return 0
        
        try:
            # Write as JSON array
            json.dump(valid_samples, file_handle, indent=indent, ensure_ascii=False)
            file_handle.flush()
            
            logger.info(f"Wrote {len(valid_samples)} of {len(samples)} samples to JSON")
            return len(valid_samples)
            
        except Exception as e:
            logger.error(f"Failed to write samples to JSON: {e}")
            return 0
    
    def validate_sample(self, sample: Dict) -> bool:
        """
        Validate a single training sample against the output schema.
        
        Checks:
            - All required fields are present
            - Field types match expected types (if specified)
            - Enum constraints (if specified)
        
        Args:
            sample: Training sample dictionary to validate
            
        Returns:
            True if sample is valid, False otherwise
        """
        if not isinstance(sample, dict):
            logger.debug(f"Sample is not a dict: {type(sample)}")
            return False
        
        # Check required fields
        for field in self.required_fields:
            if field not in sample:
                logger.debug(f"Missing required field: {field}")
                return False
            
            if sample[field] is None:
                logger.debug(f"Required field is None: {field}")
                return False
        
        # Check field types
        properties = self.output_schema.get('properties', {})
        for field_name, field_value in sample.items():
            if field_name in properties:
                field_spec = properties[field_name]
                
                # Check type
                expected_type = field_spec.get('type')
                if expected_type and not self._check_type(field_value, expected_type):
                    logger.debug(f"Field '{field_name}' has wrong type. "
                               f"Expected {expected_type}, got {type(field_value).__name__}")
                    return False
                
                # Check enum values
                enum_values = field_spec.get('enum')
                if enum_values and field_value not in enum_values:
                    logger.debug(f"Field '{field_name}' value '{field_value}' "
                               f"not in enum {enum_values}")
                    return False
                
                # Check string length constraints
                if expected_type == 'string':
                    min_length = field_spec.get('minLength')
                    if min_length and len(field_value) < min_length:
                        logger.debug(f"Field '{field_name}' too short: {len(field_value)} < {min_length}")
                        return False
                    
                    max_length = field_spec.get('maxLength')
                    if max_length and len(field_value) > max_length:
                        logger.debug(f"Field '{field_name}' too long: {len(field_value)} > {max_length}")
                        return False
                
                # Check integer/number constraints
                if expected_type in ('integer', 'number'):
                    if isinstance(field_value, (int, float)):
                        minimum = field_spec.get('minimum')
                        if minimum is not None and field_value < minimum:
                            return False
                        
                        maximum = field_spec.get('maximum')
                        if maximum is not None and field_value > maximum:
                            return False
        
        return True
    
    def _check_type(self, value: Any, expected_type: str) -> bool:
        """
        Check if a value matches the expected JSON schema type.
        
        Args:
            value: Value to check
            expected_type: JSON schema type (string, integer, number, boolean, array, object)
            
        Returns:
            True if type matches, False otherwise
        """
        type_mapping = {
            'string': str,
            'integer': int,
            'number': (int, float),
            'boolean': bool,
            'array': list,
            'object': dict,
            'null': type(None)
        }
        
        if expected_type not in type_mapping:
            # Unknown type, accept by default
            return True
        
        expected = type_mapping[expected_type]
        
        if isinstance(expected, tuple):
            return isinstance(value, expected)
        else:
            return isinstance(value, expected)
    
    def add_metadata(self, sample: Dict, source_file: Path, timestamp: datetime) -> Dict:
        """
        Enrich a training sample with provenance metadata.
        
        Args:
            sample: Original training sample
            source_file: Path to the source document
            timestamp: When the sample was generated
            
        Returns:
            Sample enriched with metadata (creates a copy, does not modify original)
        """
        # Create a copy to avoid modifying the original
        enriched = sample.copy()
        
        # Add metadata field if it doesn't exist
        if '_metadata' not in enriched:
            enriched['_metadata'] = {}
        
        # Add provenance information
        enriched['_metadata'].update({
            'source_file': str(source_file),
            'source_filename': source_file.name,
            'source_stem': source_file.stem,
            'generated_at': timestamp.isoformat(),
            'generated_at_timestamp': int(timestamp.timestamp()),
            'formatter_version': '1.0'
        })
        
        # Add content hash for deduplication if not present
        if '_hash' not in enriched:
            enriched['_hash'] = self._compute_sample_hash(sample)
        
        return enriched
    
    def _compute_sample_hash(self, sample: Dict, fields_to_ignore: Optional[Set[str]] = None) -> str:
        """
        Compute a hash of a sample for deduplication purposes.
        
        Ignores metadata and timestamp fields by default to focus on content.
        
        Args:
            sample: Sample dictionary
            fields_to_ignore: Additional field names to ignore in hash calculation
            
        Returns:
            SHA256 hash as hex string
        """
        # Fields to exclude from hash (metadata and temporal data)
        ignore_fields = fields_to_ignore or {'_metadata', '_hash', 'timestamp', 'generated_at'}
        
        # Create a copy without ignored fields
        filtered_sample = {}
        for key, value in sample.items():
            if key not in ignore_fields:
                filtered_sample[key] = value
        
        # Sort keys for consistent ordering
        sorted_sample = OrderedDict(sorted(filtered_sample.items()))
        
        # Convert to JSON string and hash
        json_str = json.dumps(sorted_sample, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode('utf-8')).hexdigest()
    
    def deduplicate_samples(self, samples: List[Dict]) -> List[Dict]:
        """
        Remove duplicate samples based on content hashing.
        
        Two samples are considered duplicates if they have the same
        meaningful content (ignoring metadata and timestamps).
        
        Args:
            samples: List of training samples
            
        Returns:
            List of unique samples (first occurrence kept)
        """
        if not samples:
            return []
        
        seen_hashes = set()
        unique_samples = []
        duplicate_count = 0
        
        for sample in samples:
            # Compute content hash (ignoring metadata)
            sample_hash = self._compute_sample_hash(sample)
            
            if sample_hash not in seen_hashes:
                seen_hashes.add(sample_hash)
                unique_samples.append(sample)
            else:
                duplicate_count += 1
                logger.debug(f"Duplicate sample detected and removed: {sample.get('type', 'unknown')}")
        
        if duplicate_count > 0:
            logger.info(f"Removed {duplicate_count} duplicate samples, kept {len(unique_samples)}")
        
        return unique_samples
    
    def deduplicate_by_field(self, samples: List[Dict], field: str) -> List[Dict]:
        """
        Remove duplicate samples based on a specific field value.
        
        Args:
            samples: List of training samples
            field: Field name to use for deduplication (e.g., 'input')
            
        Returns:
            List of samples with unique values for the specified field
        """
        if not samples:
            return []
        
        seen_values = set()
        unique_samples = []
        duplicate_count = 0
        
        for sample in samples:
            value = sample.get(field)
            if value is not None:
                # Create hash of the field value
                value_hash = hashlib.md5(str(value).encode('utf-8')).hexdigest()
                
                if value_hash not in seen_values:
                    seen_values.add(value_hash)
                    unique_samples.append(sample)
                else:
                    duplicate_count += 1
            else:
                # Keep samples without the field
                unique_samples.append(sample)
        
        if duplicate_count > 0:
            logger.info(f"Removed {duplicate_count} duplicates by field '{field}'")
        
        return unique_samples
    
    def filter_by_type(self, samples: List[Dict], sample_types: List[str]) -> List[Dict]:
        """
        Filter samples by their type field.
        
        Args:
            samples: List of training samples
            sample_types: List of allowed sample types (e.g., ['qa', 'instruction'])
            
        Returns:
            Filtered list of samples
        """
        if not samples or not sample_types:
            return samples
        
        filtered = [s for s in samples if s.get('type') in sample_types]
        
        removed = len(samples) - len(filtered)
        if removed > 0:
            logger.debug(f"Filtered out {removed} samples by type (kept {sample_types})")
        
        return filtered
    
    def filter_by_difficulty(self, samples: List[Dict], min_difficulty: str = "easy", 
                            max_difficulty: str = "hard") -> List[Dict]:
        """
        Filter samples by difficulty level.
        
        Difficulty order: easy < medium < hard
        
        Args:
            samples: List of training samples
            min_difficulty: Minimum difficulty level
            max_difficulty: Maximum difficulty level
            
        Returns:
            Filtered list of samples
        """
        difficulty_order = {'easy': 0, 'medium': 1, 'hard': 2}
        
        min_val = difficulty_order.get(min_difficulty, 0)
        max_val = difficulty_order.get(max_difficulty, 2)
        
        filtered = []
        for sample in samples:
            difficulty = sample.get('difficulty', 'medium')
            diff_val = difficulty_order.get(difficulty, 1)
            
            if min_val <= diff_val <= max_val:
                filtered.append(sample)
        
        return filtered
    
    def normalize_sample(self, sample: Dict, default_values: Optional[Dict] = None) -> Dict:
        """
        Normalize a sample by ensuring all required fields exist with defaults.
        
        Args:
            sample: Training sample to normalize
            default_values: Optional default values for missing fields
            
        Returns:
            Normalized sample
        """
        normalized = sample.copy()
        
        # Add default values for required fields if missing
        for field in self.required_fields:
            if field not in normalized:
                if default_values and field in default_values:
                    normalized[field] = default_values[field]
                else:
                    # Provide sensible defaults
                    if field == 'type':
                        normalized[field] = 'unknown'
                    elif field == 'difficulty':
                        normalized[field] = 'medium'
                    else:
                        normalized[field] = ''
        
        return normalized
    
    def batch_validate(self, samples: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Validate a batch of samples and separate valid from invalid.
        
        Args:
            samples: List of training samples
            
        Returns:
            Tuple of (valid_samples, invalid_samples)
        """
        valid = []
        invalid = []
        
        for sample in samples:
            if self.validate_sample(sample):
                valid.append(sample)
            else:
                invalid.append(sample)
        
        if invalid:
            logger.warning(f"Found {len(invalid)} invalid samples out of {len(samples)}")
        
        return valid, invalid
    
    def format_batch(self, samples: List[Dict], format_type: str = "jsonl") -> str:
        """
        Format a batch of samples as a string (useful for testing or APIs).
        
        Args:
            samples: List of training samples
            format_type: Either "jsonl" or "json"
            
        Returns:
            Formatted string representation
        """
        import io
        
        output = io.StringIO()
        
        if format_type == "jsonl":
            self.to_jsonl(samples, output)
        elif format_type == "json":
            self.to_json(samples, output, indent=2)
        else:
            raise ValueError(f"Unknown format type: {format_type}")
        
        return output.getvalue()
    
    def get_statistics(self, samples: List[Dict]) -> Dict:
        """
        Get statistics about a collection of samples.
        
        Args:
            samples: List of training samples
            
        Returns:
            Dictionary with statistics (counts by type, difficulty, etc.)
        """
        if not samples:
            return {"total": 0}
        
        stats = {
            "total": len(samples),
            "by_type": {},
            "by_difficulty": {},
            "avg_input_length": 0,
            "avg_output_length": 0,
            "unique_samples": len(self.deduplicate_samples(samples))
        }
        
        total_input_len = 0
        total_output_len = 0
        
        for sample in samples:
            # Count by type
            sample_type = sample.get('type', 'unknown')
            stats["by_type"][sample_type] = stats["by_type"].get(sample_type, 0) + 1
            
            # Count by difficulty
            difficulty = sample.get('difficulty', 'unknown')
            stats["by_difficulty"][difficulty] = stats["by_difficulty"].get(difficulty, 0) + 1
            
            # Calculate lengths
            total_input_len += len(str(sample.get('input', '')))
            total_output_len += len(str(sample.get('output', '')))
        
        if samples:
            stats["avg_input_length"] = total_input_len / len(samples)
            stats["avg_output_length"] = total_output_len / len(samples)
        
        return stats
    
    def __repr__(self) -> str:
        """String representation."""
        return f"TrainingFormatter(required_fields={self.required_fields})"
