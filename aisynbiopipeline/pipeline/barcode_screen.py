#!/usr/bin/env python3
"""Barcode extractor for amplicon or WGS reads.

Usage:
  barcode_screen.py <reads_folder> <extracted_dir> <summary_dir> [fnames_must_contain] [--library LIBRARY]

This script scans FASTQ and FASTA files for anchor sequences, recovers barcode
pairs (verA, verB), and writes per-read results to CSV. The verA/verB barcode
reference is pulled from the Library_candidates table in the LIMS database
(rows where Library == the --library value, default 'verABLib_large').
Extracted reads with barcodes are written to extracted_dir/ (in the same format
as their input file: FASTQ in -> FASTQ out, FASTA in -> FASTA out).
Combined results and summary stats are written to summary_dir/.
Only processes read files containing the optional fnames_must_contain string.

Output CSV columns: sample_name, read_id, verA, verB
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, Tuple
import pandas as pd
import edlib
import gzip
from Bio import SeqIO
from Bio.Seq import Seq

# Add parent directory to path so the limsapi package is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from limsapi.query import query_table

# Anchor sequences (kept from original script)
ANCHOR_B_BEFORE = "GCGGAAAGTGTGAGGCGCTT".upper()
ANCHOR_BETWEEN = "CGGC".upper()
ANCHOR_A_AFTER = "CTCTAGAAATAATTTTGTTT".upper()

# Library_candidates.Library value holding the verA/verB barcode reference.
DEFAULT_LIBRARY = 'verABLib_large'
LIBRARY_CANDIDATES_TABLE = 'Library_candidates'

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
    parser.add_argument('fastq_folder', help='Path to folder containing FASTQ and/or FASTA files')
    parser.add_argument('extracted_dir', help='Path to output folder for extracted reads and per-fastq CSVs')
    parser.add_argument('summary_dir', help='Path to output folder for combined CSV and summary stats')
    parser.add_argument('fnames_must_contain', nargs='?', default=None, help='Optional string to filter fastq filenames; only files containing this string are processed')
    parser.add_argument('--library', default=DEFAULT_LIBRARY, help=f'Library_candidates.Library value to pull barcodes from (default: {DEFAULT_LIBRARY})')
    return parser.parse_args()


def reverse_complement(seq: str) -> str:
    return str(Seq(seq).reverse_complement())


# Recognized read-file extensions, longest-first so compound (.gz) suffixes match
# before their bare counterparts. FASTA files are quality-less; extracted reads
# from a FASTA input are written back out as FASTA.
FASTQ_EXTS = ['.fastq.gz', '.fq.gz', '.fastq', '.fq']
FASTA_EXTS = ['.fasta.gz', '.fa.gz', '.fna.gz', '.fasta', '.fa', '.fna']
READ_EXTS = FASTQ_EXTS + FASTA_EXTS


def detect_format(path: Path) -> str:
    """Return 'fastq' or 'fasta' based on the file's extension.

    Defaults to 'fastq' for unrecognized extensions (backwards-compatible).
    """
    name = path.name.lower()
    if any(name.endswith(ext) for ext in FASTA_EXTS):
        return 'fasta'
    return 'fastq'


def append_suffix_to_filename(path: Path, suffix: str) -> Path:
    name = path.name
    for ext in READ_EXTS:
        if name.endswith(ext):
            return path.with_name(name[: -len(ext)] + suffix + ext)
    return path.with_name(name + suffix)


def base_name_without_fastq_ext(path: Path) -> str:
    name = path.name
    for ext in READ_EXTS:
        if name.endswith(ext):
            return name[: -len(ext)]
    return path.stem


def load_barcodes(library: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Pull the verA/verB barcode reference from the Library_candidates table.

    Reads rows from Library_candidates where Library == ``library`` and builds
    two lookups mapping barcode sequence -> feature_number, one for verA and one
    for verB features.
    """
    rows = query_table(LIBRARY_CANDIDATES_TABLE, filters={'Library': library})
    if not rows:
        raise ValueError(
            f"No rows found in {LIBRARY_CANDIDATES_TABLE} for Library == '{library}'"
        )

    barcodes_A: Dict[str, str] = {}
    barcodes_B: Dict[str, str] = {}

    for row in rows:
        # Normalize DB column names (Feature_type, Feature_number, Barcode) to
        # lowercase so lookups are case-insensitive.
        r = {str(k).lower(): v for k, v in row.items()}
        typ = str(r.get('feature_type', '')).strip()
        alias = str(r.get('feature_alias', '')).strip()
        bc = str(r.get('barcode', '')).strip().upper()
        if not bc or bc.lower() == 'nan':
            continue
        if typ == 'verA':
            barcodes_A[bc] = alias
        elif typ == 'verB':
            barcodes_B[bc] = alias
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
    fmt = detect_format(fq)
    sample_name = base_name_without_fastq_ext(fq)
    for marker in ('_R1', '_R2', '_illumina', '_trimmed'):
        sample_name = sample_name.replace(marker, '')
    sample_name = sample_name.rstrip('_')
    total_reads = 0
    anchors_found = 0
    total_bases = 0
    barcode_bases = 0
    matched_records = []
    matched_reads = []

    logger.info('Processing sample %s (%s)', fname, fmt)
    try:
        if str(fq).endswith('.gz'):
            handle = gzip.open(str(fq), 'rt')
        else:
            handle = open(str(fq), 'r')
        with handle:
            for rec in SeqIO.parse(handle, fmt):
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
                        'verA': ver_a if ver_a is not None else None,
                        'verB': ver_b if ver_b is not None else None,
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
        output_reads = append_suffix_to_filename(extract_dir / fname, '_BCextracted')
        csv_base = base_name_without_fastq_ext(Path(fname))
        output_csv = extract_dir / f'{csv_base}_BCextracted.csv'
        SeqIO.write(matched_reads, str(output_reads), fmt)
        pd.DataFrame.from_records(matched_records).to_csv(output_csv, index=False)
        logger.info('Wrote %d extracted reads to %s and records to %s', len(matched_reads), output_reads, output_csv)

    negative_reads = total_reads - anchors_found
    negative_bases = total_bases - barcode_bases
    mean_barcode_negative_read_length = round(negative_bases / negative_reads) if negative_reads else 0
    mean_barcode_read_length = round(barcode_bases / anchors_found) if anchors_found else 0

    return matched_records, total_reads, anchors_found, mean_barcode_negative_read_length, mean_barcode_read_length, sample_name


def main():
    args = parse_args()
    logger = configure_logging()

    fastq_folder = Path(args.fastq_folder).resolve()
    library = args.library
    extracted_dir = Path(args.extracted_dir).resolve()
    summary_dir = Path(args.summary_dir).resolve()
    fnames_filter = args.fnames_must_contain

    logger.info('Starting amplicons extraction from %s', fastq_folder)

    if not fastq_folder.exists() or not fastq_folder.is_dir():
        raise FileNotFoundError(f'FASTQ folder not found: {fastq_folder}')

    extracted_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    fastq_files = sorted(
        f for f in fastq_folder.glob('*')
        if f.is_file() and any(f.name.lower().endswith(ext) for ext in READ_EXTS)
    )
    if fnames_filter:
        fastq_files = [f for f in fastq_files if fnames_filter in f.name]
    if not fastq_files:
        raise FileNotFoundError(f'No fastq/fasta files found in folder: {fastq_folder}')

    logger.info('Found %d read files in %s', len(fastq_files), fastq_folder)

    # load barcodes from the Library_candidates table
    try:
        barcodes_A, barcodes_B = load_barcodes(library)
    except Exception as exc:
        logger.error('Failed to load barcodes from database (Library == %s): %s', library, exc)
        raise

    logger.info(
        "Loaded %d A barcodes and %d B barcodes from %s (Library == '%s')",
        len(barcodes_A), len(barcodes_B), LIBRARY_CANDIDATES_TABLE, library,
    )

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
