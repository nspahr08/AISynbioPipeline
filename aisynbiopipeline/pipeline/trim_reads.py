#!/usr/bin/env python3
"""Run fastp and MultiQC for all Illumina samples in a SeqOrder.

Usage:
  trim_reads.py <seqorder>

The script:
- Verifies `seqorder` has an Illumina library with files in `received/`.
- Creates `trimmed/` and runs `fastp` (via Celery tasks) for every sample.
- Waits for all fastp tasks to finish, then runs `multiqc` on `trimmed/`.
- Uploads `multiqc` report to Google Drive and copies it to analysis home.

Notes:
- Defaults are conservative; you can override fastp threads and polyG via CLI options.
- This script only performs trimming/QC. Use run_breseq.py to call mutations
  against a reference genome once trimming has completed.
"""

from __future__ import annotations

import sys
import argparse
import logging
import time
import shutil
from pathlib import Path
from typing import List

import pandas as pd

# Add workspace root to path so aisynbiopipeline can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from aisynbiopipeline.workflows.seq_folder_utils import SeqOrder, Library
from aisynbiopipeline.workflows.read_qc import run_multiqc
from aisynbiopipeline.limsapi.googledrive import upload_or_replace

# Import Celery tasks
from aisynbiopipeline.tasks.fastp_task import fastp as fastp_task

LOG_FILE = Path(__file__).resolve().parent / 'pipeline.log'
ANALYSIS_HOME_ROOT = Path('/storage/nspahr/lib_analysis')
MULTIQC_DRIVE_FOLDER = '19gvG0_brALNGVIKR-OALZpQRoIzd3xEH'

DEFAULT_WAIT_POLL = 60 * 5  # 5 min
DEFAULT_WAIT_TIMEOUT = 60 * 60 * 24  # 24 hour per phase default


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
    parser = argparse.ArgumentParser(
        description='Run fastp and MultiQC on all Illumina samples in a seqorder.'
    )
    parser.add_argument('seqorder', help='Sequencing order name')

    # fastp options
    parser.add_argument('--fastp-threads', type=int, default=16, help='Threads for fastp')
    parser.add_argument('--fastp-polyG', type=int, default=10, help='polyG minimum length')

    # waiting
    parser.add_argument('--wait-poll', type=int, default=DEFAULT_WAIT_POLL, help='Poll interval seconds')
    parser.add_argument('--wait-timeout', type=int, default=DEFAULT_WAIT_TIMEOUT, help='Per-phase timeout seconds')

    return parser.parse_args()


def ensure_received_present(seqorder_name: str, logger) -> Library:
    seqorder = SeqOrder(seqorder_name)
    illumina = Library(seqorder, 'Illumina')
    received = illumina.path / 'received'
    if not received.exists():
        raise FileNotFoundError(f'Received folder missing: {received}')
    fastqs = list(received.glob('*.fastq*'))
    if len(fastqs) == 0:
        raise FileNotFoundError(f'No fastq files found in received: {received}')
    logger.info('Found %d fastq files in %s', len(fastqs), received)
    return illumina


def submit_fastp_tasks(manifest: pd.DataFrame, illumina: Library, threads: int, polyG: int, logger) -> List:
    tasks = []
    for _, row in manifest.iterrows():
        sample = row['sample_name']
        fwd = row.get('R1')
        rvs = row.get('R2')
        if not fwd or not rvs:
            logger.warning('Skipping sample %s: missing R1/R2 in manifest', sample)
            continue
        # define outputs in trimmed folder
        trimmed_dir = illumina.path / 'trimmed'
        trimmed_dir.mkdir(exist_ok=True)
        out_fwd = trimmed_dir / Path(fwd).name.replace('_R1', '_R1_trimmed')
        out_rvs = trimmed_dir / Path(rvs).name.replace('_R2', '_R2_trimmed')

        logger.info('Submitting fastp for sample %s: %s %s -> %s %s', sample, fwd, rvs, out_fwd, out_rvs)
        async_res = fastp_task.apply_async((str(fwd), str(rvs), str(out_fwd), str(out_rvs), threads, polyG))
        tasks.append({'sample': sample, 'task': async_res, 'out_fwd': out_fwd, 'out_rvs': out_rvs})
    return tasks


def wait_for_tasks(tasks, poll_interval: int, timeout: int, logger, phase_name: str) -> None:
    start = time.time()
    pending = tasks.copy()
    while pending:
        for t in pending[:]:
            res = t['task']
            state = res.state
            if state == 'SUCCESS':
                logger.info('%s task success for sample %s', phase_name, t['sample'])
                pending.remove(t)
            elif state in ('FAILURE', 'REVOKED'):
                logger.error('%s task failed for sample %s: state=%s', phase_name, t['sample'], state)
                raise RuntimeError(f'{phase_name} task failed for sample {t["sample"]}, state={state}')
            # else still pending or started
        if pending and (time.time() - start) > timeout:
            raise TimeoutError(f'Timeout while waiting for {phase_name} tasks after {timeout} seconds')
        if pending:
            logger.info('Waiting for %d %s tasks...', len(pending), phase_name)
            time.sleep(poll_interval)


def main():
    args = parse_args()
    logger = configure_logging()

    seqorder_name = args.seqorder

    illumina = ensure_received_present(seqorder_name, logger)

    # create trimmed folder
    illumina.create_subfolder('trimmed')

    # create manifest of received
    received_manifest = illumina.create_manifest('received')
    if received_manifest.empty:
        raise FileNotFoundError('No samples found in received folder')

    # Submit fastp tasks
    fastp_tasks = submit_fastp_tasks(received_manifest, illumina, args.fastp_threads, args.fastp_polyG, logger)
    if not fastp_tasks:
        raise RuntimeError('No fastp tasks were submitted')

    # Wait for fastp completion
    wait_for_tasks(fastp_tasks, args.wait_poll, args.wait_timeout, logger, 'fastp')

    # Run multiqc on trimmed
    trimmed_folder = illumina.path / 'trimmed'
    multiqc_report = run_multiqc(str(trimmed_folder))
    logger.info('MultiQC report created at %s', multiqc_report)

    # copy multiqc to analysis home and upload to drive
    analysis_dir = ANALYSIS_HOME_ROOT / seqorder_name
    analysis_dir.mkdir(parents=True, exist_ok=True)
    dest_multiqc = analysis_dir / (seqorder_name + '_trimmed_multiqc_report.html')
    shutil.copy2(multiqc_report, dest_multiqc)
    logger.info('Copied MultiQC report to %s', dest_multiqc)

    try:
        upload_or_replace(dest_multiqc, MULTIQC_DRIVE_FOLDER)
        logger.info('Uploaded MultiQC report to Google Drive folder %s', MULTIQC_DRIVE_FOLDER)
    except Exception as exc:
        logger.error('Failed to upload MultiQC report to Google Drive: %s', exc)

    logger.info('Fastp and MultiQC completed for seqorder %s', seqorder_name)


if __name__ == '__main__':
    main()
