#!/usr/bin/env python3
"""Barcode extractor for amplicon or WGS reads.

Usage:
  barcode_screen.py <fastq_folder> <barcode_csv> <extracted_dir> <summary_dir> [fnames_must_contain]

This script scans FASTQ files for anchor sequences, recovers barcode pairs
(verA, verB) using a barcode CSV, and writes per-read results to CSV.
Extracted reads with barcodes are written to extracted_dir/.
Combined results and summary stats are written to summary_dir/.
Only processes fastq files containing the optional fnames_must_contain string.

Output CSV columns: sample_name, read_id, verA, verB
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
    parser.add_argument('fastq_folder', help='Path to folder containing FASTQ files')
    parser.add_argument('barcode_csv', help='CSV with barcodes (columns: feature_type, feature_number, feature_name, barcode)')
    parser.add_argument('extracted_dir', help='Path to output folder for extracted reads and per-fastq CSVs')
    parser.add_argument('summary_dir', help='Path to output folder for combined CSV and summary stats')
    parser.add_argument('fnames_must_contain', nargs='?', default=None, help='Optional string to filter fastq filenames; only files containing this string are processed')
    return parser.parse_args()


def reverse_complement(seq: str) -> str:
    return str(Seq(seq).reverse_complement())


def append_suffix_to_filename(path: Path, suffix: str) -> Path:
    name = path.name
    if name.endswith('.fastq.gz'):
        return path.with_name(name.replace('.fastq.gz', f'{suffix}.fastq.gz'))
    if name.endswith('.fq.gz'):
        return path.with_name(name.replace('.fq.gz', f'{suffix}.fq.gz'))
    if name.endswith('.fastq'):
        return path.with_name(name.replace('.fastq', f'{suffix}.fastq'))
    if name.endswith('.fq'):
        return path.with_name(name.replace('.fq', f'{suffix}.fq'))
    return path.with_name(name + suffix)


def base_name_without_fastq_ext(path: Path) -> str:
    name = path.name
    for ext in ['.fastq.gz', '.fq.gz', '.fastq', '.fq']:
        if name.endswith(ext):
            return name[: -len(ext)]
    return path.stem


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


def process_fastq(
    fq: Path,
    barcodes_A: Dict[str, str],
    barcodes_B: Dict[str, str],
    extract_dir: Path,
    logger: logging.Logger,
) -> tuple[list[dict], int, int, float, float, str]:
    fname = fq.name
    sample_name = fname.replace('.fastq.gz', '').replace('.fq.gz', '').replace('.fastq', '').replace('.fq', '').replace('_R1', '').replace('_illumina', '').replace('_trimmed', "").replace('_R2', '').rstrip('_')
    total_reads = 0
    anchors_found = 0
    total_bases = 0
    barcode_bases = 0
    matched_records = []
    matched_reads = []

    logger.info('Processing sample %s', fname)
    try:
        if str(fq).endswith('.gz'):
            handle = gzip.open(str(fq), 'rt')
        else:
            handle = open(str(fq), 'r')
        with handle:
            for rec in SeqIO.parse(handle, 'fastq'):
                total_reads += 1
                read_len = len(rec.seq)
                total_bases += read_len
                seq = str(rec.seq).upper()
                ver_a, ver_b = process_read(seq, barcodes_A, barcodes_B)
                if ver_a is None or ver_b is None:
                    ver_a, ver_b = process_read(reverse_complement(seq), barcodes_A, barcodes_B)
                if ver_a is not None or ver_b is not None:
                    anchors_found += 1
                    barcode_bases += read_len
                    record = {
                        'sample_name': sample_name,
                        'read_id': rec.id,
                        'verA': f'A{ver_a}' if ver_a is not None else None,
                        'verB': f'B{ver_b}' if ver_b is not None else None,
                    }
                    matched_records.append(record)
                    matched_reads.append(rec)
                if total_reads % 1000000 == 0:
                    logger.info('  Processed %d reads for file %s', total_reads, fname)
    except Exception as exc:
        logger.error('Failed processing fastq %s: %s', fq, exc)
        raise

    logger.info('Sample %s: total_reads=%d anchors_found=%d', sample_name, total_reads, anchors_found)

    if matched_reads:
        output_fastq = append_suffix_to_filename(extract_dir / fname, '_BCextracted')
        csv_base = base_name_without_fastq_ext(Path(fname))
        output_csv = extract_dir / f'{csv_base}_BCextracted.csv'
        SeqIO.write(matched_reads, str(output_fastq), 'fastq')
        pd.DataFrame.from_records(matched_records).to_csv(output_csv, index=False)
        logger.info('Wrote %d extracted reads to %s and records to %s', len(matched_reads), output_fastq, output_csv)

    negative_reads = total_reads - anchors_found
    negative_bases = total_bases - barcode_bases
    mean_barcode_negative_read_length = round(negative_bases / negative_reads) if negative_reads else 0
    mean_barcode_read_length = round(barcode_bases / anchors_found) if anchors_found else 0

    return matched_records, total_reads, anchors_found, mean_barcode_negative_read_length, mean_barcode_read_length, sample_name


def main():
    args = parse_args()
    logger = configure_logging()

    fastq_folder = Path(args.fastq_folder).resolve()
    barcode_csv = args.barcode_csv
    extracted_dir = Path(args.extracted_dir).resolve()
    summary_dir = Path(args.summary_dir).resolve()
    fnames_filter = args.fnames_must_contain

    logger.info('Starting amplicons extraction from %s', fastq_folder)

    if not fastq_folder.exists() or not fastq_folder.is_dir():
        raise FileNotFoundError(f'FASTQ folder not found: {fastq_folder}')

    extracted_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    fastq_files = sorted(fastq_folder.glob('*.fastq*'))
    if fnames_filter:
        fastq_files = [f for f in fastq_files if fnames_filter in f.name]
    if not fastq_files:
        raise FileNotFoundError(f'No fastq files found in folder: {fastq_folder}')

    logger.info('Found %d fastq files in %s', len(fastq_files), fastq_folder)

    # load barcodes
    try:
        barcodes_A, barcodes_B = load_barcodes(barcode_csv)
    except Exception as exc:
        logger.error('Failed to load barcode CSV: %s', exc)
        raise

    logger.info('Loaded %d A barcodes and %d B barcodes', len(barcodes_A), len(barcodes_B))

    records = []
    summary_rows = []
    for fq in fastq_files:
        matched_records, total_reads, anchors_found, mean_barcode_negative_read_length, mean_barcode_read_length, sample_name = process_fastq(
            fq, barcodes_A, barcodes_B, extracted_dir, logger
        )
        records.extend(matched_records)
        summary_rows.append(
            {
                'sample name': sample_name,
                'total reads': total_reads,
                'reads with barcodes': anchors_found,
                'percent reads with barcodes': round(anchors_found/total_reads*100),
                'mean barcode negative read length': mean_barcode_negative_read_length,
                'mean barcode positive read length': mean_barcode_read_length,
            }
        )

    # write results to summary folder
    out_suffix = f"_{fnames_filter}" if fnames_filter else ""
    out_csv = summary_dir / f"amplicons_reads{out_suffix}.csv"
    summary_csv = summary_dir / 'summary_stats.csv'

    df = pd.DataFrame.from_records(records)
    df.to_csv(out_csv, index=False)
    pd.DataFrame.from_records(summary_rows).to_csv(summary_csv, index=False)
    logger.info('Wrote %d records to %s', len(df), out_csv)
    logger.info('Wrote summary stats to %s', summary_csv)
    logger.info('Amplicon extraction completed')


if __name__ == '__main__':
    main()
