#!/usr/bin/env python3
"""Trim down a LIMS database file to a single experiment / sequencing order.

Usage:
  trim_database.py <db_file>

This script trims a copy of the SQLite LIMS database down to the data
relevant to experiment ``TFMN1`` and sequencing order
``Plasmidsaurus_2025-12-22_MQRBN8``. It uses the operations provided by
``limsapi.database.DatabaseManager``.

The trimming performs the following, in order:
  1. Delete rows from several tables that don't belong to the target
     experiment / sequencing order / breseq run.
  2. Drop tables that are not needed at all.
  3. Delete rows from Strains / Conditions that are no longer referenced by
     the remaining Samples rows.

WARNING: This operation removes data in place. Run it against a *copy* of the
database, never the production file.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from limsapi.config import load_config
from limsapi.database import DatabaseManager


LOG_FILE = Path(__file__).resolve().parent / 'pipeline.log'

# Target identifiers to keep.
TARGET_EXPERIMENT = 'TFMN1'
TARGET_SEQORDER = 'Plasmidsaurus_2025-12-22_MQRBN8'
TARGET_BRESEQ_ID = 'breseq_483a96084b'

# (table, column, value) triples. Rows where column != value are removed.
# ``IS NOT`` is used so that NULL values are also removed (null-safe compare).
KEEP_EQUAL = [
    ('Experiments', 'Name', TARGET_EXPERIMENT),
    ('Samples', 'Experiment', TARGET_EXPERIMENT),
    ('Measurements', 'Experiment', TARGET_EXPERIMENT),
    ('Robotic_run', 'Experiment', TARGET_EXPERIMENT),
    ('Robotic_ALE_samples', 'Experiment', TARGET_EXPERIMENT),
    ('Seq_orders', 'Poplar_Seqorder_Name', TARGET_SEQORDER),
    ('Seq_samples', 'Seqorder', TARGET_SEQORDER),
    ('Breseq_registry', 'ID', TARGET_BRESEQ_ID),
    ('Copy_numbers', 'Seqorder', TARGET_SEQORDER),
    ('Copy_numbers', 'Breseq_registry_ID', TARGET_BRESEQ_ID),
    ('Mutations', 'Experiment', TARGET_EXPERIMENT),
]

# Tables to drop entirely.
DROP_TABLES = [
    'Strain_stocks_ANL',
    'Plasmid_stocks_ANL',
    'Primers',
    'Wells',
    'dgoA_alleles_new',
    'dgoA_alleles_old',
    'Study',
    'Transformation_libraries',
    'robotic_mt_samples',
    'verAB_barcodes'
]

# (table, column, ref_table, ref_column) referential trims. Rows are kept only
# if their column value appears in ref_table.ref_column among the remaining
# (target-experiment) Samples rows.
KEEP_REFERENCED = [
    ('Strains', 'Name', 'Samples', 'Strain'),
    ('Conditions', 'Name', 'Samples', 'Condition'),
    ('DNA_constructs', 'Name', 'Samples', 'Transforming_DNA'),
]


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
        description='Trim a LIMS database down to a single experiment.'
    )
    parser.add_argument(
        'db_file',
        help='Path to the SQLite database file to trim (modified in place).',
    )
    return parser.parse_args()


def delete_keep_equal(db_manager, logger, table, column, value):
    """Delete rows from ``table`` where ``column`` is not ``value``."""
    if not db_manager.table_exists(table):
        logger.warning('Table %s does not exist; skipping.', table)
        return
    conn = db_manager.get_connection()
    cursor = conn.execute(
        f'DELETE FROM "{table}" WHERE "{column}" IS NOT ?',
        (value,),
    )
    conn.commit()
    logger.info(
        'Trimmed %s: removed %d rows where %s != %r',
        table, cursor.rowcount, column, value,
    )


def delete_keep_referenced(db_manager, logger, table, column,
                           ref_table, ref_column):
    """Delete rows from ``table`` whose ``column`` is not referenced by the
    target-experiment rows of ``ref_table.ref_column``."""
    if not db_manager.table_exists(table):
        logger.warning('Table %s does not exist; skipping.', table)
        return
    conn = db_manager.get_connection()
    cursor = conn.execute(
        f'DELETE FROM "{table}" WHERE "{column}" NOT IN ('
        f'SELECT "{ref_column}" FROM "{ref_table}" '
        f'WHERE "Experiment" = ? AND "{ref_column}" IS NOT NULL)',
        (TARGET_EXPERIMENT,),
    )
    conn.commit()
    logger.info(
        'Trimmed %s: removed %d rows not referenced by %s.%s '
        '(Experiment = %r)',
        table, cursor.rowcount, ref_table, ref_column, TARGET_EXPERIMENT,
    )


def main():
    """Main entry point."""
    args = parse_args()
    logger = configure_logging()

    db_file = Path(args.db_file)
    logger.info('Starting database trim on %s', db_file)

    if not db_file.exists():
        logger.error('Database file not found: %s', db_file)
        raise FileNotFoundError(f'Database file not found: {db_file}')

    # Load configuration and point the manager at the supplied db file.
    config = load_config()
    db_manager = DatabaseManager(config)
    db_manager.db_path = db_file
    db_manager.connect()
    logger.info('Connected to database: %s', db_manager.db_path)

    try:
        # 1. Row-level trims on the target experiment / seq order / breseq run.
        for table, column, value in KEEP_EQUAL:
            delete_keep_equal(db_manager, logger, table, column, value)

        # 2. Drop unneeded tables.
        for table in DROP_TABLES:
            db_manager.drop_table(table)
            logger.info('Dropped table %s', table)

        # 3. Trim lookup tables to rows still referenced by remaining Samples.
        for table, column, ref_table, ref_column in KEEP_REFERENCED:
            delete_keep_referenced(
                db_manager, logger, table, column, ref_table, ref_column
            )

        # Reclaim space freed by the deletions.
        db_manager.get_connection().execute('VACUUM')
        logger.info('Vacuumed database to reclaim space.')
    except Exception as exc:
        logger.error('Failed to trim database: %s', exc)
        db_manager.disconnect()
        raise

    db_manager.disconnect()
    logger.info('Database connection closed')
    logger.info('Database trim completed successfully')


if __name__ == '__main__':
    main()
