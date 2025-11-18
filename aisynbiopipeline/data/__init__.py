"""
Data management utilities for AISynbioPipeline.

This module provides tools for managing the standardized data directory structure
used for storing experimental data, sequencing libraries, and analysis results.

Directory Structure:
    ai_synbio_data/
    ├── experimental_data/
    │   ├── sequencing_libraries/
    │   │   └── <library_name>/
    │   │       ├── <library_name>_short_reads/
    │   │       │   ├── received/
    │   │       │   ├── trimmed/
    │   │       │   ├── breseq/
    │   │       │   │   └── breseq_<params>/
    │   │       │   └── mapped/
    │   │       │       └── mapped_<params>/
    │   │       ├── <library_name>_long_reads/
    │   │       │   ├── received/
    │   │       │   └── filtered/
    │   │       └── <library_name>_hybrid_assemblies/
    │   ├── proteomics_data/
    │   └── robotic_OD_data/
    └── reference_data/
        ├── reference_genomes/
        └── blast_dbs/
"""

from pathlib import Path
from typing import Optional


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


def get_library_base_path(
    library_name: str,
    data_root: Optional[str] = None
) -> Path:
    """
    Get the base path to a sequencing library.

    Args:
        library_name: Name of the sequencing library
        data_root: Optional custom data root directory

    Returns:
        Path to the library base directory
    """
    root = get_data_root(data_root)
    return root / "experimental_data" / "sequencing_libraries" / library_name


def get_library_reads_path(
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
    library_base = get_library_base_path(library_name, data_root)
    return library_base / f"{library_name}_{read_type}_reads"


def get_received_path(
    library_name: str,
    read_type: str,
    data_root: Optional[str] = None
) -> Path:
    """
    Get the path to the 'received' directory for raw reads.

    Args:
        library_name: Name of the sequencing library
        read_type: Type of reads ('short' or 'long')
        data_root: Optional custom data root directory

    Returns:
        Path to the received directory
    """
    reads_path = get_library_reads_path(library_name, read_type, data_root)
    return reads_path / "received"


def get_trimmed_path(
    library_name: str,
    data_root: Optional[str] = None
) -> Path:
    """
    Get the path to the 'trimmed' directory (short reads only).

    Args:
        library_name: Name of the sequencing library
        data_root: Optional custom data root directory

    Returns:
        Path to the trimmed directory
    """
    reads_path = get_library_reads_path(library_name, "short", data_root)
    return reads_path / "trimmed"


def get_filtered_path(
    library_name: str,
    data_root: Optional[str] = None
) -> Path:
    """
    Get the path to the 'filtered' directory (long reads only).

    Args:
        library_name: Name of the sequencing library
        data_root: Optional custom data root directory

    Returns:
        Path to the filtered directory
    """
    reads_path = get_library_reads_path(library_name, "long", data_root)
    return reads_path / "filtered"


def get_breseq_path(
    library_name: str,
    params: Optional[str] = None,
    data_root: Optional[str] = None
) -> Path:
    """
    Get the path to breseq analysis directory.

    Breseq params should follow: <ref_genome>_<pop|con>_<coverage>_<other_params>
    Example: ADP1_pop_100x or ADP1_con

    Args:
        library_name: Name of the sequencing library
        params: Optional parameter set identifier (e.g., 'ADP1_pop_100x')
        data_root: Optional custom data root directory

    Returns:
        Path to the breseq directory (or specific params subdirectory)
    """
    reads_path = get_library_reads_path(library_name, "short", data_root)
    breseq_base = reads_path / "breseq"

    if params:
        return breseq_base / f"breseq_{params}"
    return breseq_base


def get_mapped_path(
    library_name: str,
    params: Optional[str] = None,
    data_root: Optional[str] = None
) -> Path:
    """
    Get the path to mapped reads directory.

    Args:
        library_name: Name of the sequencing library
        params: Optional parameter set identifier
        data_root: Optional custom data root directory

    Returns:
        Path to the mapped directory (or specific params subdirectory)
    """
    reads_path = get_library_reads_path(library_name, "short", data_root)
    mapped_base = reads_path / "mapped"

    if params:
        return mapped_base / f"mapped_{params}"
    return mapped_base


def get_hybrid_assemblies_path(
    library_name: str,
    data_root: Optional[str] = None
) -> Path:
    """
    Get the path to hybrid assemblies directory.

    Args:
        library_name: Name of the sequencing library
        data_root: Optional custom data root directory

    Returns:
        Path to the hybrid assemblies directory
    """
    library_base = get_library_base_path(library_name, data_root)
    return library_base / f"{library_name}_hybrid_assemblies"


def get_reference_genomes_path(data_root: Optional[str] = None) -> Path:
    """
    Get the path to reference genomes directory.

    Args:
        data_root: Optional custom data root directory

    Returns:
        Path to the reference genomes directory
    """
    root = get_data_root(data_root)
    return root / "reference_data" / "reference_genomes"


def get_blast_dbs_path(data_root: Optional[str] = None) -> Path:
    """
    Get the path to BLAST databases directory.

    Args:
        data_root: Optional custom data root directory

    Returns:
        Path to the BLAST databases directory
    """
    root = get_data_root(data_root)
    return root / "reference_data" / "blast_dbs"


__all__ = [
    'get_data_root',
    'get_library_base_path',
    'get_library_reads_path',
    'get_received_path',
    'get_trimmed_path',
    'get_filtered_path',
    'get_breseq_path',
    'get_mapped_path',
    'get_hybrid_assemblies_path',
    'get_reference_genomes_path',
    'get_blast_dbs_path',
]
