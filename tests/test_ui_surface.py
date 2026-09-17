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

import pytest

from app.sidebar import AGENTS
from app.starters import build_starter_prompts
from vitess_ai.modules.catalog import MODULES, upload_modules
from vitess_ai.schema import (
    Monitor1DParameters,
    Monitor2DParameters,
    WriteoutParameters,
)

APP = Path(__file__).resolve().parents[1] / "app"
SOURCE = "\n".join(path.read_text(encoding="utf-8") for path in sorted(APP.glob("*.py")))


def test_the_sidebar_offers_three_slots_and_the_catalog_decides_which() -> None:
    """Six upload widgets became three, and not by editing a list here.

    `writeout`, `monitor1d` and `monitor2d` were declared uploads under a mode
    that uploaded nothing: each set an output filename the parameter schema
    already owns. The rows are gone (03/CP2) and the panel reads the catalog
    through the API, so it cannot grow them back locally.
    """
    from app.file_management import SLOT_LABELS

    assert set(SLOT_LABELS) == {spec.name for spec in upload_modules()}
    assert set(SLOT_LABELS) == {"readin", "instrument", "guide"}


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
