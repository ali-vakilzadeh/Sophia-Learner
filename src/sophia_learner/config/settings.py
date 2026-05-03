"""
Configuration loading and management for Sophia Learner.

This module provides the Settings dataclass and its nested configuration
dataclasses, along with functions to load, validate, and access the
configuration in a singleton pattern.

The configuration is loaded from a YAML file, validated against a schema
using Pydantic, and then mapped to the corresponding dataclasses.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import ValidationError

# Import the validation function from the schema module
from sophia_learner.config.schema import validate_config


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""
    pass


# Singleton holder for the configuration instance
_CONFIG_INSTANCE: Optional["Settings"] = None


@dataclass
class WatcherConfig:
    """Configuration for directory watching and debouncing."""
    watch_folders: List[Path]
    file_extensions: List[str]
    hold_hours: int
    backfill_on_startup: bool


@dataclass
class SchedulerConfig:
    """Configuration for processing windows and rate limiting."""
    processing_window: Dict[str, str]  # e.g., {"start": "17:00", "end": "07:00"}
    timezone: str
    delay_between_files_seconds: int
    max_files_per_batch: int


@dataclass
class SecurityConfig:
    """Configuration for security, sandboxing, and virus scanning."""
    sandbox_mode: bool
    max_file_size_mb: int
    max_extraction_time_seconds: int
    enable_virus_scan: bool
    virus_scan_command: str
    quarantine_dir: Path
    strip_macros: bool
    allowed_mime_types: List[str]


@dataclass
class AIConfig:
    """Configuration for the AI backend (Ollama or Transformers)."""
    backend: Literal["ollama", "transformers"]
    ollama: Optional[Dict]  # Ollama-specific settings (model, url, etc.)
    transformers: Optional[Dict]  # Transformers-specific settings
    prompt_template: Path
    output_schema: Dict  # Expected JSON schema for training samples


@dataclass
class OutputConfig:
    """Configuration for writing training data to disk."""
    folder: Path
    format: Literal["jsonl", "json"]
    max_file_size_mb: int
    rotate_daily: bool
    compress_archive: bool


@dataclass
class DatabaseConfig:
    """Configuration for the SQLite database."""
    path: Path
    backup_interval_hours: int
    vacuum_on_startup: bool


@dataclass
class LoggingConfig:
    """Configuration for logging (levels, files, rotation)."""
    level: str
    log_dir: Path
    max_log_size_mb: int
    backup_count: int
    json_format: bool


@dataclass
class ManagementConfig:
    """Configuration for conflict resolution and management app."""
    conflict_resolution: Literal["manual", "auto_keep_latest"]
    management_app_host: str
    management_app_port: int
    notification_command: Optional[str]


@dataclass
class Settings:
    """Top-level configuration container."""
    watcher: WatcherConfig
    scheduler: SchedulerConfig
    security: SecurityConfig
    ai: AIConfig
    output: OutputConfig
    database: DatabaseConfig
    logging: LoggingConfig
    management: ManagementConfig


def load_config(config_path: Optional[Path] = None) -> Settings:
    """
    Load, validate, and return configuration.

    Args:
        config_path: Optional custom path to the YAML config file.
                     Defaults to "./config/config.yaml".

    Returns:
        Validated Settings instance.

    Raises:
        ConfigError: If the config file does not exist, is invalid YAML,
                     or fails Pydantic validation.
    """
    if config_path is None:
        config_path = Path("./config/config.yaml")

    # Resolve to absolute path for clearer error messages
    config_path = config_path.resolve()

    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}") from e

    # Validate the raw dictionary using Pydantic schema
    try:
        validated_dict = validate_config(raw_config)
    except ValidationError as e:
        raise ConfigError(f"Configuration validation failed: {e}") from e

    # Build nested dataclasses from the validated dictionary
    try:
        watcher = WatcherConfig(**validated_dict["watcher"])
        scheduler = SchedulerConfig(**validated_dict["scheduler"])
        security = SecurityConfig(**validated_dict["security"])
        ai = AIConfig(**validated_dict["ai"])
        output = OutputConfig(**validated_dict["output"])
        database = DatabaseConfig(**validated_dict["database"])
        logging = LoggingConfig(**validated_dict["logging"])
        management = ManagementConfig(**validated_dict["management"])

        settings = Settings(
            watcher=watcher,
            scheduler=scheduler,
            security=security,
            ai=ai,
            output=output,
            database=database,
            logging=logging,
            management=management,
        )
    except KeyError as e:
        raise ConfigError(f"Missing required configuration section: {e}") from e
    except TypeError as e:
        raise ConfigError(f"Error mapping configuration to dataclasses: {e}") from e

    return settings


def get_config() -> Settings:
    """
    Singleton accessor for the configuration.

    Returns the existing config instance if already loaded, otherwise loads
    the default configuration.

    Returns:
        Settings instance (validated).

    """
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is None:
        _CONFIG_INSTANCE = load_config()
    return _CONFIG_INSTANCE


def reload_config() -> Settings:
    """
    Force reload the configuration from disk.

    Updates the global singleton instance and returns the fresh configuration.

    Returns:
        Freshly loaded Settings instance.

    """
    global _CONFIG_INSTANCE
    _CONFIG_INSTANCE = load_config()
    return _CONFIG_INSTANCE
