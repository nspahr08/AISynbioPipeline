#!/usr/bin/env python3
"""Update Robotic_OD table in LIMS database from CSV.

Usage:
  db_update_robotic_OD.py <csv_file>

This script reads a CSV file and updates the
Robotic_OD table in the SQLite LIMS database.

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
        description='Update Robotic_OD table from CSV file'
    )
    parser.add_argument(
        'csv_file',
        help='Path to CSV file with mutation data',
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    logger = configure_logging()

    csv_file = Path(args.csv_file)

    logger.info('Starting Robotic_OD table update from %s', csv_file)

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

    # Define schema for Robotic_OD table
    schema: Dict[str, str] = {
        'filename': 'TEXT',
        'experiment': 'TEXT',
        'file_ID': 'TEXT',
        'timestamp': 'INTEGER',
        'series': 'TEXT',
        'plate_index': 'INTEGER',
        'transfer': 'INTEGER',
        'reading': 'TEXT',
        'row': 'INTEGER',
        'column': 'INTEGER',
        'od': 'FLOAT',
        'well': 'TEXT',
        'measurement_type': 'TEXT',
        'culture_container': 'TEXT',
        'plate_type': 'TEXT',
        'start_date': 'TEXT',
        'file_basename': 'TEXT',
        'bmg_filename': 'TEXT',
        'datetime': 'TEXT',
        'sample_name': 'TEXT',
        'Type': 'TEXT',
        'Condition': 'TEXT',
        'strain': 'TEXT',
        'Transforming_DNA': 'TEXT',
        'Protocol': 'TEXT',
        'Parent_sample': 'TEXT',
        'Replicate_samples': 'TEXT',
        'Microtiter_plate_name': 'TEXT',
        'Microtiter_plate_well': 'TEXT',
        'background': 'FLOAT',
        'innoculation_timestamp': 'TEXT',
        'resource_id': 'TEXT',
        'Plate_name': 'TEXT',
        'Name': 'TEXT',
        'trans_DNA_concentration': 'TEXT',
        'trans_DNA+conc': 'TEXT',
        'Strain_name': 'TEXT',
        'Transforming_DNA': 'TEXT',
        'Parent_sample': 'TEXT',
        'Replicate_samples': 'TEXT',
        'Plate_name': 'TEXT',
        'Microtiter_plate_well': 'TEXT',
        'Plotting_group_number': 'INTEGER',
        'Plotting_group_name': 'TEXT',
        'Blank': 'BOOL',
        'timepoint': 'FLOAT',
        'inoculation_timestamp': 'TEXT'
    }

    # Ensure table exists with correct schema
    try:
        db_manager.sync_schema('Robotic_OD', schema)
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
        'filename', 'experiment', 'file_ID', 'timestamp', 'series',
       'plate_index', 'transfer', 'reading', 'row', 'column', 'od', 'well',
       'measurement_type', 'culture_container', 'plate_type', 'start_date',
       'file_basename', 'bmg_filename', 'datetime', 'sample_name',
       'Type', 'Condition', 'strain', 'Transforming_DNA',
       'Protocol', 'Parent_sample', 'Replicate_samples',
       'Microtiter_plate_name', 'Microtiter_plate_well', 'background',
       'innoculation_timestamp', 'resource_id', 'Plate_name', 'Name',
       'trans_DNA_concentration', 'trans_DNA+conc', 'Strain_name',
       'Transforming_DNA', 'Parent_sample', 'Replicate_samples', 'Plate_name',
       'Microtiter_plate_well', 'Plotting_group_number', 'Plotting_group_name',
       'Blank', 'timepoint', 'inoculation_timestamp'
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
        inserted, updated = db_manager.upsert_rows('Robotic_OD', rows)
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
    logger.info('Robotic_OD table update completed successfully')


if __name__ == '__main__':
    main()
