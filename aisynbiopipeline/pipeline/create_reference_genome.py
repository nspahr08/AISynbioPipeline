#!/usr/bin/env python3
"""Create a new reference genome from a Breseq GenomeDiff (.gd) file.

This script reads a Breseq run output from an Illumina seqsample, applies
mutations from the run's data/output.gd file, and writes a new GenBank
reference to the configured REF_GENOMES directory.

Arguments:
    seqorder: name of the sequencing order folder
    seqsample: sample name inside the Illumina library
    breseq_registry_id: Breseq run registry folder identifier (with or without "breseq_" prefix)
    new_ref_name: new reference genome filename (must end with .gbk)
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from aisynbiopipeline.workflows.breseq import Breseq
from aisynbiopipeline.workflows.reference_utils import get_ref_genomes_path
from aisynbiopipeline.limsapi.googledrive import upload_or_replace
from aisynbiopipeline.workflows.seq_folder_utils import Library, SeqOrder

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
    logger.info('Starting create_reference_genome')
    return logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Create a new reference genome from a Breseq GenomeDiff file.'
    )
    parser.add_argument('seqorder', help='Sequencing order name')
    parser.add_argument('seqsample', help='SeqSample name in the Illumina library')
    parser.add_argument('breseq_registry_id', help='Breseq registry ID')
    parser.add_argument('new_ref_name', help='New GenBank reference filename (e.g. new_ref.gbk)')
    return parser.parse_args()


def normalize_registry_folder(registry_id: str) -> str:
    if registry_id.startswith('breseq_'):
        return registry_id
    return f'breseq_{registry_id}'


def normalize_reference_name(ref_name: str) -> str:
    if not ref_name.lower().endswith('.gbk'):
        ref_name = f'{ref_name}.gbk'
    return ref_name


def main() -> None:
    args = parse_args()
    logger = configure_logging()

    seqorder_name = args.seqorder
    seqsample_name = args.seqsample
    registry_folder = normalize_registry_folder(args.breseq_registry_id)
    new_ref_name = normalize_reference_name(args.new_ref_name)

    ref_genomes_path = Path(get_ref_genomes_path())
    new_ref_path = ref_genomes_path / new_ref_name
    if new_ref_path.exists():
        raise FileExistsError(f'Reference already exists: {new_ref_path}')

    seqorder = SeqOrder(seqorder_name)
    illumina_library = Library(seqorder, 'Illumina')

    breseq_run_folder = illumina_library.path / 'breseq' / seqsample_name / registry_folder
    gd_path = breseq_run_folder / 'data' / 'output.gd'

    if not breseq_run_folder.exists():
        raise FileNotFoundError(f'Breseq run folder does not exist: {breseq_run_folder}')
    if not gd_path.exists():
        raise FileNotFoundError(f'GenomeDiff file does not exist: {gd_path}')

    breseq_object = Breseq.from_existing(breseq_run_folder)

    reference_path = Path(breseq_object.reference_path)
    if not reference_path.exists():
        raise FileNotFoundError(f'Old reference GenBank file does not exist: {reference_path}')

    new_ref_path.parent.mkdir(parents=True, exist_ok=True)
    applied_path = breseq_object.apply_mutations(new_ref_path, format='GENBANK')

    drive_folder_id = '191faLQEDTSDjMlZm80h3agsfEcK10sxr'
    try:
        upload_or_replace(str(applied_path), drive_folder_id)
        logger.info('Uploaded new reference to Google Drive folder %s', drive_folder_id)
    except Exception as exc:
        logger.error('Failed to upload new reference to Google Drive: %s', exc)

    logger.info('Successfully created new reference genome')
    logger.info('Input .gd: %s', gd_path)
    logger.info('Old reference .gbk: %s', reference_path)
    logger.info('New reference .gbk: %s', applied_path)


if __name__ == '__main__':
    main()
