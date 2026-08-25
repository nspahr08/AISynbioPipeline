#!/usr/bin/env python3
"""Trim amplicon reads down to a target gene flanked by two anchor sequences.

Usage:
  amplicon_trim.py <fastq_folder> <left_anchor> <right_anchor> <extracted_dir> <summary_dir> [fnames_must_contain] [--error-rate R]

Given a left and right anchor sequence (user-provided flanks on either side of a
target gene), each read is trimmed down to the target gene:

  * both anchors found  -> trim off the left anchor and everything 5' of it AND
                           the right anchor and everything 3' of it (target gene only)
  * left anchor only    -> trim off the left anchor and everything 5' of it
  * right anchor only   -> trim off the right anchor and everything 3' of it
  * neither anchor      -> read is discarded (not written to the extracted fastq)

Anchors are matched with fuzzy alignment (edlib HW, ~error-rate allowed error)
on both strands; reads whose anchors are found on the reverse strand are
reverse-complemented so all trimmed reads are written in a single (forward)
orientation. Trimmed reads are written per input fastq to extracted_dir/.

As in amplicon_screen.py, per-status read tables (combined across samples) and
per-sample summary statistics are written to summary_dir/:
  both_anchor_reads.csv, left_anchor_reads.csv, right_anchor_reads.csv,
  no_anchor_reads.csv, amplicon_trim_summary_stats.csv
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional, Tuple, List
import pandas as pd
import edlib
import gzip
from Bio import SeqIO
from Bio.Seq import Seq

# Fraction of anchor length allowed as edit distance when matching.
DEFAULT_ERROR_RATE = 0.2

# Ranking used to pick the read orientation with the strongest anchor detection.
STATUS_RANK = {'both': 3, 'left': 2, 'right': 2, 'none': 1}

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
    parser = argparse.ArgumentParser(description='Trim amplicon reads down to a target gene flanked by two anchors')
    parser.add_argument('fastq_folder', help='Path to folder containing FASTQ files')
    parser.add_argument('left_anchor', help="Left (5') anchor sequence flanking the target gene")
    parser.add_argument('right_anchor', help="Right (3') anchor sequence flanking the target gene")
    parser.add_argument('extracted_dir', help='Path to output folder for trimmed reads')
    parser.add_argument('summary_dir', help='Path to output folder for read tables and summary stats')
    parser.add_argument('fnames_must_contain', nargs='?', default=None, help='Optional string to filter fastq filenames; only files containing this string are processed')
    parser.add_argument('--error-rate', type=float, default=DEFAULT_ERROR_RATE, help=f'Max edit distance as a fraction of anchor length (default: {DEFAULT_ERROR_RATE})')
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


def sample_name_from_filename(fname: str) -> str:
    return (
        fname.replace('.fastq.gz', '').replace('.fq.gz', '').replace('.fastq', '').replace('.fq', '')
        .replace('_R1', '').replace('_R2', '').replace('_nanopore', '').replace('_illumina', '').replace('_trimmed', '')
        .rstrip('_')
    )


def find_anchor(seq: str, anchor: str, max_err: int, last: bool = False) -> Optional[Tuple[int, int]]:
    """Locate ``anchor`` in ``seq`` (edlib HW). Returns (start, end_inclusive) or None.

    Uses the 5'-most hit by default; set ``last=True`` for the 3'-most hit.
    """
    res = edlib.align(anchor, seq, mode='HW', task='locations')
    dist = res.get('editDistance', -1)
    if dist is None or dist < 0 or dist > max_err:
        return None
    locs = res.get('locations')
    if not locs:
        return None
    loc = locs[-1] if last else locs[0]
    return loc[0], loc[1]


def classify(seq: str, left: str, right: str, max_err_l: int, max_err_r: int):
    """Classify a single strand of ``seq`` and return (status, left_match, right_match).

    status is one of 'both', 'left', 'right', 'none'. Matches are (start, end_inclusive)
    tuples or None. For 'both' the left anchor must lie 5' of the right anchor.
    """
    left_match = find_anchor(seq, left, max_err_l, last=False)
    right_match = find_anchor(seq, right, max_err_r, last=True)

    if left_match and right_match and (left_match[1] + 1) <= right_match[0]:
        return 'both', left_match, right_match
    if left_match:
        return 'left', left_match, None
    if right_match:
        return 'right', None, right_match
    return 'none', None, None


def trim_indices(status: str, seq_len: int, left_match, right_match) -> Tuple[int, int]:
    """Return (start, end) slice indices for the target gene given the classification."""
    if status == 'both':
        return left_match[1] + 1, right_match[0]
    if status == 'left':
        return left_match[1] + 1, seq_len
    if status == 'right':
        return 0, right_match[0]
    return 0, seq_len


def process_fastq(
    fq: Path,
    left: str,
    right: str,
    error_rate: float,
    extract_dir: Path,
    logger: logging.Logger,
):
    fname = fq.name
    sample_name = sample_name_from_filename(fname)
    max_err_l = int(len(left) * error_rate)
    max_err_r = int(len(right) * error_rate)

    total_reads = 0
    # Per-status accumulators: count, summed input length, summed trimmed length.
    counts = {'both': 0, 'left': 0, 'right': 0, 'none': 0}
    in_bases = {'both': 0, 'left': 0, 'right': 0, 'none': 0}
    trim_bases = {'both': 0, 'left': 0, 'right': 0}

    trimmed_records = []
    records = {'both': [], 'left': [], 'right': [], 'none': []}

    logger.info('Processing sample %s', fname)
    try:
        if str(fq).endswith('.gz'):
            handle = gzip.open(str(fq), 'rt')
        else:
            handle = open(str(fq), 'r')
        with handle:
            for rec in SeqIO.parse(handle, 'fastq'):
                total_reads += 1
                input_len = len(rec.seq)
                seq = str(rec.seq).upper()
                rc_seq = reverse_complement(seq)

                f_status, fL, fR = classify(seq, left, right, max_err_l, max_err_r)
                r_status, rL, rR = classify(rc_seq, left, right, max_err_l, max_err_r)

                # Pick the orientation with the strongest anchor detection; prefer
                # forward on ties.
                if STATUS_RANK[r_status] > STATUS_RANK[f_status]:
                    status, left_match, right_match, strand = r_status, rL, rR, '-'
                    chosen_seq = rc_seq
                    source = rec.reverse_complement(id=rec.id, description=rec.description)
                else:
                    status, left_match, right_match, strand = f_status, fL, fR, '+'
                    chosen_seq = seq
                    source = rec

                counts[status] += 1
                in_bases[status] += input_len

                if status == 'none':
                    records['none'].append({
                        'sample_name': sample_name,
                        'read_id': rec.id,
                        'strand': '+',
                        'read_length': input_len,
                        'trimmed_length': '',
                        'sequence': seq,
                    })
                else:
                    start, end = trim_indices(status, len(chosen_seq), left_match, right_match)
                    trimmed_seq = chosen_seq[start:end]
                    trim_len = len(trimmed_seq)
                    trim_bases[status] += trim_len
                    if trim_len > 0:
                        trimmed_records.append(source[start:end])
                    records[status].append({
                        'sample_name': sample_name,
                        'read_id': rec.id,
                        'strand': strand,
                        'read_length': input_len,
                        'trimmed_length': trim_len,
                        'sequence': trimmed_seq,
                    })

                if total_reads % 1000000 == 0:
                    logger.info('  Processed %d reads for file %s', total_reads, fname)
    except Exception as exc:
        logger.error('Failed processing fastq %s: %s', fq, exc)
        raise

    logger.info(
        'Sample %s: total=%d both=%d left_only=%d right_only=%d none=%d',
        sample_name, total_reads, counts['both'], counts['left'], counts['right'], counts['none'],
    )

    if trimmed_records:
        output_fastq = append_suffix_to_filename(extract_dir / fname, '_trimmed')
        SeqIO.write(trimmed_records, str(output_fastq), 'fastq')
        logger.info('Wrote %d trimmed reads to %s', len(trimmed_records), output_fastq)

    def pct(n: int) -> int:
        return round(n / total_reads * 100) if total_reads else 0

    def mean(total: int, n: int) -> int:
        return round(total / n) if n else 0

    summary_row = {
        'sample name': sample_name,
        'total reads': total_reads,
        'reads with both anchors': counts['both'],
        'percent reads with both anchors': pct(counts['both']),
        'reads with left anchor only': counts['left'],
        'percent reads with left anchor only': pct(counts['left']),
        'reads with right anchor only': counts['right'],
        'percent reads with right anchor only': pct(counts['right']),
        'reads without anchors': counts['none'],
        'percent reads without anchors': pct(counts['none']),
        'mean input read length (both anchors)': mean(in_bases['both'], counts['both']),
        'mean trimmed length (both anchors)': mean(trim_bases['both'], counts['both']),
        'mean input read length (left anchor only)': mean(in_bases['left'], counts['left']),
        'mean trimmed length (left anchor only)': mean(trim_bases['left'], counts['left']),
        'mean input read length (right anchor only)': mean(in_bases['right'], counts['right']),
        'mean trimmed length (right anchor only)': mean(trim_bases['right'], counts['right']),
        'mean input read length (no anchors)': mean(in_bases['none'], counts['none']),
    }

    return summary_row, records['both'], records['left'], records['right'], records['none']


def main():
    args = parse_args()
    logger = configure_logging()

    fastq_folder = Path(args.fastq_folder).resolve()
    left = args.left_anchor.strip().upper()
    right = args.right_anchor.strip().upper()
    extracted_dir = Path(args.extracted_dir).resolve()
    summary_dir = Path(args.summary_dir).resolve()
    fnames_filter = args.fnames_must_contain
    error_rate = args.error_rate

    logger.info('Starting amplicon trimming from %s', fastq_folder)

    if not fastq_folder.exists() or not fastq_folder.is_dir():
        raise FileNotFoundError(f'FASTQ folder not found: {fastq_folder}')
    if not left or not right:
        raise ValueError('Both left and right anchor sequences must be non-empty')

    extracted_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    fastq_files = sorted(fastq_folder.glob('*.fastq*'))
    if fnames_filter:
        fastq_files = [f for f in fastq_files if fnames_filter in f.name]
    if not fastq_files:
        raise FileNotFoundError(f'No fastq files found in folder: {fastq_folder}')

    logger.info('Found %d fastq files in %s', len(fastq_files), fastq_folder)
    logger.info('Left anchor: %s (len %d), Right anchor: %s (len %d), error_rate=%.2f', left, len(left), right, len(right), error_rate)

    summary_rows = []
    all_both, all_left, all_right, all_none = [], [], [], []
    for fq in fastq_files:
        summary_row, both_r, left_r, right_r, none_r = process_fastq(
            fq, left, right, error_rate, extracted_dir, logger
        )
        summary_rows.append(summary_row)
        all_both.extend(both_r)
        all_left.extend(left_r)
        all_right.extend(right_r)
        all_none.extend(none_r)

    out_suffix = f"_{fnames_filter}" if fnames_filter else ""
    summary_csv = summary_dir / f'amplicon_trim_summary_stats{out_suffix}.csv'
    pd.DataFrame.from_records(summary_rows).to_csv(summary_csv, index=False)
    logger.info('Wrote summary stats for %d samples to %s', len(summary_rows), summary_csv)

    # Combined per-status read tables across all samples (sample_name distinguishes source).
    read_csv_columns = ['sample_name', 'read_id', 'strand', 'read_length', 'trimmed_length', 'sequence']
    for records, out_name in (
        (all_both, 'both_anchor_reads.csv'),
        (all_left, 'left_anchor_reads.csv'),
        (all_right, 'right_anchor_reads.csv'),
        (all_none, 'no_anchor_reads.csv'),
    ):
        out_path = summary_dir / out_name
        pd.DataFrame.from_records(records, columns=read_csv_columns).to_csv(out_path, index=False)
        logger.info('Wrote %d reads to %s', len(records), out_path)

    logger.info('Amplicon trimming completed')


if __name__ == '__main__':
    main()
