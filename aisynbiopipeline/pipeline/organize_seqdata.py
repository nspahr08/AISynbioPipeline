#!/usr/bin/env python3
"""Organize downloaded fastq files for a Plasmidsaurus item.

This script expects download_seqdata.py to have already downloaded and
unzipped the raw read bundle for the given item_code into the hardcoded
reception folder. It copies Illumina and Nanopore fastq files into the
standard library folder structure with renamed filenames.

The only required argument is item_code. The expected fastq type is
controlled by the optional --platform argument.
"""

from __future__ import annotations

import sys
import argparse
import logging
import shutil
from pathlib import Path

import pandas as pd

# Add workspace root to path so aisynbiopipeline can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from aisynbiopipeline.workflows.plasmidsaurus import create_seqorder_name
from aisynbiopipeline.workflows.seq_folder_utils import Library, SeqOrder
from aisynbiopipeline.limsapi.query import query_to_dataframe

DOWNLOAD_ROOT = Path('/storage/synbio/ai_synbio_data/experimental_data/downloads')
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
    logger.info('Starting organize_seqdata')
    logger.info('Log file: %s', LOG_FILE)
    return logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Organize downloaded fastq files for a Plasmidsaurus item.'
    )
    parser.add_argument('item_code', help='Plasmidsaurus item code to process')
    parser.add_argument(
        '--platform',
        choices=PLATFORM_CHOICES,
        default='hybrid',
        help='Expected read type for this item: illumina, nanopore, or hybrid',
    )
    parser.add_argument(
        '--rename-to-lims',
        action='store_true',
        help=(
            'After copying, rename files in received/ from their Tube_label '
            '(the Plasmidsaurus-derived sample name) to the matching '
            'Sequencing_sample name, per the Seq_samples LIMS table for this '
            'Seqorder. R1/R2 indicators are preserved for Illumina reads.'
        ),
    )
    return parser.parse_args()


def rename_plasmidsaurus_read_file(filename: str, logger: logging.Logger) -> str:
    parts = filename.split('_')
    if len(parts) < 3:
        logger.warning('Original file names are not in expected Plasmidsaurus format. Keeping original names.')
        return filename
    newname = '_'.join(parts[2:])
    newname = newname.replace("_illumina", "").replace("_nanopore", "")
    return newname


def copy_reads_to_library(reads_folder: Path, library: Library, pattern: str, logger: logging.Logger) -> int:
    copied = 0
    for source_path in sorted(reads_folder.glob(pattern)):
        if not source_path.is_file():
            continue
        renamed = rename_plasmidsaurus_read_file(source_path.name, logger)
        destination = library.path / 'received' / renamed
        logger.info('Copying %s -> %s', source_path, destination)
        shutil.copy2(source_path, destination)
        copied += 1
    logger.info('Copied %s files for pattern %s into %s', copied, pattern, library.path / 'received')
    return copied


def build_lims_rename_map(seqorder_name: str, sample_names: list, logger: logging.Logger) -> dict:
    """Look up the Sequencing_sample name for each Tube_label in ``sample_names``.

    Aborts if any sample has no matching Tube_label row, if Seq_samples has
    more than one row with the same Tube_label for this Seqorder, or if any
    row's Sequencing_sample value is empty.
    """
    seq_samples = query_to_dataframe('Seq_samples', filters={'Seqorder': seqorder_name})
    if seq_samples.empty:
        raise ValueError(f'No rows found in Seq_samples for Seqorder={seqorder_name!r}')

    lookup = seq_samples[['Tube_label', 'Sequencing_sample']]

    def is_blank(value) -> bool:
        return pd.isna(value) or str(value).strip() == ''

    blank_labels = sorted(lookup.loc[lookup['Sequencing_sample'].apply(is_blank), 'Tube_label'].tolist())
    if blank_labels:
        raise ValueError(
            f'Seq_samples.Sequencing_sample is empty for Tube_label(s) in Seqorder={seqorder_name!r}: {blank_labels}'
        )

    duplicated_labels = sorted(lookup.loc[lookup['Tube_label'].duplicated(keep=False), 'Tube_label'].unique())
    if duplicated_labels:
        raise ValueError(
            f'Ambiguous Tube_label values in Seq_samples for Seqorder={seqorder_name!r}: {duplicated_labels}'
        )

    rename_map = dict(zip(lookup['Tube_label'], lookup['Sequencing_sample']))

    missing = sorted(s for s in sample_names if s not in rename_map)
    if missing:
        raise ValueError(
            f'No Seq_samples.Tube_label match for samples in Seqorder={seqorder_name!r}: {missing}'
        )

    logger.info('LIMS rename map for Seqorder=%s: %s', seqorder_name, {s: rename_map[s] for s in sample_names})
    return {s: rename_map[s] for s in sample_names}


def rename_library_to_lims(library: Library, seqorder_name: str, logger: logging.Logger) -> None:
    """Rename files in ``library``'s received/ folder from Tube_label to Sequencing_sample.

    Sample names are generated via ``library.create_manifest('received')``. R1/R2
    indicators (and file extensions) are preserved by only replacing the
    Tube_label prefix of each filename.
    """
    manifest = library.create_manifest('received')
    if manifest.empty:
        logger.info('No samples to rename in %s', library.path / 'received')
        return

    sample_names = manifest['sample_name'].tolist()
    rename_map = build_lims_rename_map(seqorder_name, sample_names, logger)

    file_columns = [col for col in ('R1', 'R2', 'fastq_file') if col in manifest.columns]

    for _, row in manifest.iterrows():
        sample_name = row['sample_name']
        new_name = rename_map[sample_name]
        for col in file_columns:
            path = row.get(col)
            if path is None or (isinstance(path, float) and pd.isna(path)):
                continue
            old_path = Path(path)
            if not old_path.name.startswith(sample_name):
                raise ValueError(
                    f'Expected {old_path.name!r} to start with sample name {sample_name!r}; '
                    'cannot safely rename to LIMS name.'
                )
            new_path = old_path.with_name(new_name + old_path.name[len(sample_name):])
            logger.info('Renaming %s -> %s', old_path, new_path)
            old_path.rename(new_path)


def main() -> None:
    args = parse_args()
    logger = configure_logging()
    item_code = args.item_code
    platform = args.platform
    logger.info('Platform mode: %s', platform)

    seqorder_name = create_seqorder_name(item_code)
    logger.info('Resolved seqorder name: %s', seqorder_name)

    reception_dir = DOWNLOAD_ROOT / seqorder_name
    reads_folder = reception_dir / f'{item_code}_reads'
    if not reads_folder.exists():
        logger.error('Expected reads folder not found: %s', reads_folder)
        raise FileNotFoundError(f'Reads folder not found: {reads_folder}. Run download_seqdata.py first.')

    seqorder = SeqOrder(seqorder_name, create=True)
    short_library = Library(seqorder, 'Illumina', create=True) if platform in ('hybrid', 'illumina') else None
    long_library = Library(seqorder, 'Nanopore', create=True) if platform in ('hybrid', 'nanopore') else None

    if platform == 'hybrid':
        illumina_count = copy_reads_to_library(reads_folder, short_library, '*illumina*.fastq*', logger)
        nanopore_count = copy_reads_to_library(reads_folder, long_library, '*nanopore*.fastq*', logger)
    elif platform == 'illumina':
        illumina_count = copy_reads_to_library(reads_folder, short_library, '*.fastq*', logger)
        nanopore_count = 0
    else:
        illumina_count = 0
        nanopore_count = copy_reads_to_library(reads_folder, long_library, '*.fastq*', logger)

    if args.rename_to_lims:
        for library in (short_library, long_library):
            if library is not None:
                rename_library_to_lims(library, seqorder_name, logger)

    logger.info('Finished organizing fastq files for %s', item_code)
    logger.info('Illumina files copied: %s', illumina_count)
    logger.info('Nanopore files copied: %s', nanopore_count)


if __name__ == '__main__':
    main()
