"""Small Linux process locks for shared trading state.

The Linux brain runs master and the Telegram signal daemon concurrently. A
file's atomic rename prevents torn JSON, but it does not prevent two
read-modify-write cycles from overwriting each other's newer risk snapshot.
This module serializes those critical sections without coupling the daemons
or introducing a service dependency.
"""
from __future__ import annotations

import contextlib
import time

from engines import paths

try:  # The production brain is Linux; keep imports/test collection portable.
    import fcntl
except ImportError:  # pragma: no cover - only non-POSIX development hosts
    fcntl = None


@contextlib.contextmanager
def exclusive(name: str, *, timeout: float = 10.0):
    """Hold an exclusive lock below the active data root.

    Raises ``TimeoutError`` rather than yielding an unlocked critical section.
    Callers that cannot safely refresh their state should fail closed and skip
    the entry, not race a second account snapshot.
    """
    if not name or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in name):
        raise ValueError("lock name must be a simple lowercase identifier")
    if fcntl is None:
        # Windows is the execution arm, not the risk/state brain. Refusing to
        # pretend a POSIX lock exists is safer than silently running unlocked.
        raise RuntimeError("POSIX process locks are unavailable")

    lock_dir = paths.data_dir() / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{name}.lock"
    handle = lock_path.open("a+", encoding="utf-8")
    deadline = time.monotonic() + max(0.0, float(timeout))
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for state lock: {name}")
                time.sleep(0.05)
        yield lock_path
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
