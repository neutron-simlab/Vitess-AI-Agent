"""CP6: what the pages may and may not do, asserted without a browser.

Streamlit pages are hard to test and easy to get quietly wrong, so what is
pinned here is the small set of properties that would cost a real result if
they slipped -- an output filename reappearing as a second source of truth, a
trajectory file taking the text-decoding path, or the six upload slots coming
back. Rendering is not asserted; a screenshot test would pass on a page nobody
can use.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

import app.file_management as file_management
from app.sidebar import AGENTS
from app.session_state import adopt_thread_agent, start_new_thread
from app.starters import build_starter_prompts
from app.ui_components import logo_path
from vitess_ai.clients import VitessClient
from vitess_ai.modules.catalog import MODULES, upload_modules
from vitess_ai.server.uploads import upload_module_manifest
from vitess_ai.schema import (
    Monitor1DParameters,
    Monitor2DParameters,
    WriteoutParameters,
)

APP = Path(__file__).resolve().parents[1] / "app"
SOURCE = "\n".join(path.read_text(encoding="utf-8") for path in sorted(APP.glob("*.py")))


def test_the_juena_logo_is_packaged_for_the_page_and_header() -> None:
    assert logo_path() == APP / "assets" / "logo.png"


def test_the_sidebar_offers_three_slots_and_the_catalog_decides_which() -> None:
    """Six upload widgets became three, and not by editing a list here.

    `writeout`, `monitor1d` and `monitor2d` were declared uploads under a mode
    that uploaded nothing: each set an output filename the parameter schema
    already owns. The rows are gone (03/CP2) and the panel reads the catalog
    through the API, so it cannot grow them back locally.
    """
    assert [slot["name"] for slot in upload_module_manifest()] == [
        spec.name for spec in upload_modules()
    ]
    assert "SLOT_LABELS" not in (APP / "file_management.py").read_text(
        encoding="utf-8"
    )


def test_a_new_thread_is_created_before_its_first_sidebar_upload() -> None:
    """An unsent conversation has no row yet, but the upload route checks one."""

    class Client:
        agent = "vitess"

        def __init__(self) -> None:
            self.created: tuple[str, str, str] | None = None

        def get_chat(self, thread_id: str, *, include_messages: bool):
            assert include_messages is False
            return None

        def create_chat(self, thread_id: str, *, agent_id: str, title: str):
            self.created = (thread_id, agent_id, title)

    client = Client()

    file_management._ensure_chat(client, "new-thread")

    assert client.created == ("new-thread", "vitess", "New Chat")


def test_the_vitess_client_can_reach_all_four_file_routes() -> None:
    """Core exposes `_headers` as a property; calling it broke the whole sidebar."""

    seen: list[tuple[str, str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        assert request.headers["cookie"] == "juena_session=session-token"
        seen.append((request.method, request.url.path))
        if request.url.path == "/files/modules":
            return httpx.Response(200, json={"modules": list(upload_module_manifest())})
        if request.method == "GET":
            return httpx.Response(200, json={"files": []})
        if request.method == "POST":
            return httpx.Response(200, json={"filename": "beam.dat"})
        return httpx.Response(200, json={"removed": "beam.dat"})

    client = VitessClient(
        "http://vitess.test",
        agent="vitess",
        session_token="session-token",
    )
    client.close()
    transport_client = httpx.Client(transport=httpx.MockTransport(answer))
    client._client = transport_client
    try:
        assert client.upload_modules()[0]["name"] == "readin"
        assert client.list_staged("thread") == []
        assert client.stage_file("thread", "readin", "beam.dat", b"beam\n") == {
            "filename": "beam.dat"
        }
        client.remove_staged("thread", "readin", "beam.dat")
    finally:
        transport_client.close()

    assert seen == [
        ("GET", "/files/modules"),
        ("GET", "/files/thread"),
        ("POST", "/files/thread/readin"),
        ("DELETE", "/files/thread/readin/beam.dat"),
    ]


def test_the_ui_does_not_recreate_a_fallback_upload_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If `/files/modules` is down, labels must not become slot authority."""

    warnings: list[str] = []

    class StreamlitDouble:
        session_state: dict[str, object] = {}

        @staticmethod
        def subheader(_text: str) -> None:
            pass

        @staticmethod
        def warning(text: str) -> None:
            warnings.append(text)

    class Client:
        @staticmethod
        def list_staged(_thread_id: str):
            return []

        @staticmethod
        def upload_modules():
            raise file_management.httpx.ConnectError("offline")

    monkeypatch.setattr(file_management, "st", StreamlitDouble())

    file_management.render_file_manifest(Client(), "thread")

    assert warnings == ["Could not read the upload slots: offline"]


def test_switching_mode_starts_a_new_thread_instead_of_showing_the_old_transcript() -> None:
    state = {
        "thread_id": "guided-thread",
        "messages": ["guided answer"],
        "chat_initialized": True,
    }
    replacement = UUID("22222222-2222-4222-8222-222222222222")

    start_new_thread(state, make_id=lambda: replacement)

    assert state == {
        "thread_id": str(replacement),
        "messages": [],
        "chat_initialized": True,
    }


def test_reloading_a_thread_restores_the_agent_that_owns_it() -> None:
    state = {"selected_agent": "vitess"}

    changed = adopt_thread_agent(
        state,
        "advanced_mode",
        known_agents=set(AGENTS),
    )

    assert changed is True
    assert state["selected_agent"] == "advanced_mode"


@pytest.mark.parametrize(
    "filename", ["output.dat", "output.out", "monitor1D.dat", "monitor2D.dat"]
)
def test_no_output_filename_appears_anywhere_in_the_interface(filename: str) -> None:
    """The schema owns those names, and a second copy is the removed bug.

    The first generation's sidebar said `output.out` where
    `WriteoutParameters.sOutFileName` said `output.dat` -- two defaults for one
    value, in two files, with nothing to make them agree. The three modules that
    write files collect their filenames conversationally now, from the schema
    default the prompt teaches.
    """
    assert filename not in SOURCE


@pytest.mark.parametrize(
    ("model", "field", "default"),
    [
        (WriteoutParameters, "sOutFileName", "output.dat"),
        (Monitor1DParameters, "fMonitorFilename", "monitor1D.dat"),
        (Monitor2DParameters, "fMonitorFilename", "monitor2D.dat"),
    ],
)
def test_each_output_filename_still_has_exactly_one_owner(
    model: type, field: str, default: str
) -> None:
    assert model.model_fields[field].default == default
    assert default not in json.dumps([spec.model_dump() for spec in MODULES])


def test_the_composer_does_not_accept_files() -> None:
    """Two upload paths, and confusing them mangles binary neutron data.

    juena's composer decodes an attachment with `raw.decode("utf-8-sig")` and
    puts the text in graph state. A VITESS trajectory file can be `VT_BINARY`
    and large, and `.h5`/`.nxs` are HDF5 -- that path would either throw or
    write mangled bytes into the transcript. Input files go to `/files`, which
    never decodes: it writes bytes for a compiled binary to open.
    """
    chat_page = (APP / "chat_interface.py").read_text(encoding="utf-8")

    assert "accept_file" not in chat_page.split("# Deliberately no `accept_file`")[1]
    assert "Deliberately no `accept_file`" in chat_page


def test_the_ui_does_not_claim_the_text_question_card_uploads_binary_files() -> None:
    """`ask_user` pauses; the one module-labelled uploader remains the sidebar."""

    assert "upload from the chat" not in SOURCE
    assert "both of which post to `/files`" not in SOURCE
    assert "upload it here while" in SOURCE


def test_the_page_never_touches_the_project_volume_directly() -> None:
    """The UI is a separate process, and in production a separate container.

    A path works at all only because both containers mount the same volume at
    the same place. Going through the route is what keeps one definition of
    which slot a file belongs to, what may be uploaded and how big it may be.
    """
    assert "/data/projects" not in SOURCE
    assert "VITESS_PROJECT_PATH" not in SOURCE


def test_both_agents_are_reachable_and_named_for_what_they_are() -> None:
    """They differ in interaction model, not expertise, and the picker says so."""

    assert set(AGENTS) == {"vitess", "advanced_mode"}
    for _label, description in AGENTS.values():
        assert description


@pytest.mark.parametrize("agent", ["vitess", "advanced_mode"])
def test_each_agent_has_starters_of_its_own(agent: str) -> None:
    """A sweep asked of the guided agent is answered one simulation at a time.

    Which is not wrong so much as forty minutes of the wrong shape, so the
    chips shown are the ones that belong to the mode that is selected.
    """
    starters = build_starter_prompts(agent)

    assert starters
    assert all(starter.agent == agent for starter in starters)


def test_the_sidebar_is_a_fraction_of_what_it_replaced() -> None:
    """596 lines, most of it six upload widgets and a mode that uploaded nothing.

    Not a style preference: if it has not shrunk, something was ported that
    03/CP2 said to delete -- and the most likely candidate is
    `_render_path_upload_mode`, whose whole job was to collect an output
    filename the schema already owns.
    """
    sidebar = (APP / "sidebar.py").read_text(encoding="utf-8").splitlines()
    manifest = (APP / "file_management.py").read_text(encoding="utf-8").splitlines()

    assert len(sidebar) < 150, "the sidebar grew; check what came back with it"
    assert len(sidebar) + len(manifest) < 300
    assert "path_only" not in SOURCE


def test_an_unknown_agent_is_refused_rather_than_adopted() -> None:
    """A thread whose `agent_id` names no registered graph is a broken row.

    Adopting it would set `selected_agent` to something the client cannot be
    built for, and the failure would surface one rerun later as a stream to an
    agent id that 404s -- a long way from the row that caused it.
    """
    with pytest.raises(ValueError, match="unknown agent"):
        adopt_thread_agent({}, "simulator_legacy", known_agents=set(AGENTS))


def test_switching_mode_leaves_the_other_agent_s_thread_behind() -> None:
    """The pure function is tested; this is the wiring that calls it.

    Without `on_change`, changing the radio keeps `thread_id`, so the next
    message is sent to the new agent on a thread the old one owns -- and core
    refuses a thread whose `agent_id` does not match, so the conversation
    simply stops working with no explanation in the page.
    """
    source = (APP / "sidebar.py").read_text(encoding="utf-8")

    assert "on_change=start_new_thread" in source
    assert "args=(st.session_state,)" in source


def test_reloading_a_thread_adopts_the_agent_that_owns_it_at_the_call_site() -> None:
    """Likewise: `adopt_thread_agent` is only useful where it is called.

    The client is built from `selected_agent` before the thread is loaded, so a
    thread belonging to the other mode has to re-enter the script once the
    agent is known. Losing the call means the page streams a restored
    `advanced_mode` conversation to the guided graph.
    """
    source = (APP / "streamlit_app.py").read_text(encoding="utf-8")

    # The `if` matters: asserting only that the name appears would pass on a
    # call whose result is thrown away, which is the same as not calling it.
    assert "if adopt_thread_agent(" in source
    assert "chat.agent_id" in source
    assert "st.rerun()" in source.split("adopt_thread_agent(")[1]
