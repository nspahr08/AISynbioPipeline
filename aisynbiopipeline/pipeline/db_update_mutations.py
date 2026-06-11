#!/usr/bin/env python3
"""Update Mutations table in LIMS database from CSV.

Usage:
  db_update_mutations.py <csv_file>

This script reads a CSV file and updates the
Mutations table in the SQLite LIMS database.

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
        description='Update Mutations table from CSV file'
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

    logger.info('Starting Mutations table update from %s', csv_file)

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

    # Define schema for Mutations table
    schema: Dict[str, str] = {
     'Experiment': 'TEXT',
     'Seq_sample': 'TEXT',
     'Seqorder': 'TEXT',
     'Breseq_registry_ID': 'TEXT',
     'seq_id': 'TEXT',
     'aa_new_seq': 'TEXT',
     'aa_position': 'INTEGER',
     'aa_ref_seq': 'TEXT',
     'codon_new_seq': 'TEXT',
     'codon_position': 'INTEGER',
     'codon_ref_seq': 'TEXT',
     'evidence_ids': 'INTEGER',
     'frequency': 'REAL',
     'gene_name': 'TEXT',
     'gene_position': 'TEXT',
     'gene_product': 'TEXT',
     'gene_strand': 'TEXT',
     'genes_inactivated': 'TEXT',
     'genes_overlapping': 'TEXT',
     'genes_promoter': 'TEXT',
     'id': 'INTEGER',
     'locus_tag': 'TEXT',
     'locus_tags_inactivated': 'TEXT',
     'locus_tags_overlapping': 'TEXT',
     'locus_tags_promoter': 'TEXT',
     'mutation_category': 'TEXT',
     'new_seq': 'TEXT',
     'position': 'INTEGER',
     'position_end': 'INTEGER',
     'position_start': 'INTEGER',
     'ref_seq': 'TEXT',
     'snp_type': 'TEXT',
     'type': 'TEXT',
     'codon_number': 'INTEGER',
     'codon_position_is_indeterminate': 'TEXT',
     'transl_table': 'INTEGER',
     'insert_position': 'INTEGER',
     'repeat_length': 'BOOLEAN',
     'repeat_new_copies': 'INTEGER',
     'repeat_ref_copies': 'INTEGER',
     'repeat_seq': 'TEXT',
     'size': 'TEXT',
     'multiple_polymorphic_SNPs_in_same_codon': 'TEXT'
    }

    # Ensure table exists with correct schema
    try:
        db_manager.sync_schema('Mutations', schema)
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
        'Experiment', 'Seq_sample', 'Seqorder', 'Breseq_registry_ID', 'seq_id', 'aa_new_seq', 'aa_position', 'aa_ref_seq', 'codon_new_seq', 'codon_position', 'codon_ref_seq', 'evidence_ids', 'frequency', 'gene_name', 'gene_position', 'gene_product', 'gene_strand', 'genes_inactivated', 'genes_overlapping', 'genes_promoter', 'id', 'locus_tag', 'locus_tags_inactivated', 'locus_tags_overlapping', 'locus_tags_promoter', 'mutation_category', 'new_seq', 'position', 'position_end', 'position_start', 'ref_seq', 'snp_type', 'type', 'codon_number', 'codon_position_is_indeterminate', 'transl_table', 'insert_position', 'repeat_length', 'repeat_new_copies', 'repeat_ref_copies', 'repeat_seq', 'size', 'multiple_polymorphic_SNPs_in_same_codon'
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
        inserted, updated = db_manager.upsert_rows('Mutations', rows)
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
    logger.info('Mutations table update completed successfully')


if __name__ == '__main__':
    main()
