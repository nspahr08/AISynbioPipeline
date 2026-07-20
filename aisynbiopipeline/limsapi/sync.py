"""
Synchronization daemon module.

This module handles the synchronization between Google Sheets and the SQLite
mirror database, including a background daemon with scheduling.
"""

import fcntl
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from .config import load_config
from .sheets import SheetsReader
from .database import DatabaseManager
from .locking import db_lock, LockBusyError


# Global daemon state
_daemon_thread: Optional[threading.Thread] = None
_daemon_running = False
_daemon_lock_fd: Optional[int] = None
_sync_status = {
    'last_sync': None,
    'last_success': None,
    'last_error': None,
    'syncs_completed': 0,
    'syncs_failed': 0
}


def configure_logging(config: Dict[str, Any]) -> logging.Logger:
    """
    Configure logging for sync operations.

    Args:
        config: Configuration dict

    Returns:
        Configured logger instance
    """
    log_level = config['sync'].get('log_level', 'INFO')
    # log_file = Path(__file__).parent.parent.parent / config['sync'].get('log_file')
    log_file = config['sync'].get('log_file')
    
    logger = logging.getLogger('lims_sync')
    logger.setLevel(getattr(logging, log_level))

    # Remove existing handlers
    logger.handlers = []

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level))
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, log_level))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def _get_daemon_lock_path(config: Dict[str, Any]) -> Path:
    """
    Get the path to the daemon lock file.

    Args:
        config: Configuration dict

    Returns:
        Path object for the lock file
    """
    lock_file = config['sync'].get(
        'lock_file'
    )
    return Path(lock_file)


def _acquire_daemon_lock(
    logger: logging.Logger,
    config: Dict[str, Any]
) -> Optional[int]:
    """
    Acquire an exclusive lock for the sync daemon.

    Uses fcntl file locking to ensure only one daemon can run across
    multiple processes on the same system.

    Args:
        logger: Logger instance
        config: Configuration dict

    Returns:
        Lock file descriptor if acquired, None if lock already held

    Raises:
        Exception: If lock file cannot be created or accessed
    """
    lock_path = _get_daemon_lock_path(config)
    logger.debug(f"Attempting to acquire lock at {lock_path}")

    try:

        # Open/create lock file
        lock_fd = os.open(
            str(lock_path),
            os.O_CREAT | os.O_RDWR,
            0o666
        )

        # Try to acquire exclusive lock (non-blocking)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write current PID to lock file
            os.ftruncate(lock_fd, 0)
            os.lseek(lock_fd, 0, os.SEEK_SET)
            pid_str = str(os.getpid())
            os.write(lock_fd, pid_str.encode())
            os.fsync(lock_fd)

            logger.debug(
                f"Successfully acquired daemon lock (PID: {os.getpid()})"
            )
            return lock_fd

        except BlockingIOError:
            # Lock is held by another process
            os.close(lock_fd)
            try:
                # Try to read the PID from the lock file
                with open(lock_path, 'r') as f:
                    other_pid = f.read().strip()
                logger.warning(
                    f"Daemon lock is held by process {other_pid}"
                )
            except Exception:
                logger.warning("Daemon lock is held by another process")
            return None

    except Exception as e:
        logger.error(f"Failed to acquire daemon lock: {e}")
        raise


def _release_daemon_lock(
    logger: logging.Logger,
    lock_fd: int,
    config: Dict[str, Any]
) -> None:
    """
    Release the daemon lock.

    Args:
        logger: Logger instance
        lock_fd: Lock file descriptor
        config: Configuration dict
    """
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

        lock_path = _get_daemon_lock_path(config)
        lock_path.unlink(missing_ok=True)

        logger.debug("Successfully released daemon lock")

    except Exception as e:
        logger.error(f"Failed to release daemon lock: {e}")


def _get_status_path(config: Dict[str, Any]) -> Optional[Path]:
    """Return the configured sync status file path, or None if unset."""
    status_file = config['sync'].get('status_file')
    return Path(status_file) if status_file else None


def _write_status(config: Dict[str, Any], sync_result: Dict[str, Any]) -> None:
    """
    Persist the latest sync status to the configured status file.

    Each cron sync runs as its own process, so the in-memory ``_sync_status``
    globals are useless across runs. This writes a small JSON file (atomically,
    via a temp file + ``os.replace``) that ``lims status`` can read. Cumulative
    counters are kept via read-modify-write, which is race-free because sync
    holds the DB lock for its whole run.
    """
    status_path = _get_status_path(config)
    if status_path is None:
        return

    try:
        status_path.parent.mkdir(parents=True, exist_ok=True)

        prev: Dict[str, Any] = {}
        try:
            with open(status_path, 'r') as f:
                prev = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            prev = {}

        success = sync_result.get('success', False)
        status = {
            'last_sync': sync_result.get('end_time') or sync_result.get('start_time'),
            'last_success': (
                sync_result.get('end_time') if success else prev.get('last_success')
            ),
            'last_error': (
                None if success
                else (sync_result.get('errors') or [None])[-1] or prev.get('last_error')
            ),
            'syncs_completed': prev.get('syncs_completed', 0) + (1 if success else 0),
            'syncs_failed': prev.get('syncs_failed', 0) + (0 if success else 1),
            'last_result': sync_result,
        }

        fd, tmp_path = tempfile.mkstemp(
            dir=str(status_path.parent), prefix='.sync_status_', suffix='.tmp'
        )
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(status, f, indent=2, default=str)
            os.replace(tmp_path, status_path)
        except Exception:
            # Clean up the temp file on failure; never mask the sync outcome.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:  # pragma: no cover - status is best-effort
        logging.getLogger('lims_sync').warning(f"Failed to write sync status: {e}")


def sync_all_sheets(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Perform a full sync of all sheets from Google Sheets to SQLite.

    Acquires the shared DB lock (non-blocking) so it can never run concurrently
    with another sync or an archive, regardless of how it was launched (cron,
    CLI, notebook). If the lock is already held, the sync is skipped (returns a
    result with ``skipped=True``) rather than piling up.

    Args:
        config: Configuration dict (loads from file if not provided)

    Returns:
        Dictionary with sync statistics

    Raises:
        Exception: If sync fails critically
    """
    if config is None:
        config = load_config()

    logger = configure_logging(config)

    try:
        with db_lock(config, blocking=False):
            return _sync_all_sheets_locked(config, logger)
    except LockBusyError:
        logger.warning(
            "Another sync or archive is in progress; skipping this sync"
        )
        return {
            'start_time': datetime.now().isoformat(),
            'end_time': datetime.now().isoformat(),
            'success': False,
            'skipped': True,
            'tables_synced': 0,
            'total_rows_inserted': 0,
            'total_rows_updated': 0,
            'total_rows_deleted': 0,
            'errors': [],
        }


def _sync_all_sheets_locked(
    config: Dict[str, Any], logger: logging.Logger
) -> Dict[str, Any]:
    """Run the actual sync while holding the DB lock (see ``sync_all_sheets``)."""
    sync_result = {
        'start_time': datetime.now().isoformat(),
        'end_time': None,
        'success': False,
        'skipped': False,
        'tables_synced': 0,
        'total_rows_inserted': 0,
        'total_rows_updated': 0,
        'total_rows_deleted': 0,
        'errors': []
    }

    sheets_reader = None
    db_manager = None

    try:
        logger.info("Starting sync operation")

        # Connect to Google Sheets
        logger.info("Connecting to Google Sheets")
        sheets_reader = SheetsReader(config)
        sheets_reader.connect()

        # Connect to database
        logger.info("Connecting to database")
        db_manager = DatabaseManager(config)
        db_manager.connect()

        # Get all worksheet names
        worksheet_names = sheets_reader.get_worksheet_names()
        logger.info(f"Found {len(worksheet_names)} worksheets: {', '.join(worksheet_names)}")

        # Sync each worksheet
        for i, worksheet_name in enumerate(worksheet_names):
            try:
                # Add delay between worksheets to avoid rate limits (skip first worksheet)
                if i > 0:
                    delay = config['google_sheets'].get('worksheet_delay', 1.0)
                    if delay > 0:
                        logger.debug(f"Waiting {delay}s before next worksheet to avoid rate limits")
                        time.sleep(delay)

                logger.info(f"Syncing worksheet: {worksheet_name}")

                # Get schema from sheet
                sheet_schema = sheets_reader.get_worksheet_schema(worksheet_name)
                logger.debug(f"Schema for {worksheet_name}: {sheet_schema}")

                # Sync database schema
                db_manager.sync_schema(worksheet_name, sheet_schema)

                # Get all data from sheet
                sheet_data = sheets_reader.get_worksheet_data(worksheet_name)
                logger.info(f"Retrieved {len(sheet_data)} rows from {worksheet_name}")

                if sheet_data:
                    # Upsert rows
                    inserted, updated = db_manager.upsert_rows(worksheet_name, sheet_data)
                    sync_result['total_rows_inserted'] += inserted
                    sync_result['total_rows_updated'] += updated
                    logger.info(f"Inserted {inserted}, updated {updated} rows in {worksheet_name}")

                    # Calculate hashes for current data (must sanitize keys like upsert_rows does)
                    current_hashes = []
                    for row in sheet_data:
                        sanitized_row = {
                            k.replace(' ', '_').replace('-', '_'): v
                            for k, v in row.items()
                        }
                        current_hashes.append(db_manager.calculate_row_hash(sanitized_row))

                    # Mark deleted rows
                    deleted = db_manager.mark_deleted_rows(worksheet_name, current_hashes)
                    sync_result['total_rows_deleted'] += deleted
                    if deleted > 0:
                        logger.info(f"Marked {deleted} rows as deleted in {worksheet_name}")
                else:
                    logger.info(f"No data in {worksheet_name}, marking all rows as deleted")
                    deleted = db_manager.mark_deleted_rows(worksheet_name, [])
                    sync_result['total_rows_deleted'] += deleted

                sync_result['tables_synced'] += 1

            except Exception as e:
                error_msg = f"Error syncing worksheet {worksheet_name}: {str(e)}"
                logger.error(error_msg)
                sync_result['errors'].append(error_msg)
                # Continue with next worksheet

        sync_result['success'] = True
        sync_result['end_time'] = datetime.now().isoformat()

        logger.info(
            f"Sync completed successfully. "
            f"Synced {sync_result['tables_synced']} tables, "
            f"inserted {sync_result['total_rows_inserted']}, "
            f"updated {sync_result['total_rows_updated']}, "
            f"deleted {sync_result['total_rows_deleted']} rows"
        )

        # Update global status
        _sync_status['last_sync'] = sync_result['end_time']
        _sync_status['last_success'] = sync_result['end_time']
        _sync_status['syncs_completed'] += 1

        return sync_result

    except Exception as e:
        error_msg = f"Sync failed: {str(e)}"
        logger.error(error_msg)
        sync_result['errors'].append(error_msg)
        sync_result['end_time'] = datetime.now().isoformat()

        # Update global status
        _sync_status['last_sync'] = sync_result['end_time']
        _sync_status['last_error'] = error_msg
        _sync_status['syncs_failed'] += 1

        raise

    finally:
        # Persist status for cross-process `lims status` (best-effort), while
        # still holding the DB lock so the read-modify-write is race-free.
        _write_status(config, sync_result)

        # Cleanup connections
        if sheets_reader:
            sheets_reader.disconnect()
        if db_manager:
            db_manager.disconnect()


def _daemon_worker(config: Dict[str, Any]) -> None:
    """
    Worker function for the background sync daemon.

    Args:
        config: Configuration dict
    """
    global _daemon_running

    import schedule  # deprecated daemon only; imported lazily so the cron/CLI
                     # path doesn't require the `schedule` package.

    logger = configure_logging(config)
    interval_minutes = config['sync']['interval_minutes']

    logger.info(f"Sync daemon started with {interval_minutes} minute interval")

    # Schedule the sync job
    schedule.every(interval_minutes).minutes.do(sync_all_sheets, config)

    # Run initial sync
    try:
        sync_all_sheets(config)
    except Exception as e:
        logger.error(f"Initial sync failed: {e}")

    # Keep running scheduled jobs
    while _daemon_running:
        schedule.run_pending()
        time.sleep(1)

    logger.info("Sync daemon stopped")


def start_sync_daemon(config: Optional[Dict[str, Any]] = None) -> None:
    """
    Start the background sync daemon.

    Args:
        config: Configuration dict (loads from file if not provided)

    Raises:
        Exception: If daemon is already running or lock cannot be acquired
    """
    global _daemon_thread, _daemon_running, _daemon_lock_fd

    if _daemon_running:
        raise Exception(
            "Sync daemon is already running in this process"
        )

    if config is None:
        config = load_config()

    if not config['sync']['enabled']:
        raise Exception("Sync is disabled in configuration")

    logger = configure_logging(config)

    # Try to acquire system-wide lock BEFORE setting state
    _daemon_lock_fd = _acquire_daemon_lock(logger, config)
    if _daemon_lock_fd is None:
        raise Exception(
            "Sync daemon is already running "
            "(locked by another process)"
        )

    try:
        _daemon_running = True  # Set state AFTER lock acquired
        _daemon_thread = threading.Thread(
            target=_daemon_worker,
            args=(config,),
            daemon=True
        )
        _daemon_thread.start()

    except Exception:
        # Rollback state and release lock if thread creation fails
        _daemon_running = False
        if _daemon_lock_fd is not None:
            _release_daemon_lock(logger, _daemon_lock_fd, config)
            _daemon_lock_fd = None
        raise


def stop_sync_daemon() -> None:
    """
    Stop the background sync daemon.

    Raises:
        Exception: If daemon is not running
    """
    global _daemon_running, _daemon_thread, _daemon_lock_fd

    if not _daemon_running:
        raise Exception("Sync daemon is not running")

    config = load_config()
    logger = configure_logging(config)

    try:
        _daemon_running = False  # Signal thread to stop

        if _daemon_thread:
            _daemon_thread.join(timeout=10)
            if _daemon_thread.is_alive():
                logger.warning(
                    "Daemon thread did not stop cleanly "
                    "within timeout"
                )
            _daemon_thread = None

    finally:
        # Always release lock, even if thread join fails
        if _daemon_lock_fd is not None:
            _release_daemon_lock(logger, _daemon_lock_fd, config)
            _daemon_lock_fd = None


def get_sync_status(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get the latest sync status.

    Reads the persisted status file (written by every sync run) so it works
    across independent processes, e.g. cron syncs and a separate ``lims status``
    invocation. Falls back to this process's in-memory status if the file is
    missing or unreadable.

    Args:
        config: Configuration dict (loads from file if not provided)

    Returns:
        Dictionary with sync status information
    """
    if config is None:
        config = load_config()

    status_path = _get_status_path(config)
    if status_path is not None:
        try:
            with open(status_path, 'r') as f:
                persisted = json.load(f)
            return {
                'last_sync': persisted.get('last_sync'),
                'last_success': persisted.get('last_success'),
                'last_error': persisted.get('last_error'),
                'syncs_completed': persisted.get('syncs_completed', 0),
                'syncs_failed': persisted.get('syncs_failed', 0),
            }
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    # Fallback: in-memory status for the current process only.
    return {
        'last_sync': _sync_status['last_sync'],
        'last_success': _sync_status['last_success'],
        'last_error': _sync_status['last_error'],
        'syncs_completed': _sync_status['syncs_completed'],
        'syncs_failed': _sync_status['syncs_failed']
    }
