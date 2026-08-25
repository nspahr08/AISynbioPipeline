#!/usr/bin/env python3
"""Convert a folder of SnapGene (.dna) files to FASTA format.

Usage:
  snapgene_to_fasta.py <input_folder> <output_dir> [--recursive] [--delete-source]

Every .dna file found in `input_folder` is parsed with Biopython's built-in
'snapgene' format support and written as a single-record FASTA file of the
same name (<stem>.fasta) in `output_dir`. Files that fail to parse are
logged and skipped so the rest of the batch still completes.

With --delete-source, each .dna file is deleted after it is successfully
converted (files that fail to convert are left in place).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from Bio import SeqIO

LOG_FILE = Path(__file__).resolve().parent / 'pipeline.log'


def configure_logging() -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
    )
    return logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Convert a folder of SnapGene .dna files to FASTA format')
    parser.add_argument('input_folder', help='Path to folder containing .dna files')
    parser.add_argument('output_dir', help='Path where converted .fasta files will be written')
    parser.add_argument('--recursive', action='store_true', help='Also search subfolders of input_folder for .dna files')
    parser.add_argument('--delete-source', action='store_true', help='Delete each .dna file after it is successfully converted')
    return parser.parse_args()


def convert_file(dna_path: Path, output_dir: Path, logger: logging.Logger) -> Path | None:
    fasta_path = output_dir / f'{dna_path.stem}.fasta'
    try:
        record = SeqIO.read(dna_path, 'snapgene')
    except Exception as exc:
        logger.error('Failed to parse %s: %s', dna_path, exc)
        return None
    SeqIO.write(record, fasta_path, 'fasta')
    return fasta_path


def main() -> None:
    args = parse_args()
    logger = configure_logging()

    input_folder = Path(args.input_folder).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not input_folder.exists() or not input_folder.is_dir():
        raise FileNotFoundError(f'Input folder not found: {input_folder}')

    pattern = '**/*.dna' if args.recursive else '*.dna'
    dna_files = sorted(input_folder.glob(pattern))
    if not dna_files:
        raise FileNotFoundError(f'No .dna files found in folder: {input_folder}')

    logger.info('Found %d .dna files in %s', len(dna_files), input_folder)

    output_dir.mkdir(parents=True, exist_ok=True)

    converted, failed = 0, 0
    for dna_path in dna_files:
        fasta_path = convert_file(dna_path, output_dir, logger)
        if fasta_path is None:
            failed += 1
            continue
        converted += 1
        logger.info('Converted %s -> %s', dna_path, fasta_path)
        if args.delete_source:
            dna_path.unlink()
            logger.info('Deleted source file %s', dna_path)

    logger.info('Done: %d converted, %d failed', converted, failed)
    if failed and not converted:
        raise RuntimeError('All .dna files failed to convert; see log for details')


if __name__ == '__main__':
    main()
