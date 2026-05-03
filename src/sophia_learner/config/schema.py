"""
Configuration schema validation for Sophia Learner.

This module provides Pydantic models for validating the YAML configuration
structure, along with helper functions to validate the configuration dictionary
and check AI backend availability.
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests
from pydantic import BaseModel, validator, ValidationError

# Configure a module-level logger
logger = logging.getLogger(__name__)


class WatcherSchema(BaseModel):
    """Schema for watcher configuration."""
    watch_folders: List[Path]
    file_extensions: List[str]
    hold_hours: int
    backfill_on_startup: bool

    @validator("watch_folders", each_item=True)
    def validate_watch_folder(cls, v: Path) -> Path:
        """Ensure the watch folder exists and is readable."""
        if not v.exists():
            raise ValueError(f"Watch folder does not exist: {v}")
        if not v.is_dir():
            raise ValueError(f"Watch folder is not a directory: {v}")
        if not os.access(v, os.R_OK):
            raise ValueError(f"Watch folder is not readable: {v}")
        return v


class SchedulerSchema(BaseModel):
    """Schema for scheduler configuration."""
    processing_window: Dict[str, str]  # e.g., {"start": "17:00", "end": "07:00"}
    timezone: str
    delay_between_files_seconds: int
    max_files_per_batch: int

    @validator("processing_window")
    def validate_time_window(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Ensure start and end times are in HH:MM format and not equal."""
        if "start" not in v or "end" not in v:
            raise ValueError("processing_window must contain 'start' and 'end' keys")

        start = v["start"]
        end = v["end"]

        # Validate HH:MM format
        for time_str in (start, end):
            if not isinstance(time_str, str):
                raise ValueError(f"Time must be a string, got {type(time_str)}")
            parts = time_str.split(":")
            if len(parts) != 2:
                raise ValueError(f"Time must be in HH:MM format: {time_str}")
            try:
                hour = int(parts[0])
                minute = int(parts[1])
                if not (0 <= hour <= 23) or not (0 <= minute <= 59):
                    raise ValueError(f"Invalid hour/minute: {time_str}")
            except ValueError:
                raise ValueError(f"Time components must be integers: {time_str}")

        if start == end:
            raise ValueError("Start time cannot equal end time in processing_window")

        return v


class SecuritySchema(BaseModel):
    """Schema for security configuration."""
    sandbox_mode: bool
    max_file_size_mb: int
    max_extraction_time_seconds: int
    enable_virus_scan: bool
    virus_scan_command: str
    quarantine_dir: Path
    strip_macros: bool
    allowed_mime_types: List[str]


class AISchema(BaseModel):
    """Schema for AI configuration."""
    backend: str  # Literal validated separately
    ollama: Optional[Dict[str, Any]] = None
    transformers: Optional[Dict[str, Any]] = None
    prompt_template: Path
    output_schema: Dict[str, Any]

    @validator("backend")
    def validate_backend(cls, v: str) -> str:
        """Ensure backend is one of the allowed values."""
        allowed = {"ollama", "transformers"}
        if v not in allowed:
            raise ValueError(f"backend must be one of {allowed}, got {v}")
        return v

    @validator("ollama", always=True)
    def check_ollama_config(cls, v: Optional[Dict], values: Dict[str, Any]) -> Optional[Dict]:
        """If backend='ollama', ensure ollama config is present and has required keys."""
        backend = values.get("backend")
        if backend == "ollama":
            if v is None:
                raise ValueError("When backend='ollama', 'ollama' configuration must be provided")
            if "model" not in v:
                raise ValueError("ollama config must contain 'model' key")
            # 'url' is optional (default http://localhost:11434)
        return v

    @validator("transformers", always=True)
    def check_transformers_config(cls, v: Optional[Dict], values: Dict[str, Any]) -> Optional[Dict]:
        """If backend='transformers', ensure transformers config is present and has required keys."""
        backend = values.get("backend")
        if backend == "transformers":
            if v is None:
                raise ValueError("When backend='transformers', 'transformers' configuration must be provided")
            if "model_name" not in v:
                raise ValueError("transformers config must contain 'model_name' key")
        return v


class OutputSchema(BaseModel):
    """Schema for output configuration."""
    folder: Path
    format: str  # Literal validated separately
    max_file_size_mb: int
    rotate_daily: bool
    compress_archive: bool

    @validator("format")
    def validate_format(cls, v: str) -> str:
        """Ensure format is 'jsonl' or 'json'."""
        allowed = {"jsonl", "json"}
        if v not in allowed:
            raise ValueError(f"format must be one of {allowed}, got {v}")
        return v


class DatabaseSchema(BaseModel):
    """Schema for database configuration."""
    path: Path
    backup_interval_hours: int
    vacuum_on_startup: bool


class LoggingSchema(BaseModel):
    """Schema for logging configuration."""
    level: str
    log_dir: Path
    max_log_size_mb: int
    backup_count: int
    json_format: bool


class ManagementSchema(BaseModel):
    """Schema for management configuration."""
    conflict_resolution: str  # Literal validated separately
    management_app_host: str
    management_app_port: int
    notification_command: Optional[str]

    @validator("conflict_resolution")
    def validate_conflict_resolution(cls, v: str) -> str:
        """Ensure conflict_resolution is 'manual' or 'auto_keep_latest'."""
        allowed = {"manual", "auto_keep_latest"}
        if v not in allowed:
            raise ValueError(f"conflict_resolution must be one of {allowed}, got {v}")
        return v


class ConfigSchema(BaseModel):
    """Root configuration schema."""
    watcher: WatcherSchema
    scheduler: SchedulerSchema
    security: SecuritySchema
    ai: AISchema
    output: OutputSchema
    database: DatabaseSchema
    logging: LoggingSchema
    management: ManagementSchema


def validate_config(config_dict: Dict) -> Dict:
    """
    Validate the raw configuration dictionary using Pydantic.

    Args:
        config_dict: Raw dictionary loaded from YAML.

    Returns:
        Validated dictionary (as Python dict, after conversion).

    Raises:
        ValidationError: If the configuration does not conform to the schema.
    """
    validated = ConfigSchema(**config_dict)
    # Use .dict() for Pydantic v1 compatibility; for v2, use .model_dump()
    return validated.dict()


def validate_ai_backend(backend_config: Dict) -> bool:
    """
    Check if the selected AI backend is available.

    For 'ollama', attempts to connect to the Ollama API at the configured URL
    (default http://localhost:11434) and verifies the model exists.
    For 'transformers', attempts to import torch and transformers.

    Args:
        backend_config: AI configuration dictionary (contains 'backend' and
                        backend-specific settings like 'ollama' or 'transformers').

    Returns:
        True if the backend is available, False otherwise (logs a warning).
    """
    backend = backend_config.get("backend")
    if backend == "ollama":
        url = backend_config.get("ollama", {}).get("url", "http://localhost:11434")
        model = backend_config.get("ollama", {}).get("model")
        try:
            # Check if Ollama is reachable
            resp = requests.get(f"{url}/api/tags", timeout=5)
            if resp.status_code != 200:
                logger.warning(f"Ollama API returned status {resp.status_code}")
                return False
            # Check if the required model is available
            models = resp.json().get("models", [])
            model_names = [m.get("name") for m in models]
            if model not in model_names:
                logger.warning(f"Ollama model '{model}' not found. Available: {model_names}")
                return False
            return True
        except Exception as e:
            logger.warning(f"Ollama connection failed: {e}")
            return False

    elif backend == "transformers":
        try:
            import torch
            import transformers
            # Optional: check if CUDA is available but not required
            logger.info(f"Transformers available, torch version {torch.__version__}")
            return True
        except ImportError as e:
            logger.warning(f"Transformers backend not available: missing dependency - {e}")
            return False
    else:
        logger.warning(f"Unknown backend '{backend}'")
        return False
