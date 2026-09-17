"""CP6: the VITESS manual is searchable, and says so when it is not.

Retrieval is the one capability here that can be *absent* in a working
deployment: the index is built by a separate command, against an embedding
endpoint, and a checkout that has never run it is a checkout that still has to
answer. So most of this file is about the absent case, which is the one that
happens.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from vitess_ai.config import Config
from vitess_ai.retrieval import (
    SPECIALIST_RAG_TOOLS,
    get_rag_tools,
    rag_enabled,
    specialist_rag_tools,
)
from vitess_ai.retrieval.prompts import MODULE_RAG_CONTEXT_NOTE, ORCHESTRATOR_RAG_POLICY
from vitess_ai.retrieval.tools import _unavailable_tools

ALL_FOUR = (
    "vitess_search",
    "vitess_option_lookup",
    "vitess_module_lookup",
    "vitess_debug_retrieval",
)


def test_retrieval_is_off_for_the_suite_and_that_is_deliberate() -> None:
    """Pins the fixture rather than leaving it implicit.

    Every assertion below is about the unavailable path, and it would quietly
    stop being about anything if a developer's `BLABLADOR_API_KEY` switched the
    real one on.
    """
    assert rag_enabled() is False
    assert Config.RAG_ENABLED is False


def test_an_unavailable_index_still_answers_with_four_tools() -> None:
    """Returning nothing is worse than returning a refusal.

    A model whose tool list changed between conversations cannot say "I could
    not look that up" -- it simply stops mentioning the documentation, and the
    user cannot tell an unanswerable question from an unasked one. Same choice
    03/CP3 made for the MCP gateway: keep the tool bound, report the outage.
    """
    tools = get_rag_tools()

    assert tuple(tool.name for tool in tools) == ALL_FOUR


@pytest.mark.parametrize("name", ALL_FOUR)
def test_each_unavailable_tool_says_so_and_says_what_to_do(name: str) -> None:
    tool = next(item for item in get_rag_tools() if item.name == name)

    answer = tool.invoke({"query": "what does -z mean"})

    assert answer.startswith("RAG_UNAVAILABLE:")
    assert "Answer from the parameter schema" in answer


def test_a_module_specialist_gets_three_of_the_four() -> None:
    """`vitess_debug_retrieval` inspects retrieval when retrieval looks wrong.

    That is the orchestrator's problem. 03/CP4 narrowed these specialists from
    eleven tools to four because a specialist reaches for what it is given, and
    three documentation tools is already the most that can be justified for one
    whose job is a conversation and a single validation call.
    """
    names = tuple(tool.name for tool in specialist_rag_tools())

    assert names == SPECIALIST_RAG_TOOLS
    assert "vitess_debug_retrieval" not in names


def test_the_specialist_note_names_exactly_those_three() -> None:
    """The prompt half of the same invariant CP4 enforced for the other tools."""

    for name in SPECIALIST_RAG_TOOLS:
        assert f"`{name}`" in MODULE_RAG_CONTEXT_NOTE
    assert "vitess_debug_retrieval" not in MODULE_RAG_CONTEXT_NOTE


def test_the_orchestrator_policy_names_all_four() -> None:
    for name in ALL_FOUR:
        assert f"`{name}`" in ORCHESTRATOR_RAG_POLICY


def test_the_schema_stays_authoritative_where_the_documentation_disagrees() -> None:
    """The one sentence the note exists for.

    A specialist that resolved a conflict the other way would validate against
    prose -- which is the defect both CP4 reviews were about, arriving by a new
    route. The VITESS manual describes every version of every module; the schema
    describes what this validator accepts.
    """
    # Matched on single lines: the note is wrapped markdown, so a phrase that
    # straddles a line break is not a substring of it.
    assert "authoritative" in MODULE_RAG_CONTEXT_NOTE
    assert "the schema is what runs" in MODULE_RAG_CONTEXT_NOTE
    assert "Do not use them to decide what your" in MODULE_RAG_CONTEXT_NOTE


def test_importing_retrieval_does_not_import_chroma() -> None:
    """Chroma brings ONNX and a tokenizer; a deployment without an index pays nothing.

    Run in a subprocess because this session has already imported plenty --
    asking `sys.modules` in-process would prove nothing. Same reason, and the
    same shape, as the catalog's import test (03/CP2).
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import vitess_ai.retrieval, sys;"
            " print(any(name.startswith(('chromadb', 'onnxruntime')) for name in sys.modules))",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.stdout.strip().endswith("False")


def test_core_never_learns_about_this() -> None:
    """The same rule that keeps core away from juena-rag.

    juena-chatbot searches its index over HTTP; this one is a directory on disk.
    Neither belongs in a library that knows what a specialist report is, and
    "a thing that can search" is app-supplied on both sides.
    """
    source_root = Path(__file__).resolve().parents[1].parent / "juena-core/src/juena_core"
    if not source_root.is_dir():  # pragma: no cover - a wheel install, not a checkout
        pytest.skip("juena-core is not checked out beside this repository")

    offenders = [
        str(path)
        for path in source_root.rglob("*.py")
        if "vitess_rag" in path.read_text(encoding="utf-8")
        or "chromadb" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_the_unavailable_tools_carry_the_reason_they_were_built_with() -> None:
    """A message a user can act on, not a generic failure.

    "The documentation index is empty" and "It is switched off in this
    deployment" are different problems with different fixes, and the model has
    to be able to relay which one it hit.
    """
    tools = _unavailable_tools("The documentation index is empty.")

    assert "The documentation index is empty." in tools[0].invoke({"query": "x"})
