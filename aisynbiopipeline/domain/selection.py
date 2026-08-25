"""Sample selection (cohorts) over the LIMS mirror.

A :class:`Selection` is a thin wrapper around a query against a LIMS table
(``Samples`` by default). It is grounded in the read-only query API
(:mod:`aisynbiopipeline.limsapi.query`): equality filters with a single value
are pushed down to SQL, while multi-value (``IN``) and substring filters are
applied in pandas afterward (the query API's WHERE clause only supports single
equality, see ``limsapi/query.py``).

Because a robotic run / SeqOrder can span multiple experiments, selection is by
arbitrary criteria rather than by batch: you can pick one sample, one
experiment, several experiments, or any strain/condition slice.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

# Keep the package-import convention used across the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from limsapi.query import query_to_dataframe


def _is_multi(value: Any) -> bool:
    return isinstance(value, (list, tuple, set))


class Selection:
    """A cohort of rows from a LIMS table (default ``Samples``).

    Construct via :meth:`samples` / :meth:`from_filters`, refine with
    :meth:`filter`, :meth:`isin`, :meth:`contains`, and materialize with
    :meth:`to_dataframe`, :meth:`names`, or :meth:`as_samples`.
    """

    DEFAULT_TABLE = 'Samples'
    NAME_COLUMN = 'Name'

    def __init__(
        self,
        df: pd.DataFrame,
        table: str,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.table = table
        self.config = config
        self._df = df.reset_index(drop=True)

    # ------------------------------------------------------------------ build
    @classmethod
    def from_filters(
        cls,
        table: str = DEFAULT_TABLE,
        *,
        config: Optional[Dict[str, Any]] = None,
        **filters: Any,
    ) -> 'Selection':
        """Build a selection from equality filters.

        Scalar filters are pushed to SQL; filters whose value is a
        list/tuple/set are applied in pandas as an ``isin`` after the query.
        ``None`` values are ignored.
        """
        filters = {k: v for k, v in filters.items() if v is not None}
        scalar = {k: v for k, v in filters.items() if not _is_multi(v)}
        multi = {k: list(v) for k, v in filters.items() if _is_multi(v)}

        df = query_to_dataframe(table, filters=scalar or None, config=config)

        for col, values in multi.items():
            if col in df.columns:
                df = df[df[col].isin(values)]
            else:
                # No such column -> nothing can match.
                df = df.iloc[0:0]
        return cls(df, table, config)

    @classmethod
    def samples(
        cls,
        experiment: Any = None,
        strain: Any = None,
        condition: Any = None,
        name: Any = None,
        *,
        config: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> 'Selection':
        """Select rows from the ``Samples`` table.

        Each argument may be a scalar or a list (for multi-value selection).
        ``extra`` lets you filter on any other ``Samples`` column.
        """
        return cls.from_filters(
            cls.DEFAULT_TABLE,
            config=config,
            Experiment=experiment,
            Strain_name=strain,
            Condition=condition,
            Name=name,
            **extra,
        )

    # ----------------------------------------------------------------- refine
    def filter(self, **equals: Any) -> 'Selection':
        """Return a new selection keeping rows matching all scalar equalities."""
        df = self._df
        for col, value in equals.items():
            if _is_multi(value):
                df = df[df[col].isin(list(value))] if col in df.columns else df.iloc[0:0]
            else:
                df = df[df[col] == value] if col in df.columns else df.iloc[0:0]
        return Selection(df, self.table, self.config)

    def isin(self, column: str, values: Sequence[Any]) -> 'Selection':
        """Keep rows where ``column`` is in ``values``."""
        if column not in self._df.columns:
            return Selection(self._df.iloc[0:0], self.table, self.config)
        return Selection(
            self._df[self._df[column].isin(list(values))], self.table, self.config
        )

    def contains(self, column: str, substring: str, case: bool = False) -> 'Selection':
        """Keep rows where ``column`` contains ``substring`` (substring match)."""
        if column not in self._df.columns:
            return Selection(self._df.iloc[0:0], self.table, self.config)
        mask = self._df[column].astype(str).str.contains(substring, case=case, na=False)
        return Selection(self._df[mask], self.table, self.config)

    # --------------------------------------------------------------- evaluate
    def to_dataframe(self) -> pd.DataFrame:
        """Return a copy of the underlying rows."""
        return self._df.copy()

    def names(self) -> List[str]:
        """Return the sample names (the ``Name`` column), if present."""
        if self.NAME_COLUMN not in self._df.columns:
            return []
        return self._df[self.NAME_COLUMN].tolist()

    def as_samples(self) -> List['object']:
        """Return :class:`~aisynbiopipeline.domain.entities.Sample` objects.

        Only valid when the selection is over the ``Samples`` table.
        """
        # Imported lazily to avoid a circular import at module load.
        from .entities import Sample

        samples = []
        for _, row in self._df.iterrows():
            record = row.to_dict()
            samples.append(
                Sample(record.get(self.NAME_COLUMN), record=record, config=self.config)
            )
        return samples

    def __len__(self) -> int:
        return len(self._df)

    def __repr__(self) -> str:
        return f'<Selection table={self.table!r} rows={len(self._df)}>'
