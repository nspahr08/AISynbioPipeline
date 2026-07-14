"""
SQLite database management module.

This module handles the SQLite mirror database, including schema creation,
data synchronization, and change detection using row hashing.
"""

import sqlite3
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from .config import load_config, get_db_path


class DatabaseManager:
    """
    Manages the SQLite mirror database.

    This class handles all database operations including schema creation,
    data updates, soft deletes, and change detection.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the DatabaseManager.

        Args:
            config: Configuration dict (loads from file if not provided)
        """
        if config is None:
            config = load_config()

        self.config = config
        self.db_path = get_db_path(config)
        self._connection = None

    def connect(self) -> None:
        """Establish connection to the SQLite database."""
        self._connection = sqlite3.connect(str(self.db_path))
        self._connection.row_factory = sqlite3.Row  # Return rows as dicts
        # Enable foreign keys (even though we won't use them for now)
        self._connection.execute("PRAGMA foreign_keys = ON")

    def disconnect(self) -> None:
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None

    def get_connection(self) -> sqlite3.Connection:
        """
        Get the database connection, connecting if necessary.

        Returns:
            SQLite connection object

        Raises:
            Exception: If connection fails
        """
        if self._connection is None:
            self.connect()
        return self._connection

    def table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists in the database.

        Args:
            table_name: Name of the table to check

        Returns:
            True if table exists, False otherwise
        """
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return cursor.fetchone() is not None

    def create_table(self, table_name: str, schema: Dict[str, str]) -> None:
        """
        Create a table with the given schema.

        Adds backend columns: deleted, last_synced, row_hash

        Args:
            table_name: Name of the table to create
            schema: Dictionary mapping column names to SQL types

        Raises:
            Exception: If table creation fails
        """
        conn = self.get_connection()

        # Build column definitions
        columns = []
        for col_name, col_type in schema.items():
            # Sanitize column name (replace spaces with underscores)
            safe_col_name = col_name.replace(' ', '_').replace('-', '_')
            columns.append(f'"{safe_col_name}" {col_type}')

        # Add backend columns
        columns.extend([
            'deleted BOOLEAN DEFAULT 0',
            'last_synced TIMESTAMP',
            'row_hash TEXT'
        ])

        columns_str = ',\n    '.join(columns)
        create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n    {columns_str}\n)'

        try:
            conn.execute(create_sql)
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to create table '{table_name}': {e}")

    def get_table_schema(self, table_name: str) -> Dict[str, str]:
        """
        Get the schema of an existing table.

        Args:
            table_name: Name of the table

        Returns:
            Dictionary mapping column names to types

        Raises:
            Exception: If table doesn't exist
        """
        if not self.table_exists(table_name):
            raise Exception(f"Table '{table_name}' does not exist")

        conn = self.get_connection()
        cursor = conn.execute(f'PRAGMA table_info("{table_name}")')
        rows = cursor.fetchall()

        schema = {}
        for row in rows:
            col_name = row[1]  # Column name
            col_type = row[2]  # Column type
            # Skip backend columns
            if col_name not in ('deleted', 'last_synced', 'row_hash'):
                schema[col_name] = col_type

        return schema

    def add_column(self, table_name: str, column_name: str, column_type: str) -> None:
        """
        Add a new column to an existing table.

        Args:
            table_name: Name of the table
            column_name: Name of the new column
            column_type: SQL type of the new column

        Raises:
            Exception: If column addition fails
        """
        conn = self.get_connection()
        safe_col_name = column_name.replace(' ', '_').replace('-', '_')

        try:
            conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{safe_col_name}" {column_type}')
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to add column '{column_name}' to table '{table_name}': {e}")

    def drop_table(self, table_name: str) -> None:
        """
        Drop a table from the database.

        Args:
            table_name: Name of the table to drop

        Raises:
            Exception: If table drop fails
        """
        conn = self.get_connection()

        try:
            conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to drop table '{table_name}': {e}")

    def rename_column(self, table_name: str, old_column_name: str, new_column_name: str) -> None:
        """
        Rename a column in a table.

        Args:
            table_name: Name of the table
            old_column_name: Current column name
            new_column_name: New column name

        Raises:
            Exception: If column rename fails
        """
        conn = self.get_connection()

        try:
            conn.execute(f'ALTER TABLE "{table_name}" RENAME COLUMN "{old_column_name}" TO "{new_column_name}"')
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to rename column '{old_column_name}' to '{new_column_name}' in table '{table_name}': {e}")
    
    def sync_schema(self, table_name: str, sheet_schema: Dict[str, str]) -> None:
        """
        Synchronize table schema with Google Sheets schema.

        Creates table if it doesn't exist, adds missing columns if they do.

        Args:
            table_name: Name of the table
            sheet_schema: Schema from Google Sheets

        Raises:
            Exception: If schema sync fails
        """
        if not self.table_exists(table_name):
            self.create_table(table_name, sheet_schema)
        else:
            # Check for new columns
            current_schema = self.get_table_schema(table_name)
            for col_name, col_type in sheet_schema.items():
                safe_col_name = col_name.replace(' ', '_').replace('-', '_')
                if safe_col_name not in current_schema:
                    self.add_column(table_name, safe_col_name, col_type)

    @staticmethod
    def calculate_row_hash(row_data: Dict[str, Any]) -> str:
        """
        Calculate a hash of row data for change detection.

        Args:
            row_data: Dictionary of column values

        Returns:
            SHA256 hash of the row data
        """
        # Sort keys for consistent hashing
        sorted_data = {k: row_data[k] for k in sorted(row_data.keys())}
        # Convert to JSON string and hash
        data_str = json.dumps(sorted_data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()

    def upsert_rows(self, table_name: str, rows: List[Dict[str, Any]]) -> Tuple[int, int]:
        """
        Insert or update rows in the table.

        Uses row hash to detect changes. Only inserts rows with new hashes.
        Skips rows that already exist with the same hash (deduplication).

        Args:
            table_name: Name of the table
            rows: List of row dictionaries

        Returns:
            Tuple of (rows_inserted, rows_updated)

        Raises:
            Exception: If upsert fails
        """
        if not rows:
            return (0, 0)

        conn = self.get_connection()

        inserted = 0
        updated = 0

        try:
            for row_data in rows:
                # Sanitize column names
                sanitized_row = {}
                for k, v in row_data.items():
                    safe_key = k.replace(' ', '_').replace('-', '_')
                    sanitized_row[safe_key] = v

                # Calculate hash
                row_hash = self.calculate_row_hash(sanitized_row)
                now = datetime.now().isoformat()

                # CHECK IF ROW WITH THIS HASH ALREADY EXISTS
                existing_hash = conn.execute(
                    f'SELECT row_hash FROM "{table_name}" WHERE row_hash=?',
                    (row_hash,)
                ).fetchone()

                if existing_hash:
                    # Row with same hash already exists - skip
                    # (deduplication)
                    continue

                # Build column lists
                columns = list(sanitized_row.keys())
                values = [sanitized_row[col] for col in columns]

                # Add backend columns
                columns.extend(['deleted', 'last_synced', 'row_hash'])
                values.extend([0, now, row_hash])

                # Build placeholders
                placeholders = ','.join(['?'] * len(values))
                columns_str = ','.join([f'"{col}"' for col in columns])

                # Insert new row
                insert_sql = (
                    f'INSERT INTO "{table_name}" ({columns_str}) '
                    f'VALUES ({placeholders})'
                )
                conn.execute(insert_sql, values)
                inserted += 1

            conn.commit()
            return (inserted, updated)

        except Exception as e:
            conn.rollback()
            error_msg = (
                f"Failed to upsert rows in table '{table_name}': {e}"
            )
            raise Exception(error_msg)

    def mark_deleted_rows(self, table_name: str, current_hashes: List[str]) -> int:
        """
        Mark rows as deleted if they're not in the current set.

        Args:
            table_name: Name of the table
            current_hashes: List of row hashes that currently exist in Google Sheets

        Returns:
            Number of rows marked as deleted

        Raises:
            Exception: If marking fails
        """
        conn = self.get_connection()

        try:
            if not current_hashes:
                # All rows deleted
                cursor = conn.execute(
                    f'UPDATE "{table_name}" SET deleted=1, last_synced=? WHERE deleted=0',
                    (datetime.now().isoformat(),)
                )
            else:
                placeholders = ','.join(['?'] * len(current_hashes))
                cursor = conn.execute(
                    f'UPDATE "{table_name}" SET deleted=1, last_synced=? '
                    f'WHERE row_hash NOT IN ({placeholders}) AND deleted=0',
                    [datetime.now().isoformat()] + current_hashes
                )

            conn.commit()
            return cursor.rowcount

        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to mark deleted rows in table '{table_name}': {e}")

    def delete_rows(
        self,
        table_name: str,
        column: str,
        value: Any,
        soft: bool = True,
    ) -> int:
        """
        Delete rows from a table where ``column`` equals ``value``.

        By default this performs a *soft* delete (sets ``deleted=1``), which is
        consistent with how the rest of the codebase treats removed rows: reads
        via ``query.py`` hide ``deleted=1`` rows, and a soft delete survives the
        next Google Sheets sync. A *hard* delete (``soft=False``) removes the
        rows permanently, but note that if the matching row still exists in the
        source Google Sheet it will be re-inserted on the next sync.

        Args:
            table_name: Name of the table to delete from
            column: Column to match on
            value: Value the column must equal for a row to be deleted
            soft: If True (default), mark rows deleted=1; if False, remove them

        Returns:
            Number of rows affected

        Raises:
            Exception: If the table doesn't exist or the delete fails
        """
        if not self.table_exists(table_name):
            raise Exception(f"Table '{table_name}' does not exist")

        # Match the column-name sanitization used elsewhere (create_table,
        # upsert_rows) so callers can pass the human-readable column name.
        safe_col = column.replace(' ', '_').replace('-', '_')

        conn = self.get_connection()

        try:
            if soft:
                sql = (
                    f'UPDATE "{table_name}" SET deleted=1, last_synced=? '
                    f'WHERE "{safe_col}"=? AND deleted=0'
                )
                cursor = conn.execute(sql, (datetime.now().isoformat(), value))
            else:
                sql = f'DELETE FROM "{table_name}" WHERE "{safe_col}"=?'
                cursor = conn.execute(sql, (value,))

            conn.commit()
            return cursor.rowcount

        except Exception as e:
            conn.rollback()
            raise Exception(
                f"Failed to delete rows from table '{table_name}' "
                f"where {safe_col}={value!r}: {e}"
            )

    def get_all_tables(self) -> List[str]:
        """
        Get list of all tables in the database.

        Returns:
            List of table names
        """
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        return [row[0] for row in cursor.fetchall()]

    def execute_query(self, sql: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
        """
        Execute a SQL query and return results as dictionaries.

        Args:
            sql: SQL query string
            params: Optional query parameters

        Returns:
            List of result rows as dictionaries

        Raises:
            Exception: If query execution fails
        """
        conn = self.get_connection()

        try:
            if params:
                cursor = conn.execute(sql, params)
            else:
                cursor = conn.execute(sql)

            # Convert rows to dictionaries
            columns = [description[0] for description in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))

            return results

        except Exception as e:
            raise Exception(f"Failed to execute query: {e}")

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
