#!/usr/bin/env python3
"""Download the raw read bundle for a Plasmidsaurus item.

This script downloads the raw read bundle for a given item_code and unzips
the results into a hardcoded reception folder. It does not organize the
fastq files into the standard library folder structure; use
organize_seqdata.py for that once the download has completed.

The only required argument is item_code.
"""

from __future__ import annotations

import sys
import argparse
import logging
from pathlib import Path

# Add workspace root to path so aisynbiopipeline can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from aisynbiopipeline.workflows.plasmidsaurus import (
    create_seqorder_name,
    download_results,
    get_access_token,
    get_credentials,
)

DOWNLOAD_ROOT = Path('/storage/synbio/ai_synbio_data/experimental_data/downloads')
ANALYSIS_HOME_ROOT = Path('/storage/nspahr/lib_analysis')
LOG_FILE = Path(__file__).resolve().parent / 'pipeline.log'


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
    logger.info('Starting download_seqdata')
    logger.info('Log file: %s', LOG_FILE)
    return logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Download the raw read bundle for a Plasmidsaurus item.'
    )
    parser.add_argument('item_code', help='Plasmidsaurus item code to process')
    return parser.parse_args()


def get_item_access_token() -> str:
    client_id = get_credentials('PLASMIDSAURUS_CLIENT_ID')
    client_secret = get_credentials('PLASMIDSAURUS_CLIENT_SECRET')
    return get_access_token(client_id, client_secret)


def spotcheck_read_duplication(reads_folder: Path, logger: logging.Logger) -> None:
    logger.info(
        'TODO: implement a lightweight read-ID duplication check for a small set of Illumina fastq files.'
    )
    # Placeholder: future implementation should sample one or more Illumina fastq files,
    # parse sequence identifiers, and detect duplicate read IDs before organizing.


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

    access_token = get_item_access_token()
    download_results(item_code, access_token, str(reception_dir))

    reads_folder = reception_dir / f'{item_code}_reads'
    if not reads_folder.exists():
        logger.error('Expected reads folder not found: %s', reads_folder)
        raise FileNotFoundError(f'Reads folder not found: {reads_folder}')

    spotcheck_read_duplication(reads_folder, logger)

    logger.info('Finished downloading fastq files for %s', item_code)
    logger.info('Reads folder: %s', reads_folder)
    logger.info('Run organize_seqdata.py %s --platform <platform> to organize the files.', item_code)


if __name__ == '__main__':
    main()
