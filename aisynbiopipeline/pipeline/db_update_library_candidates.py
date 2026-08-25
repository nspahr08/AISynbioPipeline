#!/usr/bin/env python3
"""Update Library_candidates table in LIMS database from CSV.

Usage:
  db_update_library_candidates.py <csv_file>

This script reads a CSV file and updates the
Library_candidates table in the SQLite LIMS database.

							

Expected CSV columns (others are ignored):
  - Library
  - Feature_type
  - Feature_number
  - Feature_alias
  - Feature_name
  - Barcode
  - Sequence
  - AI_generated

"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, Any

import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from limsapi.config import load_config
from limsapi.database import DatabaseManager


LOG_FILE = Path(__file__).resolve().parent / 'pipeline.log'


def configure_logging():
    """Set up logging to file and console."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
    )
    return logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Update Library_candidates table from CSV file'
    )
    parser.add_argument(
        'csv_file',
        help='Path to CSV file with copy number data',
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    logger = configure_logging()

    csv_file = Path(args.csv_file)

    logger.info('Starting Library_candidates table update from %s', csv_file)

    if not csv_file.exists():
        logger.error('CSV file not found: %s', csv_file)
        raise FileNotFoundError(f'CSV file not found: {csv_file}')

    # Load configuration
    try:
        config = load_config()
        logger.info('Loaded configuration from config.json')
    except Exception as exc:
        logger.error('Failed to load configuration: %s', exc)
        raise

    # Initialize database manager
    try:
        db_manager = DatabaseManager(config)
        db_manager.connect()
        logger.info('Connected to database: %s', db_manager.db_path)
    except Exception as exc:
        logger.error('Failed to connect to database: %s', exc)
        raise

    # Define schema for Library_candidates table
    schema: Dict[str, str] = {
        'Library': 'TEXT NOT NULL',
        'Feature_type': 'TEXT',
        'Feature_number': 'TEXT NOT NULL',
        'Feature_alias': 'TEXT',
        'Feature_name': 'TEXT',
        'Barcode': 'TEXT',
        'Sequence': 'TEXT',
        'AI_generated': 'BOOL',
    }

    # Ensure table exists with correct schema
    try:
        db_manager.sync_schema('Library_candidates', schema)
        logger.info('Table schema synchronized')
    except Exception as exc:
        logger.error('Failed to sync table schema: %s', exc)
        db_manager.disconnect()
        raise

    # Read CSV file
    try:
        df = pd.read_csv(csv_file)
        logger.info('Read %d rows from CSV file', len(df))
    except Exception as exc:
        logger.error('Failed to read CSV file: %s', exc)
        db_manager.disconnect()
        raise

    # Filter to required columns, ignoring others
    required_columns = [
        'Library',
        'Feature_type',
        'Feature_number',
        'Feature_alias',
        'Feature_name',
        'Barcode',
        'Sequence',
        'AI_generated',
    ]

    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        logger.error(
            'CSV file missing required columns: %s',
            missing_columns,
        )
        db_manager.disconnect()
        raise ValueError(
            f'CSV file missing required columns: {missing_columns}'
        )

    df_filtered = df[required_columns].copy()

    # Convert to list of dicts for upsert
    rows = df_filtered.to_dict('records')

    # Upsert rows into database
    try:
        inserted, updated = db_manager.upsert_rows('Library_candidates', rows)
        logger.info(
            'Database update complete: %d rows inserted, %d rows updated',
            inserted,
            updated,
        )
    except Exception as exc:
        logger.error('Failed to upsert rows: %s', exc)
        db_manager.disconnect()
        raise

    db_manager.disconnect()
    logger.info('Database connection closed')
    logger.info('Library_candidates table update completed successfully')


if __name__ == '__main__':
    main()
