#!/usr/bin/env python3
"""Run breseq for all trimmed Illumina samples in a SeqOrder.

Usage:
  run_breseq.py <seqorder> <reference>
  run_breseq.py <seqorder> --sample-ref PREFIX=REFERENCE [--sample-ref PREFIX=REFERENCE ...]

Reference can be given in one of two mutually-exclusive ways:
- A single positional reference genome, applied to every sample in the
  seqorder (the original call_mutations.py behavior).
- One or more --sample-ref PREFIX=REFERENCE mappings, so that samples whose
  name starts with PREFIX are run against REFERENCE. Every trimmed sample
  must match exactly one prefix, and every prefix must match at least one
  sample, or the script errors out before submitting any jobs.

Example:
  run_breseq.py TFMN5 \\
      --sample-ref ANLstock.ACN3941=ACN2586.gbk \\
      --sample-ref ANLstock.ACN3943=ACN2821.gbk

The script:
- Verifies `seqorder` has an Illumina library with trimmed reads (run
  trim_reads.py first if not).
- Resolves and validates all requested reference genome(s) exist.
- Assigns each trimmed sample to a reference and validates the assignment
  is unambiguous and complete.
- Creates `breseq/` and runs `breseq` (via Celery tasks) for every sample.
- Waits for breseq tasks and creates a symlink in the analysis home to the
  breseq folder.

Notes:
- Defaults are conservative; you can override breseq params via CLI options.
"""

from __future__ import annotations

import sys
import argparse
import logging
import time
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

# Add workspace root to path so aisynbiopipeline can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from aisynbiopipeline.workflows.seq_folder_utils import SeqOrder, Library
from aisynbiopipeline.workflows.reference_utils import get_ref_genomes_path

# Import Celery tasks
from aisynbiopipeline.tasks.breseq_task import breseq as breseq_task

LOG_FILE = Path(__file__).resolve().parent / 'pipeline.log'
ANALYSIS_HOME_ROOT = Path('/storage/nspahr/lib_analysis')

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
        description='Run breseq on all trimmed Illumina samples in a seqorder.'
    )
    parser.add_argument('seqorder', help='Sequencing order name')
    parser.add_argument('reference', nargs='?', default=None,
                         help='Reference genome (filename or path) applied to ALL samples. '
                              'Mutually exclusive with --sample-ref.')
    parser.add_argument('--sample-ref', action='append', default=None, metavar='PREFIX=REFERENCE',
                         help='Assign samples whose name starts with PREFIX to REFERENCE (.gbk). '
                              'Repeatable. Mutually exclusive with the positional reference argument.')

    # breseq options
    parser.add_argument('--breseq-num-processors', type=int, default=4, help='Processors for breseq')
    parser.add_argument('--breseq-polymorphism-prediction', choices=('pop', 'con'), default='pop', help='polymorphism prediction mode')

    # waiting
    parser.add_argument('--wait-poll', type=int, default=DEFAULT_WAIT_POLL, help='Poll interval seconds')
    parser.add_argument('--wait-timeout', type=int, default=DEFAULT_WAIT_TIMEOUT, help='Per-phase timeout seconds')

    args = parser.parse_args()

    if args.reference and args.sample_ref:
        parser.error('Provide either a single reference argument or --sample-ref mappings, not both.')
    if not args.reference and not args.sample_ref:
        parser.error('Provide a reference argument or at least one --sample-ref PREFIX=REFERENCE mapping.')

    if args.sample_ref:
        parsed_map = {}
        for entry in args.sample_ref:
            if '=' not in entry:
                parser.error(f'--sample-ref must be of the form PREFIX=REFERENCE, got: {entry!r}')
            prefix, reference = entry.split('=', 1)
            if not prefix or not reference:
                parser.error(f'--sample-ref must be of the form PREFIX=REFERENCE, got: {entry!r}')
            if prefix in parsed_map:
                parser.error(f'Prefix {prefix!r} specified more than once in --sample-ref')
            parsed_map[prefix] = reference
        args.sample_ref = parsed_map

    return args


def ensure_trimmed_present(seqorder_name: str, logger) -> Library:
    seqorder = SeqOrder(seqorder_name)
    illumina = Library(seqorder, 'Illumina')
    trimmed = illumina.path / 'trimmed'
    if not trimmed.exists():
        raise FileNotFoundError(f'Trimmed folder missing: {trimmed}. Run trim_reads.py first.')
    fastqs = list(trimmed.glob('*.fastq*'))
    if len(fastqs) == 0:
        raise FileNotFoundError(f'No fastq files found in trimmed: {trimmed}. Run trim_reads.py first.')
    logger.info('Found %d fastq files in %s', len(fastqs), trimmed)
    return illumina


def resolve_reference_path(reference: str, logger) -> Path:
    ref_name = Path(reference).name
    if not ref_name.lower().endswith('.gbk'):
        ref_name = f'{ref_name}.gbk'

    ref_genomes_path = Path(get_ref_genomes_path())
    ref_path = ref_genomes_path / ref_name
    if not ref_path.exists():
        raise FileNotFoundError(f'Reference genome not found: {ref_path}')

    logger.info('Using reference genome: %s', ref_path)
    return ref_path


def resolve_reference_paths(raw_map: Dict[str, str], logger) -> Dict[str, Path]:
    """Resolve every PREFIX -> reference mapping, collecting all missing references before raising."""
    ref_genomes_path = Path(get_ref_genomes_path())
    resolved = {}
    missing = []
    for prefix, reference in raw_map.items():
        ref_name = Path(reference).name
        if not ref_name.lower().endswith('.gbk'):
            ref_name = f'{ref_name}.gbk'
        ref_path = ref_genomes_path / ref_name
        if not ref_path.exists():
            missing.append(str(ref_path))
            continue
        logger.info('Prefix %r -> reference genome %s', prefix, ref_path)
        resolved[prefix] = ref_path

    if missing:
        raise FileNotFoundError(f'Reference genome(s) not found: {missing}')

    return resolved


def assign_references(sample_names: List[str], resolved_refs: Dict[str, Path]) -> Tuple[Dict[str, Path], List[str], Dict[str, List[str]], set]:
    """Assign each sample to a reference by prefix match.

    Returns (assignment, unmatched_samples, ambiguous_samples, unused_prefixes).
    """
    assignment = {}
    unmatched = []
    ambiguous = {}
    used_prefixes = set()

    for sample in sample_names:
        matches = [prefix for prefix in resolved_refs if sample.startswith(prefix)]
        if not matches:
            unmatched.append(sample)
            continue
        if len(matches) > 1:
            ambiguous[sample] = matches
            continue
        prefix = matches[0]
        used_prefixes.add(prefix)
        assignment[sample] = resolved_refs[prefix]

    unused_prefixes = set(resolved_refs) - used_prefixes
    return assignment, unmatched, ambiguous, unused_prefixes


def build_reference_assignment(sample_names: List[str], args, logger) -> Dict[str, Path]:
    if args.sample_ref:
        resolved_refs = resolve_reference_paths(args.sample_ref, logger)
        assignment, unmatched, ambiguous, unused_prefixes = assign_references(sample_names, resolved_refs)

        problems = []
        if unused_prefixes:
            problems.append(f'--sample-ref prefixes matching no trimmed sample: {sorted(unused_prefixes)}')
        if ambiguous:
            problems.append(f'Samples matching more than one --sample-ref prefix: {ambiguous}')
        if unmatched:
            problems.append(f'Trimmed samples not matched by any --sample-ref prefix: {sorted(unmatched)}')
        if problems:
            raise ValueError('Invalid --sample-ref assignment:\n' + '\n'.join(problems))

        logger.info('Reference assignment: %s', {s: str(r) for s, r in assignment.items()})
        return assignment

    reference_path = resolve_reference_path(args.reference, logger)
    return {sample: reference_path for sample in sample_names}


def submit_breseq_tasks(manifest: pd.DataFrame, illumina: Library, reference_for_sample: Dict[str, Path], polymorphism_prediction: str, num_processors: int, logger) -> List:
    tasks = []
    for _, row in manifest.iterrows():
        sample = row['sample_name']
        fwd = row.get('R1')
        rvs = row.get('R2')
        if not fwd or not rvs:
            logger.warning('Skipping sample %s: missing R1/R2 in manifest', sample)
            continue
        read_paths = [str(fwd), str(rvs)]
        reference = reference_for_sample[sample]

        breseq_folder = illumina.path / 'breseq' / sample
        breseq_folder.mkdir(parents=True, exist_ok=True)

        logger.info('Submitting breseq for sample %s: reads=%s reference=%s -> folder=%s', sample, read_paths, reference, breseq_folder)
        async_res = breseq_task.apply_async((read_paths, str(reference), polymorphism_prediction, str(breseq_folder), 0, num_processors, 0.05))
        tasks.append({'sample': sample, 'task': async_res, 'breseq_folder': breseq_folder})
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

    illumina = ensure_trimmed_present(seqorder_name, logger)
    trimmed_manifest = illumina.create_manifest('trimmed')
    if trimmed_manifest.empty:
        raise FileNotFoundError('No samples found in trimmed folder')

    sample_names = trimmed_manifest['sample_name'].tolist()
    reference_for_sample = build_reference_assignment(sample_names, args, logger)

    # create breseq folder and submit breseq tasks
    illumina.create_subfolder('breseq')

    breseq_tasks = submit_breseq_tasks(trimmed_manifest, illumina, reference_for_sample, args.breseq_polymorphism_prediction, args.breseq_num_processors, logger)
    if not breseq_tasks:
        raise RuntimeError('No breseq tasks were submitted')

    wait_for_tasks(breseq_tasks, args.wait_poll, args.wait_timeout, logger, 'breseq')

    # create symlink in analysis home pointing to breseq folder
    analysis_dir = ANALYSIS_HOME_ROOT / seqorder_name
    analysis_dir.mkdir(parents=True, exist_ok=True)
    breseq_folder = illumina.path / 'breseq'
    symlink = analysis_dir / 'breseq'
    if symlink.exists() or symlink.is_symlink():
        symlink.unlink()
    symlink.symlink_to(breseq_folder)
    logger.info('Created symlink %s -> %s', symlink, breseq_folder)

    logger.info('All breseq jobs completed for seqorder %s', seqorder_name)


if __name__ == '__main__':
    main()
