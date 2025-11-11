"""
Google Sheets integration module.

This module handles reading data from Google Sheets, including authentication,
connection management, and schema detection.
"""

import time
from typing import List, Dict, Any, Optional
import gspread
from google.oauth2.service_account import Credentials
from .config import load_config, get_credentials_path


class SheetsReader:
    """
    Handles reading data from Google Sheets.

    This class manages the connection to Google Sheets API, handles authentication,
    and provides methods to read sheet data and detect schemas.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the SheetsReader.

        Args:
            config: Configuration dict (loads from file if not provided)
        """
        if config is None:
            config = load_config()

        self.config = config
        self.spreadsheet_id = config['google_sheets']['spreadsheet_id']
        self.max_retries = config['google_sheets'].get('max_retries', 3)
        self.retry_delay = config['google_sheets'].get('retry_delay', 2.0)

        self._client = None
        self._spreadsheet = None

    def _get_credentials(self) -> Credentials:
        """
        Load and return Google API credentials.

        Returns:
            Google OAuth2 credentials

        Raises:
            FileNotFoundError: If credentials file not found
        """
        creds_path = get_credentials_path(self.config)

        # Define required scopes for Google Sheets
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets.readonly',
            'https://www.googleapis.com/auth/drive.readonly'
        ]

        credentials = Credentials.from_service_account_file(
            str(creds_path),
            scopes=scopes
        )

        return credentials

    def connect(self) -> None:
        """
        Establish connection to Google Sheets.

        Raises:
            Exception: If connection fails after max retries
        """
        credentials = self._get_credentials()

        for attempt in range(self.max_retries):
            try:
                self._client = gspread.authorize(credentials)
                self._spreadsheet = self._client.open_by_key(self.spreadsheet_id)
                return
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    raise Exception(f"Failed to connect to Google Sheets after {self.max_retries} attempts: {e}")

    def get_worksheet_names(self) -> List[str]:
        """
        Get list of all worksheet (tab) names in the spreadsheet.

        Returns:
            List of worksheet names

        Raises:
            Exception: If not connected or if request fails
        """
        if self._spreadsheet is None:
            raise Exception("Not connected to Google Sheets. Call connect() first.")

        for attempt in range(self.max_retries):
            try:
                worksheets = self._spreadsheet.worksheets()
                return [ws.title for ws in worksheets]
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    raise Exception(f"Failed to get worksheet names: {e}")

    def get_worksheet_data(self, worksheet_name: str) -> List[Dict[str, Any]]:
        """
        Get all data from a worksheet as a list of dictionaries.

        Args:
            worksheet_name: Name of the worksheet to read

        Returns:
            List of dictionaries, where each dict represents a row with column headers as keys

        Raises:
            Exception: If not connected or if worksheet not found
        """
        if self._spreadsheet is None:
            raise Exception("Not connected to Google Sheets. Call connect() first.")

        for attempt in range(self.max_retries):
            try:
                worksheet = self._spreadsheet.worksheet(worksheet_name)
                # Get all records as list of dicts (first row as headers)
                records = worksheet.get_all_records()
                return records
            except gspread.exceptions.WorksheetNotFound:
                raise Exception(f"Worksheet '{worksheet_name}' not found")
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    raise Exception(f"Failed to get worksheet data: {e}")

    def get_worksheet_schema(self, worksheet_name: str) -> Dict[str, str]:
        """
        Detect the schema (column names and types) of a worksheet.

        Args:
            worksheet_name: Name of the worksheet

        Returns:
            Dictionary mapping column names to inferred data types

        Raises:
            Exception: If not connected or if worksheet not found
        """
        if self._spreadsheet is None:
            raise Exception("Not connected to Google Sheets. Call connect() first.")

        for attempt in range(self.max_retries):
            try:
                worksheet = self._spreadsheet.worksheet(worksheet_name)

                # Get first row (headers)
                headers = worksheet.row_values(1)

                # Get a sample of data to infer types (first 100 rows)
                all_values = worksheet.get_all_values()

                if len(all_values) < 2:
                    # No data rows, default all to TEXT
                    return {header: 'TEXT' for header in headers}

                schema = {}
                for col_idx, header in enumerate(headers):
                    # Sample values from this column (skip header row)
                    sample_values = [
                        row[col_idx] if col_idx < len(row) else ''
                        for row in all_values[1:101]  # First 100 data rows
                    ]

                    # Infer type from sample
                    schema[header] = self._infer_column_type(sample_values)

                return schema

            except gspread.exceptions.WorksheetNotFound:
                raise Exception(f"Worksheet '{worksheet_name}' not found")
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    raise Exception(f"Failed to get worksheet schema: {e}")

    @staticmethod
    def _infer_column_type(values: List[str]) -> str:
        """
        Infer the SQL data type from a list of sample values.

        Args:
            values: List of string values from column

        Returns:
            SQL type name (TEXT, INTEGER, REAL, or BOOLEAN)
        """
        # Remove empty values
        non_empty = [v for v in values if v and str(v).strip()]

        if not non_empty:
            return 'TEXT'

        # Check if all values are integers
        all_int = True
        all_float = True
        all_bool = True

        for v in non_empty:
            v_str = str(v).strip().lower()

            # Check boolean
            if v_str not in ('true', 'false', '0', '1', 'yes', 'no'):
                all_bool = False

            # Check integer
            try:
                int(v)
            except (ValueError, TypeError):
                all_int = False

            # Check float
            try:
                float(v)
            except (ValueError, TypeError):
                all_float = False

        if all_bool:
            return 'BOOLEAN'
        elif all_int:
            return 'INTEGER'
        elif all_float:
            return 'REAL'
        else:
            return 'TEXT'

    def get_all_schemas(self) -> Dict[str, Dict[str, str]]:
        """
        Get schemas for all worksheets in the spreadsheet.

        Returns:
            Dictionary mapping worksheet names to their schemas

        Raises:
            Exception: If not connected
        """
        worksheet_names = self.get_worksheet_names()
        schemas = {}

        for name in worksheet_names:
            schemas[name] = self.get_worksheet_schema(name)

        return schemas

    def disconnect(self) -> None:
        """Disconnect from Google Sheets (cleanup)."""
        self._client = None
        self._spreadsheet = None
