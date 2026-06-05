"""Barcode extraction functions
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


ANCHOR_B_BEFORE = "GCGGAAAGTGTGAGGCGCTT".upper()
ANCHOR_BETWEEN = "CGGC".upper()
ANCHOR_A_AFTER = "CTCTAGAAATAATTTTGTTT".upper()

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
) -> list[dict]:
    fq = Path(fq) if type(fq)==str else fq
    fname = fq.name
    extract_dir = Path(extract_dir) if type(extract_dir)==str else extract_dir
    sample_name = fname.replace('.fastq.gz', '').replace('.fq.gz', '').replace('.fastq', '').replace('.fq', '').replace('_R1', '').replace('_1', '').replace('_illumina', '').replace('_trimmed', "").replace('_R2', '').replace('_2', '').rstrip('_')
    total_reads = 0
    anchors_found = 0
    matched_records = []
    matched_reads = []

    try:
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
                    ver_a, ver_b = process_read(reverse_complement(seq), barcodes_A, barcodes_B)
                if ver_a is not None or ver_b is not None:
                    anchors_found += 1
                    record = {
                        'sample_name': sample_name,
                        'read_id': rec.id,
                        'verA': f'A{ver_a}' if ver_a is not None else None,
                        'verB': f'B{ver_b}' if ver_b is not None else None,
                    }
                    matched_records.append(record)
                    matched_reads.append(rec)
    except Exception as exc:
        raise


    if matched_reads:
        output_fastq = append_suffix_to_filename(extract_dir / fname, '_BCextracted')
        csv_base = base_name_without_fastq_ext(Path(fname))
        output_csv = extract_dir / f'{csv_base}_BCextracted.csv'
        SeqIO.write(matched_reads, str(output_fastq), 'fastq')
        pd.DataFrame.from_records(matched_records).to_csv(output_csv, index=False)

    return matched_records
