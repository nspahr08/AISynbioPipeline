import sys
import os
import json
from os import path
from zipfile import ZipFile

# Add the parent directory to the sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path)
base_dir = os.path.dirname(os.path.dirname(script_dir))
folder_name = os.path.basename(script_dir)

# Add project root to path for LIMS API access
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

print(base_dir+"/KBUtilLib/src")
sys.path = [base_dir+"/KBUtilLib/src",base_dir+"/cobrakbase",base_dir+"/ModelSEEDpy/"] + sys.path

# Import utilities with error handling
from kbutillib import NotebookUtils

import hashlib
import pandas as pd

# Define the base classes based on what's available
class NotebookUtil(NotebookUtils):
    def __init__(self,**kwargs):
        super().__init__(
            notebook_folder=script_dir,
            name="AISynbioPipelineNotebookUtils",
            **kwargs
        )

# Initialize the NotebookUtil instance
util = NotebookUtil()

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
except ImportError as e:
    print(f"Warning: LIMS API not available: {e}")
    LIMS_AVAILABLE = False

def get_lims_tables():
    """Get a list of all available LIMS tables."""
    if not LIMS_AVAILABLE:
        raise RuntimeError("LIMS API is not available")
    return list_tables()

def query_lims(table_name, filters=None, columns=None, limit=None):
    """
    Query a LIMS table and return results as a pandas DataFrame.

    Args:
        table_name: Name of the table to query
        filters: Dictionary of column-value pairs for filtering
        columns: List of columns to return (all if None)
        limit: Maximum number of rows to return

    Returns:
        pandas DataFrame with results
    """
    if not LIMS_AVAILABLE:
        raise RuntimeError("LIMS API is not available")

    results = query_table(
        table_name,
        filters=filters,
        columns=columns,
        limit=limit
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
