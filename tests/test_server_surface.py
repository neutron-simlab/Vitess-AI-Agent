"""CP6: what the application serves, what it refuses, and where a file lands.

The service module configures core and registers both agents **at import**, and
`juena_core.configure()` is process-global. So the tests that import it run in a
subprocess: importing it in-process would replace the settings `conftest.py`
installed for every other test in the session, and the failure would surface
somewhere else entirely.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import asyncio
import subprocess
import sys
from types import SimpleNamespace
from threading import Barrier, Lock
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import UploadFile

from vitess_ai.config import Config, configure_core
from vitess_ai.modules.catalog import upload_modules
from vitess_ai.server.file_endpoints import _read_upload_bytes, build_file_router
from vitess_ai.server.uploads import (
    MAGIC_NUMBERS,
    UploadRefused,
    UploadStore,
    upload_module_manifest,
    upload_module_names,
)

THREAD = UUID("11111111-1111-4111-8111-111111111111")

#: What `vitess-ai` serves: core's surface plus the upload route, and nothing
#: else. Written out rather than derived, because the point of the assertion is
#: to notice a route appearing that nobody decided to add.
EXPECTED_ROUTES = {
    "/artifacts/{artifact_id}",
    "/chats",
    "/chats/{thread_id}",
    "/files/modules",
    "/files/{thread_id}",
    "/files/{thread_id}/{module}",
    "/files/{thread_id}/{module}/{filename}",
    "/health",
    "/resume",
    "/stream",
    "/stream_with_files",
    "/threads/{thread_id}",
    "/threads/{thread_id}/pending-approval",
    "/threads/{thread_id}/pending-interrupt",
    "/{agent_id}/resume",
    "/{agent_id}/stream",
    "/{agent_id}/stream_with_files",
}


def _in_a_fresh_process(source: str, tmp_path: Path, **environment: str) -> str:
    """Run one snippet against a service that configures itself on import."""

    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "DATABASE_URL": "postgresql://vitess:secret@postgres:5432/vitess",
            "BLABLADOR_API_KEY": "not-used-by-these-tests",
            "VITESS_PROJECT_PATH": str(tmp_path / "projects"),
            "VITESS_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
            "VITESS_AUDIT_FILE": str(tmp_path / "artifacts/audit.jsonl"),
            "LOG_DIR": str(tmp_path / "logs"),
            **environment,
        },
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


# --------------------------------------------------------------------------
# The served surface
# --------------------------------------------------------------------------


def test_the_application_serves_exactly_the_documented_routes(tmp_path: Path) -> None:
    printed = _in_a_fresh_process(
        "import json;"
        " from vitess_ai.server.service import app;"
        " print(json.dumps(sorted(app.openapi()['paths'])))",
        tmp_path,
    )

    assert set(json.loads(printed.splitlines()[-1])) == EXPECTED_ROUTES


def test_nothing_under_auth_is_served(tmp_path: Path) -> None:
    """There is no institute login here, and no route that pretends there is.

    v2 inherits Postgres but not SAML. Identity is a fixed local principal
    injected where a real provider's dependency would go, so adopting a login
    later replaces one callable instead of rewriting any route.
    """
    printed = _in_a_fresh_process(
        "import json;"
        " from vitess_ai.server.service import app;"
        " print(json.dumps(sorted(app.openapi()['paths'])))",
        tmp_path,
    )

    assert not [path for path in json.loads(printed.splitlines()[-1]) if "/auth" in path]


def test_importing_the_service_registers_both_agents(tmp_path: Path) -> None:
    """The side-effect import trap, transplanted from juena-chatbot.

    A registry filled only by a main script leaves `uvicorn
    vitess_ai.server.service:app` with nothing registered, and every invocation
    404s. Importing this module has to be enough.
    """
    printed = _in_a_fresh_process(
        "import json, vitess_ai.server.service;"
        " from juena_core.server.agent.registry import list_registered_agents, get_default_agent;"
        " print(json.dumps([sorted(list_registered_agents()), get_default_agent()]))",
        tmp_path,
    )
    registered, default = json.loads(printed.splitlines()[-1])

    assert registered == ["advanced_mode", "vitess"]
    assert default == "vitess"


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"DATABASE_URL": ""}, "DATABASE_URL"),
        ({"BLABLADOR_API_KEY": "", "OPENAI_API_KEY": ""}, "API_KEY"),
        # This deployment's own sentence, not core's. Core refuses the same
        # pairing a moment later with "local_principal authenticates nobody",
        # so a test matching that phrase passes whether or not this check
        # exists -- which is exactly how a guard rots. Two gates are right;
        # a test that cannot tell them apart is not.
        (
            {"VITESS_API_PUBLISHED": "true"},
            "let anyone on the network act as that user",
        ),
        (
            {"VITESS_BIND_HOST": "0.0.0.0"},
            "must be 127.0.0.1",
        ),
        (
            {"VITESS_API_PUBLISHED": "treu"},
            "must be one of 1/0",
        ),
        # A lookup bounded by zero seconds cannot succeed, and a negative retry
        # count is not a number of retries. Both are silent: the documentation
        # tools would answer RAG_UNAVAILABLE forever and look like a missing
        # index rather than a misconfigured one.
        (
            {"VITESS_RAG_QUERY_TIMEOUT_SECONDS": "0"},
            "must be greater than 0",
        ),
        (
            {"VITESS_RAG_MAX_RETRIES": "-1"},
            "must be 0 or greater",
        ),
    ],
)
def test_the_service_refuses_to_start_on_a_configuration_that_cannot_work(
    environment: dict[str, str], message: str, tmp_path: Path
) -> None:
    """Loudly at startup, not as a warning followed by a first conversation.

    The published-API case is not cosmetic: every request here is the same
    local principal, so a reachable API lets anyone on the network act as that
    user. Core refuses the pairing too; this refuses it earlier, with a message
    about this deployment.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import vitess_ai.server.service"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "DATABASE_URL": "postgresql://vitess:secret@postgres:5432/vitess",
            "BLABLADOR_API_KEY": "not-used",
            "VITESS_PROJECT_PATH": str(tmp_path / "projects"),
            **environment,
        },
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_core_is_configured_from_this_deployment_s_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The extension mechanism is that there is none.

    `Config` keeps its own class, its `os.getenv` and its `validate_required`,
    and hands core a frozen `CoreSettings`. No subclassing, no merge -- and
    core still reads nothing itself.

    Captured rather than installed: `configure()` refuses to replace settings
    that are already in place, which is what stops a second call leaving cached
    models paired with stale values -- and `conftest.py` has already installed a
    set for this process.
    """
    import vitess_ai.config as module

    captured: list[object] = []
    monkeypatch.setattr(module.juena_core, "configure", captured.append)
    configure_core()
    settings = captured[0]

    assert settings.ARTIFACT_ROOT == Config.ARTIFACT_ROOT
    # Core names this after what it times, not after where it runs: here the
    # backend is the MCP server and the thing timed is a VITESS pipeline.
    assert settings.EXECUTE_TIMEOUT_SECONDS == Config.EXECUTE_TIMEOUT_SECONDS
    assert settings.BIND_HOST == Config.BIND_HOST
    assert settings.API_PUBLISHED is False


# --------------------------------------------------------------------------
# Where a staged file lands
# --------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> UploadStore:
    return UploadStore(
        tmp_path / "projects",
        max_bytes=1024,
        allowed_extensions=(".dat", ".inf", ".h5"),
    )


def test_the_slots_come_from_the_catalog_and_from_nowhere_else() -> None:
    """`FALLBACK_MODULE_TYPES` listed six; three of them took no files.

    It existed because importing the catalog used to drag in LangChain, so the
    store kept a copy for when that failed. The import cannot fail now, and a
    store that cannot name its slots is a broken install.
    """
    assert upload_module_names() == tuple(spec.name for spec in upload_modules())
    assert upload_module_names() == ("readin", "instrument", "guide")


def test_the_whole_upload_manifest_comes_from_the_catalog() -> None:
    assert upload_module_manifest() == tuple(
        {
            "name": spec.name,
            "label": spec.accepts_upload.label,
            "help": spec.accepts_upload.help,
            "extensions": list(spec.accepts_upload.extensions),
            "max_files": spec.accepts_upload.max_files,
        }
        for spec in upload_modules()
        if spec.accepts_upload is not None
    )


def test_each_slot_enforces_its_catalog_file_count_and_extensions(store: UploadStore) -> None:
    store.stage(
        b"instrument\n",
        filename="instrument.inf",
        thread_id=THREAD,
        module="instrument",
    )

    with pytest.raises(UploadRefused, match="at most 1 staged file"):
        store.stage(
            b"second\n",
            filename="other.inf",
            thread_id=THREAD,
            module="instrument",
        )
    with pytest.raises(UploadRefused, match="instrument does not accept .h5"):
        store.stage(
            MAGIC_NUMBERS[".h5"] + b"data",
            filename="wrong-slot.h5",
            thread_id=uuid4(),
            module="instrument",
        )


def test_a_staged_file_lands_in_its_own_module_s_directory(store: UploadStore) -> None:
    staged = store.stage(b"trajectories\n", filename="beam.dat", thread_id=THREAD, module="readin")

    assert staged.path.parent == store.root / str(THREAD) / "uploads" / "readin"
    assert staged.path.read_bytes() == b"trajectories\n"
    assert staged.filename == "beam.dat"


def test_a_second_file_of_the_same_name_does_not_replace_the_first(
    store: UploadStore,
) -> None:
    """And it is not prefixed with a UUID either.

    The person who uploaded it has to recognise it in a parameter field and in
    the sidebar, and `a3f9...-beam.dat` is not a file anyone recognises.
    """
    first = store.stage(b"one\n", filename="beam.dat", thread_id=THREAD, module="readin")
    second = store.stage(b"two\n", filename="beam.dat", thread_id=THREAD, module="readin")

    assert [first.filename, second.filename] == ["beam.dat", "beam_1.dat"]
    assert first.path.read_bytes() == b"one\n"


def test_concurrent_uploads_of_the_same_name_cannot_replace_each_other(
    store: UploadStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both requests choose ``beam.dat`` before either is allowed to publish.

    This is the interleaving the former exists-then-write sequence lost: both
    responses claimed the same path and whichever write finished last replaced
    the other. The visible-name link is exclusive now, so the loser retries.
    """

    original = UploadStore._unused_name
    barrier = Barrier(2)
    lock = Lock()
    calls = 0

    def collide_once(directory: Path, name: str) -> str:
        nonlocal calls
        candidate = original(directory, name)
        with lock:
            calls += 1
            number = calls
        if number <= 2:
            barrier.wait(timeout=2)
        return candidate

    monkeypatch.setattr(UploadStore, "_unused_name", staticmethod(collide_once))
    contents = (b"first\n", b"second\n")

    def stage(content: bytes):
        return store.stage(
            content,
            filename="beam.dat",
            thread_id=THREAD,
            module="readin",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        staged = list(pool.map(stage, contents))

    assert {item.filename for item in staged} == {"beam.dat", "beam_1.dat"}
    assert {item.path.read_bytes() for item in staged} == set(contents)


def test_the_http_boundary_reads_only_one_byte_beyond_the_upload_limit() -> None:
    """A claimed 100 MB policy must not first allocate an unbounded request."""

    upload = UploadFile(file=BytesIO(b"x" * 64), filename="too-large.dat")

    content = asyncio.run(_read_upload_bytes(upload, 8))

    assert content == b"x" * 9
    assert upload.file.closed


@pytest.mark.parametrize(
    "filename", ["../../../etc/passwd.dat", "/etc/passwd.dat", "sub/dir/beam.dat"]
)
def test_a_file_name_cannot_walk_out_of_its_slot(
    filename: str, store: UploadStore
) -> None:
    staged = store.stage(b"x\n", filename=filename, thread_id=THREAD, module="readin")

    assert staged.path.parent == store.root / str(THREAD) / "uploads" / "readin"
    assert staged.filename == Path(filename).name


@pytest.mark.parametrize(
    ("content", "filename", "module", "message"),
    [
        (b"x\n", "beam.exe", "readin", "does not accept .exe"),
        (b"x" * 2048, "beam.dat", "readin", "over the"),
        (b"", "beam.dat", "readin", "is empty"),
        (b"not hdf5 at all", "beam.h5", "readin", "HDF5 signature"),
        (b"x\n", "beam.dat", "writeout", "does not accept an uploaded file"),
        (b"x\n", "beam.dat", "monitor3d", "does not accept an uploaded file"),
        (b"x\n", "", "readin", "not a usable file name"),
    ],
)
def test_an_upload_is_refused_with_a_reason_and_nothing_is_written(
    content: bytes,
    filename: str,
    module: str,
    message: str,
    store: UploadStore,
) -> None:
    """Every one of these writes no bytes; a partial write is worse than a refusal."""

    with pytest.raises(UploadRefused, match=message):
        store.stage(content, filename=filename, thread_id=THREAD, module=module)

    assert not list((store.root).rglob("*.dat"))
    assert not list((store.root).rglob("*.h5"))


def test_a_real_hdf5_file_is_accepted_where_a_named_one_is_not(
    store: UploadStore,
) -> None:
    """`.h5` and `.nxs` may never take the chat-attachment path.

    That path decodes with `raw.decode("utf-8-sig")`, so binary neutron data
    would either throw or be mangled into the transcript. This path never
    decodes -- it writes bytes for a binary to open -- which is exactly why it
    needs a signature check of its own rather than a shared text validator.
    """
    content = MAGIC_NUMBERS[".h5"] + b"\x00" * 32
    staged = store.stage(content, filename="sample.h5", thread_id=THREAD, module="readin")

    assert staged.path.read_bytes() == content


def test_listing_a_thread_returns_every_slot_in_catalog_order(
    store: UploadStore,
) -> None:
    store.stage(b"g\n", filename="guide.dat", thread_id=THREAD, module="guide")
    store.stage(b"b\n", filename="beam.dat", thread_id=THREAD, module="readin")
    store.stage(b"i\n", filename="rig.inf", thread_id=THREAD, module="instrument")

    assert [item.module for item in store.staged(THREAD)] == [
        "readin",
        "instrument",
        "guide",
    ]


def test_one_thread_cannot_see_another_s_staged_files(store: UploadStore) -> None:
    other = uuid4()
    store.stage(b"b\n", filename="beam.dat", thread_id=THREAD, module="readin")

    assert store.staged(other) == []


def test_a_wrong_slot_can_be_corrected(store: UploadStore) -> None:
    """Which is the answer to guessing wrong, and why guessing is not done.

    A trajectory file in the guide slot produces a simulation that runs,
    completes and is physically wrong.
    """
    store.stage(b"b\n", filename="beam.dat", thread_id=THREAD, module="guide")

    assert store.remove(THREAD, "guide", "beam.dat") is True
    assert store.remove(THREAD, "guide", "beam.dat") is False
    assert store.staged(THREAD) == []


# --------------------------------------------------------------------------
# The call sites, not only the functions they call
# --------------------------------------------------------------------------


def test_the_modules_route_serves_the_whole_manifest_not_just_the_names() -> None:
    """`upload_module_manifest()` being right is half of it; the route is the half
    the sidebar actually reads.

    The first port served bare slot names here and the UI kept its own copy of
    the labels, help text and limits -- which is how the catalog stopped being
    the authority without anything failing. Asserting the helper in isolation
    would not have noticed: this reads the route.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from juena_core.server.identity import Principal

    app = FastAPI()
    app.include_router(
        build_file_router(
            lambda: Principal(
                id=uuid4(), subject="s", issuer="i", email=None, display_name=None
            ),
            UploadStore(Path("/nonexistent"), max_bytes=16, allowed_extensions=(".dat",)),
        )
    )

    served = TestClient(app).get("/files/modules").json()["modules"]

    assert [slot["name"] for slot in served] == list(upload_module_names())
    for slot in served:
        assert set(slot) == {"name", "label", "help", "extensions", "max_files"}
        assert slot["label"] and slot["help"] and slot["extensions"]


def test_the_upload_route_bounds_the_body_by_the_store_s_own_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bounded reader nothing calls with the right limit is not a bound.

    `_read_upload_bytes` is tested directly, which proves it truncates -- not
    that the route hands it the store's ceiling rather than, say, a hard-coded
    number that drifts away from `VITESS_MAX_UPLOAD_BYTES`.
    """
    from vitess_ai.server import file_endpoints

    asked: list[int] = []

    async def record(upload: Any, max_bytes: int) -> bytes:
        asked.append(max_bytes)
        return b"beam\n"

    async def owned(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(file_endpoints, "_read_upload_bytes", record)
    # Ownership is asserted by its own tests; here it would only pull in a
    # database this one does not need.
    monkeypatch.setattr(file_endpoints, "get_owned_chat", owned)
    # `tmp_path`, not `/tmp`: the route writes through the real store, so a
    # shared directory would carry read-in's three-file limit between runs.
    store = UploadStore(tmp_path, max_bytes=4242, allowed_extensions=(".dat",))
    router = file_endpoints.build_file_router(lambda: None, store)
    route = next(
        item
        for item in router.routes
        if getattr(item, "name", "") == "stage_file"
    )

    asyncio.run(
        route.endpoint(
            thread_id=THREAD,
            module="readin",
            upload=SimpleNamespace(filename="beam.dat"),
            user=SimpleNamespace(id=uuid4()),
            session=None,
        )
    )

    assert asked == [store.max_bytes] == [4242]


def test_an_interrupted_upload_is_neither_listed_nor_counted(
    store: UploadStore,
) -> None:
    """The atomic publish leaves a hidden temporary if the process dies mid-write.

    It is a real file on disk, so anything that asks the directory "what is
    staged here?" sees it: the manifest would show a `.upload-…tmp` nobody
    uploaded, and `max_files` would count it, so a crashed upload would use up
    one of read-in's three slots permanently.
    """
    store.stage(b"beam\n", filename="beam.dat", thread_id=THREAD, module="readin")
    directory = store.directory(THREAD, "readin")
    (directory / ".upload-deadbeef.tmp").write_bytes(b"half a file")

    assert [item.filename for item in store.staged(THREAD)] == ["beam.dat"]

    # And it does not consume one of the slot's three places: two more must fit.
    store.stage(b"two\n", filename="two.dat", thread_id=THREAD, module="readin")
    store.stage(b"three\n", filename="three.dat", thread_id=THREAD, module="readin")

    assert len(store.staged(THREAD)) == 3
