#!/usr/bin/env python3
"""Download and organize fastq files for a Plasmidsaurus item.

This script downloads the raw read bundle for a given item_code,
unzips the results into a hardcoded reception folder, and copies
Illumina and Nanopore fastq files into the standard library folder
structure with renamed filenames.

The only required argument is item_code. The expected fastq type is
controlled by the optional --platform argument.
"""

from __future__ import annotations

import sys
import argparse
import logging
import os
import shutil
from pathlib import Path

# Add workspace root to path so aisynbiopipeline can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from aisynbiopipeline.workflows.plasmidsaurus import (
    create_seqorder_name,
    download_results,
    get_access_token,
    get_credentials,
)
from aisynbiopipeline.workflows.seq_folder_utils import Library, SeqOrder

DOWNLOAD_ROOT = Path('/storage/synbio/ai_synbio_data/experimental_data/downloads')
ANALYSIS_HOME_ROOT = Path('/storage/nspahr/lib_analysis')
LOG_FILE = Path(__file__).resolve().parent / 'pipeline.log'
PLATFORM_CHOICES = ('illumina', 'nanopore', 'hybrid')


def configure_logging() -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger(__name__)
    logger.info('Starting download_and_organize_fastq')
    logger.info('Log file: %s', LOG_FILE)
    return logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Download and organize fastq files for a Plasmidsaurus item.'
    )
    parser.add_argument('item_code', help='Plasmidsaurus item code to process')
    parser.add_argument(
        '--platform',
        choices=PLATFORM_CHOICES,
        default='hybrid',
        help='Expected read type for this item: illumina, nanopore, or hybrid',
    )
    return parser.parse_args()


def get_item_access_token() -> str:
    client_id = get_credentials('PLASMIDSAURUS_CLIENT_ID')
    client_secret = get_credentials('PLASMIDSAURUS_CLIENT_SECRET')
    return get_access_token(client_id, client_secret)


def rename_plasmidsaurus_read_file(filename: str) -> str:
    parts = filename.split('_')
    if len(parts) < 3:
        return filename
    return '_'.join(parts[2:])


def spotcheck_read_duplication(reads_folder: Path, logger: logging.Logger) -> None:
    logger.info(
        'TODO: implement a lightweight read-ID duplication check for a small set of Illumina fastq files.'
    )
    # Placeholder: future implementation should sample one or more Illumina fastq files,
    # parse sequence identifiers, and detect duplicate read IDs before organizing.


def copy_reads_to_library(reads_folder: Path, library: Library, pattern: str, logger: logging.Logger) -> int:
    copied = 0
    for source_path in sorted(reads_folder.glob(pattern)):
        if not source_path.is_file():
            continue
        renamed = rename_plasmidsaurus_read_file(source_path.name)
        destination = library.path / 'received' / renamed
        logger.info('Copying %s -> %s', source_path, destination)
        shutil.copy2(source_path, destination)
        copied += 1
    logger.info('Copied %s files for pattern %s into %s', copied, pattern, library.path / 'received')
    return copied


def main() -> None:
    args = parse_args()
    logger = configure_logging()
    item_code = args.item_code

    seqorder_name = create_seqorder_name(item_code)
    logger.info('Resolved seqorder name: %s', seqorder_name)

    reception_dir = DOWNLOAD_ROOT / seqorder_name
    reception_dir.mkdir(parents=True, exist_ok=True)
    logger.info('Reception directory: %s', reception_dir)

    analysis_dir = ANALYSIS_HOME_ROOT / seqorder_name
    analysis_dir.mkdir(parents=True, exist_ok=True)
    logger.info('Analysis directory: %s', analysis_dir)

    platform = args.platform
    logger.info('Platform mode: %s', platform)

    access_token = get_item_access_token()
    download_results(item_code, access_token, str(reception_dir))

    reads_folder = reception_dir / f'{item_code}_reads'
    if not reads_folder.exists():
        logger.error('Expected reads folder not found: %s', reads_folder)
        raise FileNotFoundError(f'Reads folder not found: {reads_folder}')

    spotcheck_read_duplication(reads_folder, logger)

    seqorder = SeqOrder(seqorder_name, create=True)
    short_library = Library(seqorder, 'Illumina', create=True) if platform in ('hybrid', 'illumina') else None
    long_library = Library(seqorder, 'Nanopore', create=True) if platform in ('hybrid', 'nanopore') else None

    if platform == 'hybrid':
        illumina_count = copy_reads_to_library(reads_folder, short_library, '*illumina*.fastq', logger)
        nanopore_count = copy_reads_to_library(reads_folder, long_library, '*nanopore*.fastq', logger)
    elif platform == 'illumina':
        illumina_count = copy_reads_to_library(reads_folder, short_library, '*.fastq', logger)
        nanopore_count = 0
    else:
        illumina_count = 0
        nanopore_count = copy_reads_to_library(reads_folder, long_library, '*.fastq', logger)

    logger.info('Finished organizing fastq files for %s', item_code)
    logger.info('Illumina files copied: %s', illumina_count)
    logger.info('Nanopore files copied: %s', nanopore_count)


if __name__ == '__main__':
    main()
