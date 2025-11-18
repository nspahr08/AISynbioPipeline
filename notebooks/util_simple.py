"""
Simplified utility functions for LIMS API notebooks.

This module provides helper functions for querying the LIMS database
without requiring external KBase dependencies.
"""

import sys
import os
import pandas as pd

# Add project root to path for LIMS API access
notebook_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(notebook_dir)

if project_root not in sys.path:
    sys.path.insert(0, project_root)

# ============================================================================
# LIMS API Helper Functions
# ============================================================================

# Import LIMS API
try:
    from aisynbiopipeline.limsapi import (
        list_tables,
        get_table_schema,
        query_table,
        get_all_records,
        get_table_count,
        search_table
    )
    LIMS_AVAILABLE = True
    print("✓ LIMS API loaded successfully")
except ImportError as e:
    print(f"Warning: LIMS API not available: {e}")
    LIMS_AVAILABLE = False


def get_lims_tables():
    """Get a list of all available LIMS tables."""
    if not LIMS_AVAILABLE:
        raise RuntimeError("LIMS API is not available")
    return list_tables()


def query_lims(table_name, filters=None, columns=None, limit=None, order_by=None, order_desc=False):
    """
    Query a LIMS table and return results as a pandas DataFrame.

    Args:
        table_name: Name of the table to query
        filters: Dictionary of column-value pairs for filtering
        columns: List of columns to return (all if None)
        limit: Maximum number of rows to return
        order_by: Column to order by (optional)
        order_desc: Order descending if True (default: False)

    Returns:
        pandas DataFrame with results
    """
    if not LIMS_AVAILABLE:
        raise RuntimeError("LIMS API is not available")

    results = query_table(
        table_name,
        filters=filters,
        columns=columns,
        limit=limit,
        order_by=order_by,
        order_desc=order_desc
    )

    return pd.DataFrame(results)


def search_lims(table_name, column, search_term):
    """
    Search for records in a LIMS table where a column contains a search term.

    Args:
        table_name: Name of the table to search
        column: Column to search in
        search_term: Term to search for (case-insensitive)

    Returns:
        pandas DataFrame with matching results
    """
    if not LIMS_AVAILABLE:
        raise RuntimeError("LIMS API is not available")

    results = search_table(table_name, column, search_term)
    return pd.DataFrame(results)


def get_lims_schema(table_name):
    """
    Get the schema of a LIMS table.

    Args:
        table_name: Name of the table

    Returns:
        Dictionary mapping column names to SQL types
    """
    if not LIMS_AVAILABLE:
        raise RuntimeError("LIMS API is not available")

    return get_table_schema(table_name)


def count_lims_rows(table_name):
    """
    Count the number of rows in a LIMS table.

    Args:
        table_name: Name of the table

    Returns:
        Integer count of rows
    """
    if not LIMS_AVAILABLE:
        raise RuntimeError("LIMS API is not available")

    return get_table_count(table_name)


# Convenience function to display table info
def show_table_info(table_name):
    """
    Display comprehensive information about a LIMS table.

    Args:
        table_name: Name of the table
    """
    if not LIMS_AVAILABLE:
        raise RuntimeError("LIMS API is not available")

    print(f"Table: {table_name}")
    print(f"Rows: {count_lims_rows(table_name)}")
    print("\nSchema:")

    schema = get_lims_schema(table_name)
    for col, sql_type in schema.items():
        print(f"  {col}: {sql_type}")

    print("\nSample data (first 5 rows):")
    sample = query_lims(table_name, limit=5)
    return sample


def get_safe_columns(df, preferred_cols):
    """
    Return only columns that exist in the DataFrame.

    This is useful for avoiding KeyError when column names are uncertain.

    Args:
        df: pandas DataFrame
        preferred_cols: List of column names you want to use

    Returns:
        List of column names that actually exist in the DataFrame

    Example:
        >>> df = query_lims('Samples', limit=1)
        >>> cols = get_safe_columns(df, ['Name', 'Strain', 'Strain_name'])
        >>> df[cols]  # Won't raise KeyError
    """
    return [col for col in preferred_cols if col in df.columns]
