#!/usr/bin/env python3
"""Quick read QC for a folder of FASTQ files.

Usage:
  quick_readQC.py <fastq_folder> <output_dir> [fnames_must_contain] [--threads N]

The script:
- Runs FastQC on every FASTQ file (optionally gzipped) found in `fastq_folder`.
- Runs MultiQC to aggregate the FastQC reports.
- Writes the MultiQC report (multiqc_report.html) and its data folder to
  `output_dir`.
- Only processes fastq files containing the optional `fnames_must_contain`
  string.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

# Add workspace root to path so aisynbiopipeline can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from aisynbiopipeline.workflows.read_qc import run_fastqc, run_multiqc

LOG_FILE = Path(__file__).resolve().parent / 'pipeline.log'


def configure_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
    )
    return logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description='Run FastQC + MultiQC on a folder of FASTQ files')
    parser.add_argument('fastq_folder', help='Path to folder containing FASTQ files')
    parser.add_argument('output_dir', help='Path where the MultiQC report and data will be written')
    parser.add_argument('fnames_must_contain', nargs='?', default=None, help='Optional string to filter fastq filenames; only files containing this string are processed')
    parser.add_argument('--threads', type=int, default=2, help='Threads to pass to FastQC (default: 2)')
    return parser.parse_args()


def main():
    args = parse_args()
    logger = configure_logging()

    fastq_folder = Path(args.fastq_folder).resolve()
    output_dir = Path(args.output_dir).resolve()
    fnames_filter = args.fnames_must_contain

    if not fastq_folder.exists() or not fastq_folder.is_dir():
        raise FileNotFoundError(f'FASTQ folder not found: {fastq_folder}')

    fastq_files = sorted(fastq_folder.glob('*.fastq*')) + sorted(fastq_folder.glob('*.fq*'))
    fastq_files = sorted(set(fastq_files))
    if fnames_filter:
        fastq_files = [f for f in fastq_files if fnames_filter in f.name]
    # Skip FastQC's own outputs so re-runs don't pick up prior zips/htmls.
    fastq_files = [f for f in fastq_files if not f.name.endswith('_fastqc.zip')]
    if not fastq_files:
        raise FileNotFoundError(f'No fastq files found in folder: {fastq_folder}')

    logger.info('Found %d fastq files in %s', len(fastq_files), fastq_folder)

    output_dir.mkdir(parents=True, exist_ok=True)

    for fq in fastq_files:
        try:
            run_fastqc(str(fq), threads=args.threads)
        except Exception as exc:
            logger.error('FastQC failed on %s: %s', fq, exc)
            raise

    logger.info('Running MultiQC on %s, writing report to %s', fastq_folder, output_dir)
    report_path = run_multiqc(str(fastq_folder), output_dir=str(output_dir))
    logger.info('MultiQC report written to %s', report_path)


if __name__ == '__main__':
    main()
