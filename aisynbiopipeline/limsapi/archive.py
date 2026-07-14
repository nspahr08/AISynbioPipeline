"""
Database archival module.

This module handles automatic archiving of the SQLite database with
retention policies for hourly, daily, weekly, and monthly backups.
"""

import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import re

from .config import load_config, get_db_path, get_archive_path
from .locking import db_lock


class ArchiveManager:
    """
    Manages database archives with retention policies.

    Handles creation, compression, restoration, and cleanup of database backups.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the ArchiveManager.

        Args:
            config: Configuration dict (loads from file if not provided)
        """
        if config is None:
            config = load_config()

        self.config = config
        self.db_path = get_db_path(config)
        self.archive_path = get_archive_path(config)
        self.retention = config['archive']

    def _get_archive_filename(self, archive_type: str, timestamp: datetime) -> str:
        """
        Generate archive filename based on type and timestamp.

        Args:
            archive_type: Type of archive (hourly, daily, weekly, monthly)
            timestamp: Timestamp for the archive

        Returns:
            Archive filename
        """
        if archive_type == 'hourly':
            name = f"lims_hourly_{timestamp.strftime('%Y%m%d_%H')}.db"
        elif archive_type == 'daily':
            name = f"lims_daily_{timestamp.strftime('%Y%m%d')}.db"
        elif archive_type == 'weekly':
            name = f"lims_weekly_{timestamp.strftime('%Y%m%d')}.db"
        elif archive_type == 'monthly':
            name = f"lims_monthly_{timestamp.strftime('%Y%m')}.db"
        else:
            raise ValueError(f"Invalid archive type: {archive_type}")

        if self.retention.get('compression', True):
            name += '.gz'

        return name

    def create_archive(self, archive_type: str = 'manual') -> Path:
        """
        Create an archive of the current database.

        Args:
            archive_type: Type of archive (hourly, daily, weekly, monthly, manual)

        Returns:
            Path to created archive file

        Raises:
            Exception: If archive creation fails
        """
        if not self.db_path.exists():
            raise Exception(f"Database file not found: {self.db_path}")

        timestamp = datetime.now()

        if archive_type == 'manual':
            archive_name = f"lims_manual_{timestamp.strftime('%Y%m%d_%H%M%S')}.db"
            if self.retention.get('compression', True):
                archive_name += '.gz'
        else:
            archive_name = self._get_archive_filename(archive_type, timestamp)

        archive_file = self.archive_path / archive_name

        try:
            # Hold the shared DB lock (waiting for any in-flight sync) so the
            # copy captures a quiescent database. NOTE: a plain file copy is
            # only consistent because the DB uses rollback-journal mode and all
            # connections are closed between syncs. If the DB is ever switched
            # to WAL, switch this to `VACUUM INTO` or the sqlite3 online-backup
            # API, which also capture the -wal file.
            with db_lock(self.config, blocking=True, timeout=300):
                if self.retention.get('compression', True):
                    # Compress while copying
                    with open(self.db_path, 'rb') as f_in:
                        with gzip.open(archive_file, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                else:
                    # Just copy
                    shutil.copy2(self.db_path, archive_file)

            return archive_file

        except Exception as e:
            raise Exception(f"Failed to create archive: {e}")

    def restore_archive(self, archive_name: str, target_path: Optional[Path] = None) -> Path:
        """
        Restore a database from an archive.

        Args:
            archive_name: Name of the archive file to restore
            target_path: Target path for restored database (uses db_path if not provided)

        Returns:
            Path to restored database file

        Raises:
            Exception: If restore fails
        """
        archive_file = self.archive_path / archive_name

        if not archive_file.exists():
            raise Exception(f"Archive file not found: {archive_file}")

        if target_path is None:
            target_path = self.db_path

        try:
            if archive_name.endswith('.gz'):
                # Decompress while restoring
                with gzip.open(archive_file, 'rb') as f_in:
                    with open(target_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            else:
                # Just copy
                shutil.copy2(archive_file, target_path)

            return target_path

        except Exception as e:
            raise Exception(f"Failed to restore archive: {e}")

    def list_archives(self, archive_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List available archives.

        Args:
            archive_type: Filter by archive type (hourly, daily, weekly, monthly, manual)

        Returns:
            List of archive information dictionaries
        """
        pattern = f"lims_{archive_type}_*" if archive_type else "lims_*"
        archive_files = sorted(self.archive_path.glob(pattern))

        archives = []
        for archive_file in archive_files:
            # Parse archive info from filename
            info = self._parse_archive_filename(archive_file.name)
            if info:
                info['path'] = str(archive_file)
                info['size_bytes'] = archive_file.stat().st_size
                archives.append(info)

        return archives

    @staticmethod
    def _parse_archive_filename(filename: str) -> Optional[Dict[str, Any]]:
        """
        Parse archive filename to extract metadata.

        Args:
            filename: Archive filename

        Returns:
            Dictionary with archive metadata or None if invalid
        """
        # Remove .gz extension if present
        name = filename.replace('.gz', '').replace('.db', '')

        # Match patterns
        patterns = {
            'hourly': r'lims_hourly_(\d{8})_(\d{2})',
            'daily': r'lims_daily_(\d{8})',
            'weekly': r'lims_weekly_(\d{8})',
            'monthly': r'lims_monthly_(\d{6})',
            'manual': r'lims_manual_(\d{8})_(\d{6})'
        }

        for archive_type, pattern in patterns.items():
            match = re.match(pattern, name)
            if match:
                info = {
                    'filename': filename,
                    'type': archive_type,
                    'compressed': filename.endswith('.gz')
                }

                # Parse timestamp based on type
                if archive_type == 'hourly':
                    date_str = match.group(1) + match.group(2)
                    timestamp = datetime.strptime(date_str, '%Y%m%d%H')
                elif archive_type == 'daily' or archive_type == 'weekly':
                    timestamp = datetime.strptime(match.group(1), '%Y%m%d')
                elif archive_type == 'monthly':
                    timestamp = datetime.strptime(match.group(1), '%Y%m')
                elif archive_type == 'manual':
                    date_str = match.group(1) + match.group(2)
                    timestamp = datetime.strptime(date_str, '%Y%m%d%H%M%S')
                else:
                    continue

                info['timestamp'] = timestamp.isoformat()
                return info

        return None

    def cleanup_archives(self) -> Dict[str, int]:
        """
        Clean up old archives based on retention policy.

        Returns:
            Dictionary with counts of deleted archives by type

        Raises:
            Exception: If cleanup fails
        """
        deleted_counts = {
            'hourly': 0,
            'daily': 0,
            'weekly': 0,
            'monthly': 0
        }

        now = datetime.now()

        for archive_type in ['hourly', 'daily', 'weekly', 'monthly']:
            retention = self.retention.get(f'{archive_type}_retention', -1)

            if retention == -1:
                # Keep forever
                continue

            if retention == 0:
                # Delete all
                archives = self.list_archives(archive_type)
            else:
                # Calculate cutoff date
                if archive_type == 'hourly':
                    cutoff = now - timedelta(hours=retention)
                elif archive_type == 'daily':
                    cutoff = now - timedelta(days=retention)
                elif archive_type == 'weekly':
                    cutoff = now - timedelta(weeks=retention)
                elif archive_type == 'monthly':
                    # Approximate months as 30 days
                    cutoff = now - timedelta(days=retention * 30)
                else:
                    continue

                # Get archives older than cutoff
                archives = [
                    a for a in self.list_archives(archive_type)
                    if datetime.fromisoformat(a['timestamp']) < cutoff
                ]

            # Delete old archives
            for archive in archives:
                try:
                    Path(archive['path']).unlink()
                    deleted_counts[archive_type] += 1
                except Exception as e:
                    # Log error but continue
                    print(f"Warning: Failed to delete archive {archive['filename']}: {e}")

        return deleted_counts


def create_archive(archive_type: str = 'manual', config: Optional[Dict[str, Any]] = None) -> str:
    """
    Create a database archive.

    Args:
        archive_type: Type of archive (hourly, daily, weekly, monthly, manual)
        config: Configuration dict (loads from file if not provided)

    Returns:
        Path to created archive file as string

    Raises:
        Exception: If archive creation fails
    """
    manager = ArchiveManager(config)
    archive_path = manager.create_archive(archive_type)
    return str(archive_path)


def restore_archive(archive_name: str, target_path: Optional[str] = None,
                   config: Optional[Dict[str, Any]] = None) -> str:
    """
    Restore a database from an archive.

    Args:
        archive_name: Name of the archive file to restore
        target_path: Target path for restored database (optional)
        config: Configuration dict (loads from file if not provided)

    Returns:
        Path to restored database file as string

    Raises:
        Exception: If restore fails
    """
    manager = ArchiveManager(config)
    target = Path(target_path) if target_path else None
    restored_path = manager.restore_archive(archive_name, target)
    return str(restored_path)


def list_archives(archive_type: Optional[str] = None,
                 config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    List available archives.

    Args:
        archive_type: Filter by archive type (optional)
        config: Configuration dict (loads from file if not provided)

    Returns:
        List of archive information dictionaries
    """
    manager = ArchiveManager(config)
    return manager.list_archives(archive_type)


def cleanup_archives(config: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """
    Clean up old archives based on retention policy.

    Args:
        config: Configuration dict (loads from file if not provided)

    Returns:
        Dictionary with counts of deleted archives by type

    Raises:
        Exception: If cleanup fails
    """
    manager = ArchiveManager(config)
    return manager.cleanup_archives()
