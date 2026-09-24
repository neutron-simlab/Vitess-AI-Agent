"""Cross-process guarantees for deleting a VITESS thread workspace."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest

from vitess_ai.server import uploads as uploads_module
from vitess_ai.server.uploads import UploadStore
from vitess_ai.workspace_lock import (
    ThreadWorkspaceDeleted,
    hold_thread_workspace,
)

THREAD = UUID("11111111-1111-4111-8111-111111111111")


@pytest.fixture
def store(tmp_path: Path) -> UploadStore:
    return UploadStore(
        tmp_path / "projects", max_bytes=1024, allowed_extensions=(".dat",)
    )


def test_active_simulation_prevents_workspace_deletion(store: UploadStore) -> None:
    workspace = store.root / str(THREAD)
    workspace.mkdir(parents=True)
    marker = workspace / "still-running.dat"
    marker.write_bytes(b"running\n")

    with hold_thread_workspace(store.root, str(THREAD)):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path;"
                " import sys;"
                " from vitess_ai.server.uploads import UploadStore;"
                " from vitess_ai.workspace_lock import ThreadWorkspaceBusy;"
                " store = UploadStore(Path(sys.argv[1]), max_bytes=1,"
                " allowed_extensions=(\".dat\",));"
                "\ntry: store.delete_thread(sys.argv[2])"
                "\nexcept ThreadWorkspaceBusy: raise SystemExit(0)"
                "\nraise SystemExit(1)",
                str(store.root),
                str(THREAD),
            ],
            capture_output=True,
            text=True,
        )

    assert result.returncode == 0, result.stderr
    assert marker.read_bytes() == b"running\n"


def test_deleted_workspace_refuses_a_late_simulation(store: UploadStore) -> None:
    workspace = store.root / str(THREAD)
    workspace.mkdir(parents=True)
    (workspace / "result.dat").write_bytes(b"done\n")

    store.delete_thread(str(THREAD))

    assert not workspace.exists()
    with pytest.raises(ThreadWorkspaceDeleted, match="has been deleted"):
        with hold_thread_workspace(store.root, str(THREAD)):
            pytest.fail("a deleted thread must not admit a new writer")


def test_failed_cleanup_does_not_leave_the_live_chat_tombstoned(
    store: UploadStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = store.root / str(THREAD)
    workspace.mkdir(parents=True)

    def fail_cleanup(_directory: Path) -> None:
        raise OSError("volume is busy")

    monkeypatch.setattr(uploads_module.shutil, "rmtree", fail_cleanup)

    with pytest.raises(OSError, match="volume is busy"):
        store.delete_thread(str(THREAD))

    with hold_thread_workspace(store.root, str(THREAD)):
        assert workspace.is_dir()
