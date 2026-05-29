#!/usr/bin/env python3
"""Amplicon barcode extractor for Illumina trimmed reads.

Usage:
  amplicons.py <seqorder> <barcode_csv> [filename_prefix]

This script scans trimmed Illumina FASTQ files for anchor sequences,
recovers barcode pairs (verA, verB) using a barcode CSV, and writes
per-read results to a CSV in the analysis folder for the seqorder.

Output CSV columns: Sample, verA, verB
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Dict, Tuple
import pandas as pd
import edlib
import gzip
from Bio import SeqIO
from Bio.Seq import Seq

# Anchor sequences (kept from original script)
ANCHOR_B_BEFORE = "GCGGAAAGTGTGAGGCGCTT".upper()
ANCHOR_BETWEEN = "CGGC".upper()
ANCHOR_A_AFTER = "CTCTAGAAATAATTTTGTTT".upper()

ANALYSIS_HOME_ROOT = Path('/storage/nspahr/lib_analysis')
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
    parser = argparse.ArgumentParser(description='Extract amplicon barcodes from trimmed reads')
    parser.add_argument('seqorder', help='Sequencing order name')
    parser.add_argument('barcode_csv', help='CSV with barcodes (columns: feature_type, feature_number, feature_name, barcode)')
    parser.add_argument('filename_prefix', nargs='?', default=None, help='Optional output filename prefix')
    return parser.parse_args()


def reverse_complement(seq: str) -> str:
    return str(Seq(seq).reverse_complement())


def load_barcodes(csv_path: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    df = pd.read_csv(csv_path)
    required = {'feature_type', 'feature_number', 'feature_name', 'barcode'}
    if not required.issubset(set(df.columns)):
        raise ValueError(f'Barcode CSV missing required columns. Required: {required}')

    barcodes_A: Dict[str, str] = {}
    barcodes_B: Dict[str, str] = {}

    for _, row in df.iterrows():
        typ = str(row['feature_type']).strip()
        num = str(row['feature_number']).strip()
        bc = str(row['barcode']).strip().upper()
        if not bc:
            continue
        if typ == 'verA':
            barcodes_A[bc] = num
        elif typ == 'verB':
            barcodes_B[bc] = num
        else:
            # ignore unknown types
            continue

    return barcodes_A, barcodes_B


def process_read(seq: str, barcodes_A: Dict[str, str], barcodes_B: Dict[str, str]) -> Tuple[str | None, str | None]:
    # Align anchors with allowed error on big anchors and exact middle anchor
    res_before = edlib.align(ANCHOR_B_BEFORE, seq, mode="HW", task="path")
    res_after = edlib.align(ANCHOR_A_AFTER, seq, mode="HW", task="path")

    if res_before.get('editDistance') is None or res_after.get('editDistance') is None:
        return None, None

    err_before = res_before['editDistance']
    err_after = res_after['editDistance']

    if err_before <= len(ANCHOR_B_BEFORE) * 0.2 and err_after <= len(ANCHOR_A_AFTER) * 0.2:
        # extract region between anchors
        start_idx = res_before['locations'][0][1] + 1
        end_idx = res_after['locations'][-1][0]
        if start_idx < end_idx and (end_idx - start_idx) < 200:
            mid_seq = seq[start_idx:end_idx]
            res_mid = edlib.align(ANCHOR_BETWEEN, mid_seq, mode="HW", task="path")
            if res_mid.get('editDistance') == 0:
                cg_start = res_mid['locations'][0][0]
                cg_end = res_mid['locations'][0][1] + 1
                bc_b_seq = mid_seq[:cg_start]
                bc_a_seq = mid_seq[cg_end:]
                ver_a = barcodes_A.get(bc_a_seq)
                ver_b = barcodes_B.get(bc_b_seq)
                return ver_a, ver_b
    return None, None


def main():
    args = parse_args()
    logger = configure_logging()
    logger.info('Starting amplicons extraction for seqorder %s', args.seqorder)

    seqorder = args.seqorder
    barcode_csv = args.barcode_csv
    prefix = args.filename_prefix or seqorder

    # locate trimmed folder
    seqorder_obj = None
    try:
        from aisynbiopipeline.workflows.seq_folder_utils import SeqOrder, Library
        seqorder_obj = SeqOrder(seqorder)
        illumina = Library(seqorder_obj, 'Illumina')
    except Exception as exc:
        logger.error('Failed to load seqorder/illumina library: %s', exc)
        raise

    trimmed = illumina.path / 'trimmed'
    if not trimmed.exists():
        raise FileNotFoundError(f'Trimmed folder not found: {trimmed}')

    fastq_files = sorted(trimmed.glob('*.fastq*'))
    if not fastq_files:
        raise FileNotFoundError(f'No fastq files found in trimmed folder: {trimmed}')

    logger.info('Found %d fastq files in %s', len(fastq_files), trimmed)

    # load barcodes
    try:
        barcodes_A, barcodes_B = load_barcodes(barcode_csv)
    except Exception as exc:
        logger.error('Failed to load barcode CSV: %s', exc)
        raise

    logger.info('Loaded %d A barcodes and %d B barcodes', len(barcodes_A), len(barcodes_B))

    records = []
    for fq in fastq_files:
        # derive sample name without common fastq extensions
        fname = fq.name
        sample_name = fname.replace('.fastq.gz', '').replace('.fq.gz', '').replace('.fastq', '').replace('.fq', '')
        total_reads = 0
        anchors_found = 0
        logger.info('Processing sample %s', sample_name)
        try:
            # open gzipped or plain fastq transparently
            if str(fq).endswith('.gz'):
                handle = gzip.open(str(fq), 'rt')
            else:
                handle = open(str(fq), 'r')
            with handle:
                for rec in SeqIO.parse(handle, 'fastq'):
                    total_reads += 1
                    seq = str(rec.seq).upper()
                    ver_a, ver_b = process_read(seq, barcodes_A, barcodes_B)
                    if ver_a is None or ver_b is None:
                        # try reverse complement
                        ver_a, ver_b = process_read(reverse_complement(seq), barcodes_A, barcodes_B)
                    if ver_a is not None or ver_b is not None:
                        anchors_found += 1
                        records.append({'Sample': sample_name, 'verA': ver_a, 'verB': ver_b})
                    if total_reads % 1000000 == 0:
                        logger.info('  Processed %d reads for sample %s', total_reads, sample_name)
        except Exception as exc:
            logger.error('Failed processing fastq %s: %s', fq, exc)
            raise

        logger.info('Sample %s: total_reads=%d anchors_found=%d', sample_name, total_reads, anchors_found)
        
    # write results to analysis folder
    analysis_dir = ANALYSIS_HOME_ROOT / seqorder
    analysis_dir.mkdir(parents=True, exist_ok=True)
    out_csv = analysis_dir / f"{prefix}_amplicons_reads.csv"

    df = pd.DataFrame.from_records(records)
    df.to_csv(out_csv, index=False)
    logger.info('Wrote %d records to %s', len(df), out_csv)
    logger.info('Amplicon extraction completed for seqorder %s', seqorder)


if __name__ == '__main__':
    main()
