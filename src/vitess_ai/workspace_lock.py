"""Cross-process exclusion between VITESS writers and thread deletion."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

__all__ = [
    "ThreadWorkspaceBusy",
    "ThreadWorkspaceDeleted",
    "hold_thread_workspace",
    "hold_thread_workspace_deletion",
]

_DELETED = b"deleted\n"


class ThreadWorkspaceBusy(RuntimeError):
    """Raised when deletion finds a simulation still using the workspace."""


class ThreadWorkspaceDeleted(RuntimeError):
    """Raised when a late writer targets a thread that was already deleted."""


def _canonical_thread_id(thread_id: str) -> str:
    try:
        canonical = str(UUID(thread_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("thread_id must be a UUID") from exc
    if thread_id != canonical:
        raise ValueError("thread_id must use canonical UUID form")
    return canonical


def _open_lock(project_root: Path, thread_id: str) -> int:
    root = project_root.expanduser().resolve()
    lock_root = root / ".thread-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    if lock_root.is_symlink() or lock_root.resolve().parent != root:
        raise ValueError("Thread lock directory must stay inside the project root")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    return os.open(lock_root / f"{_canonical_thread_id(thread_id)}.lock", flags, 0o600)


def _read_marker(fd: int) -> bytes:
    return os.pread(fd, len(_DELETED), 0)


def _write_marker(fd: int, marker: bytes) -> None:
    os.ftruncate(fd, 0)
    if marker:
        os.pwrite(fd, marker, 0)
    os.fsync(fd)


@contextmanager
def hold_thread_workspace(project_root: Path, thread_id: str) -> Iterator[None]:
    """Hold a shared lock while a simulation can create thread output files."""

    fd = _open_lock(project_root, thread_id)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        if _read_marker(fd) == _DELETED:
            raise ThreadWorkspaceDeleted(f"Thread {thread_id} has been deleted")
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def hold_thread_workspace_deletion(
    project_root: Path, thread_id: str
) -> Iterator[None]:
    """Tombstone a thread while holding its exclusive deletion lock.

    A normal cleanup failure restores the previous marker so the still-visible
    chat remains usable and deletion can be retried. A process crash leaves the
    tombstone behind, which is safer than allowing a detached simulation to
    recreate files after deletion.
    """

    fd = _open_lock(project_root, thread_id)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ThreadWorkspaceBusy(
                f"Thread {thread_id} has an active simulation"
            ) from exc
        previous = _read_marker(fd)
        _write_marker(fd, _DELETED)
        try:
            yield
        except BaseException:
            _write_marker(fd, previous)
            raise
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
