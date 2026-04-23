"""
LIMS API Module

This module provides a Python API for the Laboratory Information Management System (LIMS)
that synchronizes data from Google Sheets to a local SQLite database.

Main components:
- sheets: Google Sheets integration and reading
- database: SQLite mirror database management
- sync: Synchronization daemon and logic
- archive: Database archival and retention
- query: Read-only query interface
- googledrive: Google Drive file operations

Example usage:
    from aisynbiopipeline.limsapi import start_sync_daemon, query_table, upload_or_replace

    # Start the sync daemon
    start_sync_daemon()

    # Query data
    results = query_table('samples', filters={'status': 'active'})

    # Upload files to Google Drive
    upload_or_replace('/path/to/file.txt', 'folder_id_on_drive')
"""

from .query import (
    list_tables,
    get_table_schema,
    query_table,
    get_all_records,
    get_record_by_id,
    get_table_count,
    search_table
)

from .sync import (
    sync_all_sheets,
    start_sync_daemon,
    stop_sync_daemon,
    get_sync_status
)

from .archive import (
    create_archive,
    list_archives,
    restore_archive,
    cleanup_archives
)

from .googledrive import (
    get_drive_service,
    upload_or_replace,
    find_file_in_folder
)

__version__ = '0.1.0'
__all__ = [
    # Query functions
    'list_tables',
    'get_table_schema',
    'query_table',
    'get_all_records',
    'get_record_by_id',
    'get_table_count',
    'search_table',
    # Sync functions
    'sync_all_sheets',
    'start_sync_daemon',
    'stop_sync_daemon',
    'get_sync_status',
    # Archive functions
    'create_archive',
    'list_archives',
    'restore_archive',
    'cleanup_archives',
    # Google Drive functions
    'get_drive_service',
    'upload_or_replace',
    'find_file_in_folder',
]
