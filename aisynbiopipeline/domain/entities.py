"""Domain entities: Experiment, Sample, and the measurement joins.

This module is the SINGLE place where the (currently weak / free-text) links
between a sample and its measurements are encoded. A future database redesign
should only need to update :data:`JOIN_KEYS`.

Join keys and their provenance
------------------------------
* ``Measurements.Sample_ID == Samples.Name`` — VERIFIED from notebook usage
  (``APIExamples.ipynb`` queries ``Measurements`` filtered by ``Sample_ID``).
* ``Mutations.Seq_sample == Seq_samples.Sequencing_sample`` — VERIFIED:
  ``Create_mutation_table.ipynb`` builds ``Seq_sample`` from
  ``SeqSample.sample_name``, and ``SeqSample.sample_name`` is exactly the
  ``Sequencing_sample`` value passed in (see
  ``workflows/seq_folder_utils.py``).
* ``Robotic_OD.sample_name == Samples.Name`` — code-grounded: the OD pipeline
  maps the plate-layout ``Name`` onto each well's reading
  (``workflows/roboticALE.py``).
* ``Seq_samples.Sample_Name == Samples.Name`` — CONFIRMED against the real mirror
  DB on 2026-06-29 (≈0.98 of Seq_samples rows match a Samples.Name; the remainder
  are expected orphans/soft-deletes, not a wrong key).
* ``Copy_numbers.Seqsample`` / ``verAB_barcodes.Seqsample ==
  Seq_samples.Sequencing_sample`` — CONFIRMED against the real mirror DB on
  2026-06-29 (match rates ≈1.00 and 1.00).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# Keep the package-import convention used across the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from limsapi.query import query_to_dataframe


# Centralized join configuration. Change here (and only here) if the schema
# changes. See the module docstring for provenance of each key.
JOIN_KEYS: Dict[str, Any] = {
    'samples_table': 'Samples',
    'sample_name_column': 'Name',
    'experiment_column': 'Experiment',
    # Sample.Name -> related tables keyed directly on the sample name
    'measurements': {'table': 'Measurements', 'key': 'Sample_ID'},
    'robotic_od': {'table': 'Robotic_OD', 'key': 'sample_name'},
    'seq_samples': {
        'table': 'Seq_samples',
        'key': 'Sample_Name',            # Seq_samples row -> origin Samples.Name
        'id_column': 'Sequencing_sample',  # the sequencing-sample identifier
    },
    # Sequencing results keyed on the sequencing-sample identifier
    'mutations': {'table': 'Mutations', 'key': 'Seq_sample'},
    'copy_numbers': {'table': 'Copy_numbers', 'key': 'Seqsample'},
    'barcodes': {'table': 'verAB_barcodes', 'key': 'Seqsample'},
}


def _query_by_values(
    table: str,
    key: str,
    values: List[Any],
    config: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """Return rows of ``table`` where ``key`` is in ``values``.

    Issues one equality query per value (the query API supports only single
    equality per column) and concatenates. Returns an empty DataFrame if there
    are no values or no matches.
    """
    frames = []
    for value in values:
        if value is None:
            continue
        df = query_to_dataframe(table, filters={key: value}, config=config)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


class Sample:
    """A physical sample (a row in ``Samples``) and its measurements.

    Methods returning measurements return pandas DataFrames (notebook-friendly).
    The relating column for each is defined in :data:`JOIN_KEYS`.
    """

    def __init__(
        self,
        name: str,
        record: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self._record = record
        self.config = config

    @classmethod
    def get(cls, name: str, config: Optional[Dict[str, Any]] = None) -> 'Sample':
        """Load a sample's metadata row from ``Samples`` by name."""
        df = query_to_dataframe(
            JOIN_KEYS['samples_table'],
            filters={JOIN_KEYS['sample_name_column']: name},
            config=config,
        )
        record = df.iloc[0].to_dict() if not df.empty else None
        return cls(name, record=record, config=config)

    @property
    def record(self) -> Optional[Dict[str, Any]]:
        if self._record is None:
            loaded = Sample.get(self.name, config=self.config)
            self._record = loaded._record
        return self._record

    @property
    def experiment(self) -> Optional[str]:
        rec = self.record
        return rec.get(JOIN_KEYS['experiment_column']) if rec else None

    # ---------------------------------------------------------- measurements
    def measurements(self, type: Optional[str] = None) -> pd.DataFrame:
        """Rows from the ``Measurements`` registry for this sample.

        Optionally filter by measurement ``type`` (the ``Type`` column).
        """
        spec = JOIN_KEYS['measurements']
        df = query_to_dataframe(
            spec['table'], filters={spec['key']: self.name}, config=self.config
        )
        if type is not None and 'Type' in df.columns:
            df = df[df['Type'] == type].reset_index(drop=True)
        return df

    def od(self) -> pd.DataFrame:
        """Robotic OD readings for this sample (``Robotic_OD``)."""
        spec = JOIN_KEYS['robotic_od']
        return query_to_dataframe(
            spec['table'], filters={spec['key']: self.name}, config=self.config
        )

    def seq_samples(self) -> pd.DataFrame:
        """Sequencing samples derived from this sample (``Seq_samples``)."""
        spec = JOIN_KEYS['seq_samples']
        return query_to_dataframe(
            spec['table'], filters={spec['key']: self.name}, config=self.config
        )

    def _seq_sample_ids(self) -> List[Any]:
        spec = JOIN_KEYS['seq_samples']
        df = self.seq_samples()
        id_col = spec['id_column']
        if df.empty or id_col not in df.columns:
            return []
        return df[id_col].dropna().unique().tolist()

    def _results_for_seq_samples(self, join_name: str) -> pd.DataFrame:
        spec = JOIN_KEYS[join_name]
        ids = self._seq_sample_ids()
        if not ids:
            return pd.DataFrame()
        return _query_by_values(spec['table'], spec['key'], ids, config=self.config)

    def mutations(self) -> pd.DataFrame:
        """Mutation calls for this sample's sequencing samples (``Mutations``)."""
        return self._results_for_seq_samples('mutations')

    def copy_numbers(self) -> pd.DataFrame:
        """Copy-number results for this sample's sequencing samples."""
        return self._results_for_seq_samples('copy_numbers')

    def barcodes(self) -> pd.DataFrame:
        """verA/verB barcode counts for this sample's sequencing samples."""
        return self._results_for_seq_samples('barcodes')

    def __repr__(self) -> str:
        return f'<Sample name={self.name!r}>'


class Experiment:
    """An experiment and the samples that belong to it."""

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config = config

    def selection(self):
        """Return a :class:`~aisynbiopipeline.domain.selection.Selection` of
        this experiment's samples."""
        from .selection import Selection

        return Selection.samples(experiment=self.name, config=self.config)

    def samples(self) -> List[Sample]:
        """Return :class:`Sample` objects for this experiment."""
        return self.selection().as_samples()

    def sample_names(self) -> List[str]:
        return self.selection().names()

    def __repr__(self) -> str:
        return f'<Experiment name={self.name!r}>'
