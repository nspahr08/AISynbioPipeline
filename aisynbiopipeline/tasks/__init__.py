"""
Celery tasks for AISynbioPipeline.

This package contains all Celery task definitions. Tasks are thin wrappers
around workflow functions that handle JSON I/O and Celery integration.
"""

from .kbase_tasks import download_kbase_reads, upload_kbase_reads

__all__ = [
    'download_kbase_reads',
    'upload_kbase_reads',
]
