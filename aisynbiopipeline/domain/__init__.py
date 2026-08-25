"""Domain layer over the LIMS mirror.

A thin, read-only set of views that sit on top of ``aisynbiopipeline.limsapi``
and give callers (scripts and notebooks alike) a consistent way to:

- **select** cohorts of samples by experiment / strain / condition / etc.
  (:class:`~aisynbiopipeline.domain.selection.Selection`), and
- **resolve** a sample's related measurements across modalities
  (:class:`~aisynbiopipeline.domain.entities.Sample`,
  :class:`~aisynbiopipeline.domain.entities.Experiment`).

The join keys that relate samples to their measurements live in ONE place
(:data:`aisynbiopipeline.domain.entities.JOIN_KEYS`) so that a future database
redesign only has to change that mapping.
"""

from .selection import Selection
from .entities import Sample, Experiment, JOIN_KEYS

__all__ = ['Selection', 'Sample', 'Experiment', 'JOIN_KEYS']
