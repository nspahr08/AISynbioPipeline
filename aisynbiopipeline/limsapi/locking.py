"""
Shared filesystem lock for database-touching operations.

Both syncing and archiving mutate or copy the SQLite mirror. To guarantee that
only one such operation ever runs at a time - no matter how it was launched
(cron, the CLI, a notebook, or the library) - they all acquire the same lock
via the ``db_lock`` context manager below.

The lock uses ``fcntl.flock`` (BSD advisory locks), which:
- interoperates with the ``flock(1)`` command-line utility,
- is held per open file description and released automatically when the process
  exits (including on crash or ``kill -9``), so there are no stale locks to
  clean up, and
- must live on LOCAL disk: flock over NFS is unreliable. All jobs run on the
  same host, so a local lock file is correct and sufficient.

Do NOT unlink the lock file on release: removing a held lock file lets another
process create and lock a different inode with the same name, defeating the lock.
"""

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from .config import load_config


class LockBusyError(Exception):
    """Raised when the DB lock is held by another process and cannot be acquired."""


def get_lock_path(config: Optional[Dict[str, Any]] = None) -> Path:
    """
    Get the path to the shared DB lock file (must be on local disk).

    Args:
        config: Configuration dict (loads from file if not provided)

    Returns:
        Path object for the lock file
    """
    if config is None:
        config = load_config()

    lock_file = config['sync'].get(
        'lock_file', str(Path.home() / '.cache' / 'lims' / 'lims.lock')
    )
    return Path(lock_file)


@contextmanager
def db_lock(
    config: Optional[Dict[str, Any]] = None,
    blocking: bool = False,
    timeout: Optional[float] = None,
    poll_interval: float = 0.5,
):
    """
    Acquire the shared DB lock for the duration of the ``with`` block.

    Args:
        config: Configuration dict (loads from file if not provided)
        blocking: If False (default), fail immediately when the lock is held.
            If True, wait for it (up to ``timeout`` seconds if given).
        timeout: Max seconds to wait when ``blocking`` is True. None means wait
            forever.
        poll_interval: Seconds between acquisition attempts while blocking.

    Yields:
        The Path to the lock file once the lock is held.

    Raises:
        LockBusyError: If the lock cannot be acquired (non-blocking and held, or
            blocking and ``timeout`` elapsed).
    """
    if config is None:
        config = load_config()

    lock_path = get_lock_path(config)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o666)

    deadline = None if timeout is None else time.monotonic() + timeout
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if not blocking:
                    raise LockBusyError(
                        f"DB lock is held by another process: {lock_path}"
                    )
                if deadline is not None and time.monotonic() >= deadline:
                    raise LockBusyError(
                        f"Timed out after {timeout}s waiting for DB lock: "
                        f"{lock_path}"
                    )
                time.sleep(poll_interval)

        # Record the PID for observability (purely informational).
        try:
            os.ftruncate(lock_fd, 0)
            os.lseek(lock_fd, 0, os.SEEK_SET)
            os.write(lock_fd, str(os.getpid()).encode())
            os.fsync(lock_fd)
        except OSError:
            pass

        yield lock_path

    finally:
        if acquired:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(lock_fd)
        # Intentionally do NOT unlink the lock file (see module docstring).
