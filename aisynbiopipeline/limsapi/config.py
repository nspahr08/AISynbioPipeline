"""
Configuration management for LIMS API.

This module handles loading and validating configuration from config.json.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any
import jsonschema


def get_config_path() -> Path:
    """Get the path to the configuration file."""
    return Path(__file__).parent / "config.json"


def get_schema_path() -> Path:
    """Get the path to the configuration schema file."""
    return Path(__file__).parent / "config_schema.json"


def load_config() -> Dict[str, Any]:
    """
    Load and validate configuration from config.json.

    Returns:
        Dict containing validated configuration

    Raises:
        FileNotFoundError: If config.json not found
        jsonschema.ValidationError: If config doesn't match schema
        json.JSONDecodeError: If config is not valid JSON
    """
    config_path = get_config_path()
    schema_path = get_schema_path()

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    # Load configuration
    with open(config_path, 'r') as f:
        config = json.load(f)

    # Load schema
    with open(schema_path, 'r') as f:
        schema = json.load(f)

    # Validate configuration against schema
    jsonschema.validate(instance=config, schema=schema)

    return config


def get_db_path(config: Dict[str, Any] = None) -> Path:
    """
    Get the absolute path to the database file.

    Args:
        config: Configuration dict (loads from file if not provided)

    Returns:
        Absolute path to database file
    """
    if config is None:
        config = load_config()

    db_path = config['database']['db_path']

    # Make absolute if relative
    if not os.path.isabs(db_path):
        # Relative to project root (parent of parent of this file)
        project_root = Path(__file__).parent.parent.parent
        db_path = project_root / db_path
    else:
        db_path = Path(db_path)

    # Create parent directory if it doesn't exist
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return db_path


def get_archive_path(config: Dict[str, Any] = None) -> Path:
    """
    Get the absolute path to the archive directory.

    Args:
        config: Configuration dict (loads from file if not provided)

    Returns:
        Absolute path to archive directory
    """
    if config is None:
        config = load_config()

    archive_path = config['database']['archive_path']

    # Make absolute if relative
    if not os.path.isabs(archive_path):
        # Relative to project root
        project_root = Path(__file__).parent.parent.parent
        archive_path = project_root / archive_path
    else:
        archive_path = Path(archive_path)

    # Create directory if it doesn't exist
    archive_path.mkdir(parents=True, exist_ok=True)

    return archive_path


def get_credentials_path(config: Dict[str, Any] = None) -> Path:
    """
    Get the absolute path to the Google Sheets credentials file.

    Args:
        config: Configuration dict (loads from file if not provided)

    Returns:
        Absolute path to credentials file

    Raises:
        FileNotFoundError: If credentials file doesn't exist
    """
    if config is None:
        config = load_config()

    creds_file = config['google_sheets']['credentials_file']

    # Make absolute if relative
    if not os.path.isabs(creds_file):
        # Try several locations
        locations = [
            Path(__file__).parent / creds_file,  # Same dir as this file
            Path(__file__).parent.parent.parent / creds_file,  # Project root
            Path(creds_file),  # Current working directory
        ]

        for location in locations:
            if location.exists():
                return location

        raise FileNotFoundError(
            f"Credentials file not found: {creds_file}. "
            f"Searched in: {[str(loc) for loc in locations]}"
        )
    else:
        creds_path = Path(creds_file)
        if not creds_path.exists():
            raise FileNotFoundError(f"Credentials file not found: {creds_path}")
        return creds_path


def get_drive_credentials_path(config: Dict[str, Any] = None) -> Path:
    """
    Get the absolute path to the Google Drive oauth credentials file.

    Args:
        config: Configuration dict (loads from file if not provided)

    Returns:
        Absolute path to credentials file

    Raises:
        FileNotFoundError: If credentials file doesn't exist
    """
    if config is None:
        config = load_config()

    creds_file = config['drive']['credentials_file']

    # Make absolute if relative
    if not os.path.isabs(creds_file):
        # Try several locations
        locations = [
            Path(__file__).parent / creds_file,  # Same dir as this file
            Path(__file__).parent.parent.parent / creds_file,  # Project root
            Path(creds_file),  # Current working directory
        ]

        for location in locations:
            if location.exists():
                return location.parent.parent

        raise FileNotFoundError(
            f"Credentials file not found: {creds_file}. "
            f"Searched in: {[str(loc) for loc in locations]}"
        )
    else:
        creds_path = Path(creds_file).parent.parent
        if not creds_path.exists():
            raise FileNotFoundError(f"Credentials file not found: {creds_path}")
        return creds_path


# Load configuration on module import
try:
    CONFIG = load_config()
except (FileNotFoundError, jsonschema.ValidationError, json.JSONDecodeError) as e:
    # Don't fail on import, but log the error
    import warnings
    warnings.warn(f"Failed to load configuration: {e}")
    CONFIG = None
