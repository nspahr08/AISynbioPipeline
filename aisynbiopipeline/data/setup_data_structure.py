#!/usr/bin/env python
"""
Script to set up the standardized data folder structure for AISynbioPipeline.

This creates the directory structure for storing experimental data including
sequencing libraries, assemblies, and analysis results.

Directory Structure:
    ai_synbio_data/
    └── experimental_data/
        └── sequencing_libraries/
            └── <library_name>/
                ├── <library_name>_short_reads/
                │   ├── received/
                │   ├── trimmed/
                │   ├── breseq/
                │   ├── mapped/
                │   └── filtered/
                └── <library_name>_long_reads/
                    ├── received/
                    ├── trimmed/
                    ├── breseq/
                    ├── mapped/
                    └── filtered/
"""

import argparse
from pathlib import Path
from typing import List, Optional


def create_library_structure(
    data_root: Path,
    library_name: str,
    read_types: Optional[List[str]] = None
) -> List[Path]:
    """
    Create the directory structure for a sequencing library.

    Args:
        data_root: Root directory for data (e.g., 'ai_synbio_data')
        library_name: Name of the sequencing library
        read_types: List of read types to create ('short', 'long', or both)

    Returns:
        List of created directory paths
    """
    if read_types is None:
        read_types = ['short', 'long']

    created_dirs = []

    # Base path: data_root/experimental_data/sequencing_libraries/library_name/
    library_base = (
        data_root / "experimental_data" / "sequencing_libraries" / library_name
    )

    # Subdirectories for each analysis type
    subdirs = ['received', 'trimmed', 'breseq', 'mapped', 'filtered']

    for read_type in read_types:
        # Create read type directory: library_name_short_reads or library_name_long_reads
        read_dir = library_base / f"{library_name}_{read_type}_reads"

        for subdir in subdirs:
            dir_path = read_dir / subdir
            dir_path.mkdir(parents=True, exist_ok=True)
            created_dirs.append(dir_path)
            print(f"Created: {dir_path}")

    return created_dirs


def setup_data_root(data_root: Path) -> Path:
    """
    Set up the root data directory structure.

    Args:
        data_root: Root directory for data

    Returns:
        Path to experimental_data directory
    """
    experimental_data = data_root / "experimental_data" / "sequencing_libraries"
    experimental_data.mkdir(parents=True, exist_ok=True)
    print(f"Created: {experimental_data}")
    return experimental_data


def create_readme(directory: Path, content: str):
    """
    Create a README file in the specified directory.

    Args:
        directory: Directory to create README in
        content: Content for the README file
    """
    readme_path = directory / "README.md"
    with open(readme_path, 'w') as f:
        f.write(content)
    print(f"Created: {readme_path}")


def main():
    """Main entry point for the setup script."""
    parser = argparse.ArgumentParser(
        description='Set up AISynbioPipeline data directory structure',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Set up root data structure only
  python setup_data_structure.py --root ai_synbio_data

  # Set up root and create a library structure
  python setup_data_structure.py --root ai_synbio_data --library my_library_ABC

  # Create library with only short reads
  python setup_data_structure.py --root ai_synbio_data --library my_library_ABC --read-types short

  # Create multiple libraries
  python setup_data_structure.py --root ai_synbio_data --library lib1 lib2 lib3
"""
    )

    parser.add_argument(
        '--root',
        default='ai_synbio_data',
        help='Root directory for data (default: ai_synbio_data)'
    )

    parser.add_argument(
        '--library',
        nargs='+',
        help='Name(s) of sequencing library to create'
    )

    parser.add_argument(
        '--read-types',
        nargs='+',
        choices=['short', 'long'],
        default=['short', 'long'],
        help='Types of reads to set up (default: both short and long)'
    )

    parser.add_argument(
        '--create-readme',
        action='store_true',
        help='Create README files in each directory'
    )

    args = parser.parse_args()

    data_root = Path(args.root)

    print("=" * 70)
    print("AISynbioPipeline Data Structure Setup")
    print("=" * 70)
    print(f"Data root: {data_root.absolute()}")
    print()

    # Set up root structure
    experimental_data = setup_data_root(data_root)

    if args.create_readme:
        readme_content = """# AISynbioPipeline Data Directory

This directory contains experimental data for the AISynbioPipeline project.

## Structure

- `sequencing_libraries/` - Sequencing library data organized by library name
  - Each library has subdirectories for short and/or long reads
  - Each read type has subdirectories for different analysis stages:
    - `received/` - Raw data as received from sequencing facility
    - `trimmed/` - Quality-trimmed reads
    - `breseq/` - Breseq analysis results
    - `mapped/` - Mapped reads
    - `filtered/` - Filtered reads

## Naming Conventions

- Library folders: `<library_name>/`
- Read type folders: `<library_name>_short_reads/` or `<library_name>_long_reads/`
- Breseq folders: `breseq_<ref_genome>_<pop_or_con>_<coverage>_<params>/`
"""
        create_readme(data_root / "experimental_data", readme_content)

    # Set up library structures if requested
    if args.library:
        print()
        for library_name in args.library:
            print(f"Setting up library: {library_name}")
            print("-" * 70)
            create_library_structure(data_root, library_name, args.read_types)

            if args.create_readme:
                library_base = (
                    data_root / "experimental_data" / "sequencing_libraries" / library_name
                )
                library_readme = f"""# {library_name}

Sequencing library data for {library_name}.

## Subdirectories

- `{library_name}_short_reads/` - Short read data (if applicable)
- `{library_name}_long_reads/` - Long read data (if applicable)

Each read type directory contains:
- `received/` - Raw data from sequencing facility
- `trimmed/` - Quality-trimmed reads
- `breseq/` - Breseq mutation analysis results
- `mapped/` - Reads mapped to reference genome
- `filtered/` - Filtered reads based on quality/mapping criteria
"""
                create_readme(library_base, library_readme)

            print()

    print("=" * 70)
    print("Setup complete!")
    print("=" * 70)

    if not args.library:
        print("\nTo create library structures, run with --library option:")
        print(f"  python setup_data_structure.py --root {args.root} --library <library_name>")


if __name__ == '__main__':
    main()
