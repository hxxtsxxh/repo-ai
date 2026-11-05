"""Cross-process locking for the index and generated files.

Hooks can fire concurrently (two Claude sessions in one repo, a Stop hook
racing a manual `repo-ai update`). Writers take an exclusive advisory lock;
a hook that cannot get it immediately simply skips its refresh rather than
queueing up behind it — that is what prevents fork storms.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator
from pathlib import Path

try:  # POSIX
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows
    import msvcrt  # type: ignore[import-not-found]
except ImportError:
    msvcrt = None  # type: ignore[assignment]


def _try_lock(fd: int) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    if msvcrt is not None:  # pragma: no cover - Windows
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    return True  # no locking primitive available: best effort


def _unlock(fd: int) -> None:
    if fcntl is not None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
    elif msvcrt is not None:  # pragma: no cover
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = 60.0) -> Iterator[bool]:
    """Yield True once the lock is held, False if `timeout` elapsed.

    `timeout=0` makes it a non-blocking try-lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o644)
    acquired = False
    try:
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            acquired = _try_lock(fd)
            if acquired or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        if acquired:
            with contextlib.suppress(OSError):
                os.ftruncate(fd, 0)
                os.write(fd, f"{os.getpid()}\n".encode())
        yield acquired
    finally:
        if acquired:
            _unlock(fd)
        os.close(fd)


def is_locked(path: Path) -> bool:
    if not path.exists():
        return False
    with file_lock(path, timeout=0) as got:
        return not got
