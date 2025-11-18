"""
Data management utilities for AISynbioPipeline.

This module provides tools for managing the standardized data directory structure
used for storing experimental data, sequencing libraries, and analysis results.
"""

from pathlib import Path
from typing import List, Optional


def get_data_root(custom_root: Optional[str] = None) -> Path:
    """
    Get the data root directory.

    Args:
        custom_root: Optional custom root directory path

    Returns:
        Path to the data root directory
    """
    if custom_root:
        return Path(custom_root)
    return Path('ai_synbio_data')


def get_library_path(
    library_name: str,
    read_type: str,
    data_root: Optional[str] = None
) -> Path:
    """
    Get the path to a library's read directory.

    Args:
        library_name: Name of the sequencing library
        read_type: Type of reads ('short' or 'long')
        data_root: Optional custom data root directory

    Returns:
        Path to the library read directory
    """
    root = get_data_root(data_root)
    return (
        root / "experimental_data" / "sequencing_libraries" /
        library_name / f"{library_name}_{read_type}_reads"
    )


def get_analysis_path(
    library_name: str,
    read_type: str,
    analysis_type: str,
    data_root: Optional[str] = None
) -> Path:
    """
    Get the path to a specific analysis directory.

    Args:
        library_name: Name of the sequencing library
        read_type: Type of reads ('short' or 'long')
        analysis_type: Type of analysis ('received', 'trimmed', 'breseq', 'mapped', 'filtered')
        data_root: Optional custom data root directory

    Returns:
        Path to the analysis directory
    """
    library_path = get_library_path(library_name, read_type, data_root)
    return library_path / analysis_type


__all__ = [
    'get_data_root',
    'get_library_path',
    'get_analysis_path',
]
