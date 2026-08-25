#!/usr/bin/env python3
"""Amplicon extractor for primer-flanked reads.

Usage:
  amplicon_screen.py <fastq_folder> <fwd_primer> <rev_primer> <extracted_dir> <summary_dir> [fnames_must_contain]

This script scans FASTQ files for a forward/reverse primer pair, extracts the
primer-bound amplicon (the region flanked by the two primers, primers included),
and writes the extracted reads per fastq to extracted_dir/.
Summary statistics per sample are written to summary_dir/.

Primers are matched with fuzzy alignment (edlib HW, ~20% allowed error) on both
strands. The forward primer is expected on the sense strand and the reverse
primer is supplied 5'->3' on the antisense strand (its footprint on the sense
read is its reverse complement). A read counts as "with primers" only when BOTH
primers are found.

Summary CSV columns:
  sample name, total reads, reads with primers, percent reads with primers,
  mean read length of reads with primers, mean read length of reads without primers
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional, Tuple
import pandas as pd
import edlib
import gzip
from Bio import SeqIO
from Bio.Seq import Seq

# Fraction of primer length allowed as edit distance when matching.
PRIMER_MAX_ERROR_RATE = 0.2

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
    parser = argparse.ArgumentParser(description='Extract primer-bound amplicons from reads')
    parser.add_argument('fastq_folder', help='Path to folder containing FASTQ files')
    parser.add_argument('fwd_primer', help='Forward primer sequence (5\'->3\', sense strand)')
    parser.add_argument('rev_primer', help='Reverse primer sequence (5\'->3\', antisense strand)')
    parser.add_argument('extracted_dir', help='Path to output folder for extracted reads')
    parser.add_argument('summary_dir', help='Path to output folder for summary stats')
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


def sample_name_from_filename(fname: str) -> str:
    return (
        fname.replace('.fastq.gz', '').replace('.fq.gz', '').replace('.fastq', '').replace('.fq', '')
        .replace('_R1', '').replace('_R2', '').replace('_illumina', '').replace('_trimmed', '')
        .rstrip('_')
    )


def find_amplicon(seq: str, fwd: str, rc_rev: str, max_err_fwd: int, max_err_rev: int) -> Optional[Tuple[int, int]]:
    """Locate the primer-bound region on a single strand of ``seq``.

    Searches for the forward primer and the reverse complement of the reverse
    primer. Returns (start, end) spanning from the start of the forward primer
    to the end of the reverse primer footprint (both primers included), or None
    if either primer is missing or the ordering is inconsistent.
    """
    res_fwd = edlib.align(fwd, seq, mode='HW', task='locations')
    res_rev = edlib.align(rc_rev, seq, mode='HW', task='locations')

    if res_fwd.get('editDistance', -1) < 0 or res_rev.get('editDistance', -1) < 0:
        return None
    if res_fwd['editDistance'] > max_err_fwd or res_rev['editDistance'] > max_err_rev:
        return None
    if not res_fwd.get('locations') or not res_rev.get('locations'):
        return None

    # Forward primer: first (5'-most) hit. Reverse footprint: last (3'-most) hit.
    fwd_start = res_fwd['locations'][0][0]
    rev_end = res_rev['locations'][-1][1] + 1

    if fwd_start >= rev_end:
        return None

    return fwd_start, rev_end


def primer_present(primer: str, seq: str, rc_seq: str, max_err: int) -> bool:
    """Return True if ``primer`` is found (within max_err) on either strand."""
    for target in (seq, rc_seq):
        res = edlib.align(primer, target, mode='HW', task='distance')
        dist = res.get('editDistance', -1)
        if dist is not None and 0 <= dist <= max_err:
            return True
    return False


def process_fastq(
    fq: Path,
    fwd: str,
    rev: str,
    extract_dir: Path,
    logger: logging.Logger,
) -> tuple[dict, list, list, list, list]:
    fname = fq.name
    sample_name = sample_name_from_filename(fname)
    rc_rev = reverse_complement(rev)
    max_err_fwd = int(len(fwd) * PRIMER_MAX_ERROR_RATE)
    max_err_rev = int(len(rev) * PRIMER_MAX_ERROR_RATE)

    # "left" primer == forward primer; "right" primer == reverse primer.
    total_reads = 0
    both_reads = both_bases = 0
    left_reads = left_bases = 0
    right_reads = right_bases = 0
    none_reads = none_bases = 0
    extracted_records = []
    both_primer_records = []
    left_primer_records = []
    right_primer_records = []
    no_primer_records = []

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
                seq = str(rec.seq).upper()
                rc_seq = reverse_complement(seq)

                region = find_amplicon(seq, fwd, rc_rev, max_err_fwd, max_err_rev)
                strand = '+'
                if region is None:
                    rc_region = find_amplicon(rc_seq, fwd, rc_rev, max_err_fwd, max_err_rev)
                    if rc_region is not None:
                        region = rc_region
                        strand = '-'

                fwd_found = primer_present(fwd, seq, rc_seq, max_err_fwd)
                rev_found = primer_present(rc_rev, seq, rc_seq, max_err_rev)

                if region is not None or (fwd_found and rev_found):
                    # Both primers present. Extract the amplicon when the two
                    # primers form a valid ordered pair on one strand.
                    both_reads += 1
                    both_bases += read_len
                    both_primer_records.append({
                        'sample_name': sample_name,
                        'read_id': rec.id,
                        'read_length': read_len,
                        'sequence': seq,
                    })
                    if region is not None:
                        start, end = region
                        source = rec if strand == '+' else rec.reverse_complement(id=rec.id, description=rec.description)
                        extracted_records.append(source[start:end])
                elif fwd_found:
                    left_reads += 1
                    left_bases += read_len
                    left_primer_records.append({
                        'sample_name': sample_name,
                        'read_id': rec.id,
                        'read_length': read_len,
                        'sequence': seq,
                    })
                elif rev_found:
                    right_reads += 1
                    right_bases += read_len
                    right_primer_records.append({
                        'sample_name': sample_name,
                        'read_id': rec.id,
                        'read_length': read_len,
                        'sequence': seq,
                    })
                else:
                    none_reads += 1
                    none_bases += read_len
                    no_primer_records.append({
                        'sample_name': sample_name,
                        'read_id': rec.id,
                        'read_length': read_len,
                        'sequence': seq,
                    })

                if total_reads % 1000000 == 0:
                    logger.info('  Processed %d reads for file %s', total_reads, fname)
    except Exception as exc:
        logger.error('Failed processing fastq %s: %s', fq, exc)
        raise

    logger.info(
        'Sample %s: total_reads=%d both=%d left_only=%d right_only=%d none=%d',
        sample_name, total_reads, both_reads, left_reads, right_reads, none_reads,
    )

    if extracted_records:
        output_fastq = append_suffix_to_filename(extract_dir / fname, '_amplicon')
        SeqIO.write(extracted_records, str(output_fastq), 'fastq')
        logger.info('Wrote %d extracted amplicons to %s', len(extracted_records), output_fastq)

    def pct(n: int) -> int:
        return round(n / total_reads * 100) if total_reads else 0

    def mean_len(bases: int, n: int) -> int:
        return round(bases / n) if n else 0

    summary_row = {
        'sample name': sample_name,
        'total reads': total_reads,
        'reads with primers': both_reads,
        'percent reads with primers': pct(both_reads),
        'reads with left primer only': left_reads,
        'percent reads with left primer only': pct(left_reads),
        'reads with right primer only': right_reads,
        'percent reads with right primer only': pct(right_reads),
        'reads without primers': none_reads,
        'percent reads without primers': pct(none_reads),
        'mean read length of reads with primers': mean_len(both_bases, both_reads),
        'mean read length of left-primer-only reads': mean_len(left_bases, left_reads),
        'mean read length of right-primer-only reads': mean_len(right_bases, right_reads),
        'mean read length of reads without primers': mean_len(none_bases, none_reads),
    }

    return summary_row, both_primer_records, left_primer_records, right_primer_records, no_primer_records


def main():
    args = parse_args()
    logger = configure_logging()

    fastq_folder = Path(args.fastq_folder).resolve()
    fwd = args.fwd_primer.strip().upper()
    rev = args.rev_primer.strip().upper()
    extracted_dir = Path(args.extracted_dir).resolve()
    summary_dir = Path(args.summary_dir).resolve()
    fnames_filter = args.fnames_must_contain

    logger.info('Starting amplicon extraction from %s', fastq_folder)

    if not fastq_folder.exists() or not fastq_folder.is_dir():
        raise FileNotFoundError(f'FASTQ folder not found: {fastq_folder}')
    if not fwd or not rev:
        raise ValueError('Both forward and reverse primer sequences must be non-empty')

    extracted_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    fastq_files = sorted(fastq_folder.glob('*.fastq*'))
    if fnames_filter:
        fastq_files = [f for f in fastq_files if fnames_filter in f.name]
    if not fastq_files:
        raise FileNotFoundError(f'No fastq files found in folder: {fastq_folder}')

    logger.info('Found %d fastq files in %s', len(fastq_files), fastq_folder)
    logger.info('Forward primer: %s (len %d), Reverse primer: %s (len %d)', fwd, len(fwd), rev, len(rev))

    summary_rows = []
    all_both_records = []
    all_left_records = []
    all_right_records = []
    all_no_primer_records = []
    for fq in fastq_files:
        summary_row, both_records, left_records, right_records, no_primer_records = process_fastq(
            fq, fwd, rev, extracted_dir, logger
        )
        summary_rows.append(summary_row)
        all_both_records.extend(both_records)
        all_left_records.extend(left_records)
        all_right_records.extend(right_records)
        all_no_primer_records.extend(no_primer_records)

    out_suffix = f"_{fnames_filter}" if fnames_filter else ""
    summary_csv = summary_dir / f'amplicon_summary_stats{out_suffix}.csv'
    pd.DataFrame.from_records(summary_rows).to_csv(summary_csv, index=False)
    logger.info('Wrote summary stats for %d samples to %s', len(summary_rows), summary_csv)

    # Combined per-category read CSVs across all samples (sample_name column
    # distinguishes source sample).
    read_csv_columns = ['sample_name', 'read_id', 'read_length', 'sequence']
    for records, out_name in (
        (all_both_records, 'both_primer_reads.csv'),
        (all_left_records, 'left_primer_reads.csv'),
        (all_right_records, 'right_primer_reads.csv'),
        (all_no_primer_records, 'no_primer_reads.csv'),
    ):
        out_path = summary_dir / out_name
        pd.DataFrame.from_records(records, columns=read_csv_columns).to_csv(out_path, index=False)
        logger.info('Wrote %d reads to %s', len(records), out_path)

    logger.info('Amplicon extraction completed')


if __name__ == '__main__':
    main()
