"""
Query API module.

This module provides a read-only query interface for the SQLite mirror database.
"""

from typing import List, Dict, Any, Optional
import pandas as pd

from .config import load_config
from .database import DatabaseManager


def list_tables(config: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    List all available tables in the database.

    Args:
        config: Configuration dict (loads from file if not provided)

    Returns:
        List of table names

    Raises:
        Exception: If operation fails
    """
    with DatabaseManager(config) as db:
        return db.get_all_tables()


def get_table_schema(table_name: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Get the schema of a specific table.

    Args:
        table_name: Name of the table
        config: Configuration dict (loads from file if not provided)

    Returns:
        Dictionary mapping column names to SQL types

    Raises:
        Exception: If table doesn't exist or operation fails
    """
    with DatabaseManager(config) as db:
        return db.get_table_schema(table_name)


def query_table(
    table_name: str,
    filters: Optional[Dict[str, Any]] = None,
    columns: Optional[List[str]] = None,
    include_deleted: bool = False,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    order_by: Optional[str] = None,
    order_desc: bool = False,
    config: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Query a table with optional filters and pagination.

    Args:
        table_name: Name of the table to query
        filters: Dictionary of column-value pairs for filtering (optional)
        columns: List of columns to return (returns all if not specified)
        include_deleted: Include rows marked as deleted (default: False)
        limit: Maximum number of rows to return (optional)
        offset: Number of rows to skip (optional)
        order_by: Column to order by (optional)
        order_desc: Order descending if True (default: False)
        config: Configuration dict (loads from file if not provided)

    Returns:
        List of dictionaries representing rows

    Raises:
        Exception: If query fails
    """
    with DatabaseManager(config) as db:
        # Build SELECT clause
        if columns:
            columns_str = ', '.join([f'"{col}"' for col in columns])
        else:
            columns_str = '*'

        # Build WHERE clause
        where_clauses = []
        params = []

        if not include_deleted:
            where_clauses.append('deleted = 0')

        if filters:
            for col, value in filters.items():
                safe_col = col.replace(' ', '_').replace('-', '_')
                where_clauses.append(f'"{safe_col}" = ?')
                params.append(value)

        where_str = ' AND '.join(where_clauses) if where_clauses else '1=1'

        # Build ORDER BY clause
        order_str = ''
        if order_by:
            safe_order_col = order_by.replace(' ', '_').replace('-', '_')
            direction = 'DESC' if order_desc else 'ASC'
            order_str = f' ORDER BY "{safe_order_col}" {direction}'

        # Build LIMIT/OFFSET clause
        limit_str = ''
        if limit is not None:
            limit_str = f' LIMIT {limit}'
            if offset is not None:
                limit_str += f' OFFSET {offset}'

        # Build full query
        sql = f'SELECT {columns_str} FROM "{table_name}" WHERE {where_str}{order_str}{limit_str}'

        return db.execute_query(sql, tuple(params) if params else None)


def get_all_records(
    table_name: str,
    include_deleted: bool = False,
    config: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Get all records from a table.

    Args:
        table_name: Name of the table
        include_deleted: Include rows marked as deleted (default: False)
        config: Configuration dict (loads from file if not provided)

    Returns:
        List of dictionaries representing all rows

    Raises:
        Exception: If query fails
    """
    return query_table(table_name, include_deleted=include_deleted, config=config)


def get_record_by_id(
    table_name: str,
    id_column: str,
    id_value: Any,
    config: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """
    Get a specific record by ID.

    Args:
        table_name: Name of the table
        id_column: Name of the ID column
        id_value: Value of the ID to search for
        config: Configuration dict (loads from file if not provided)

    Returns:
        Dictionary representing the row, or None if not found

    Raises:
        Exception: If query fails
    """
    results = query_table(
        table_name,
        filters={id_column: id_value},
        limit=1,
        config=config
    )

    return results[0] if results else None


def query_to_dataframe(
    table_name: str,
    filters: Optional[Dict[str, Any]] = None,
    columns: Optional[List[str]] = None,
    include_deleted: bool = False,
    config: Optional[Dict[str, Any]] = None
) -> pd.DataFrame:
    """
    Query a table and return results as a pandas DataFrame.

    Args:
        table_name: Name of the table to query
        filters: Dictionary of column-value pairs for filtering (optional)
        columns: List of columns to return (returns all if not specified)
        include_deleted: Include rows marked as deleted (default: False)
        config: Configuration dict (loads from file if not provided)

    Returns:
        pandas DataFrame with query results

    Raises:
        Exception: If query fails
    """
    results = query_table(
        table_name,
        filters=filters,
        columns=columns,
        include_deleted=include_deleted,
        config=config
    )

    return pd.DataFrame(results)


def execute_sql(
    sql: str,
    params: Optional[tuple] = None,
    config: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Execute a custom SQL query.

    WARNING: Only use for read-only SELECT queries. This is a read-only API.

    Args:
        sql: SQL query string
        params: Query parameters (optional)
        config: Configuration dict (loads from file if not provided)

    Returns:
        List of dictionaries representing query results

    Raises:
        Exception: If query fails or is not a SELECT statement
    """
    # Basic safety check - only allow SELECT
    if not sql.strip().upper().startswith('SELECT'):
        raise Exception("Only SELECT queries are allowed. This is a read-only API.")

    with DatabaseManager(config) as db:
        return db.execute_query(sql, params)


def get_table_count(
    table_name: str,
    include_deleted: bool = False,
    config: Optional[Dict[str, Any]] = None
) -> int:
    """
    Get the number of records in a table.

    Args:
        table_name: Name of the table
        include_deleted: Include rows marked as deleted (default: False)
        config: Configuration dict (loads from file if not provided)

    Returns:
        Number of records

    Raises:
        Exception: If query fails
    """
    where_clause = '' if include_deleted else 'WHERE deleted = 0'
    sql = f'SELECT COUNT(*) as count FROM "{table_name}" {where_clause}'

    with DatabaseManager(config) as db:
        result = db.execute_query(sql)
        return result[0]['count'] if result else 0


def search_table(
    table_name: str,
    search_column: str,
    search_term: str,
    include_deleted: bool = False,
    config: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Search for records where a column contains a search term (case-insensitive).

    Args:
        table_name: Name of the table
        search_column: Column to search in
        search_term: Term to search for
        include_deleted: Include rows marked as deleted (default: False)
        config: Configuration dict (loads from file if not provided)

    Returns:
        List of matching records

    Raises:
        Exception: If query fails
    """
    safe_col = search_column.replace(' ', '_').replace('-', '_')

    where_clauses = [f'"{safe_col}" LIKE ?']
    params = [f'%{search_term}%']

    if not include_deleted:
        where_clauses.append('deleted = 0')

    where_str = ' AND '.join(where_clauses)
    sql = f'SELECT * FROM "{table_name}" WHERE {where_str}'

    with DatabaseManager(config) as db:
        return db.execute_query(sql, tuple(params))
