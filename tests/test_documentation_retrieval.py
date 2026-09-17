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
from types import SimpleNamespace

import pytest
from langchain.tools import tool

from vitess_ai.config import Config
from vitess_ai.retrieval import (
    RAG_TOOL_NAMES,
    RagUnavailable,
    SPECIALIST_RAG_TOOLS,
    get_rag_tools,
    orchestrator_documentation,
    rag_enabled,
    specialist_rag_tools,
)
from vitess_ai.retrieval.prompts import (
    MODULE_RAG_CONTEXT_NOTE,
    RAG_ANSWER_PROTOCOL,
    SUPERVISOR_RAG_POLICY,
    SWEEP_RAG_POLICY,
)
from vitess_ai.retrieval.runtime import (
    build_embedding_client,
    build_embedding_function,
)
from vitess_ai.retrieval.tools import (
    _guard_query_tool,
    _unavailable_tools,
    _validated_rag_tools,
)
import vitess_ai.retrieval.bootstrap as bootstrap

ALL_FOUR = (
    "vitess_search",
    "vitess_option_lookup",
    "vitess_module_lookup",
    "vitess_debug_retrieval",
)

assert ALL_FOUR == RAG_TOOL_NAMES


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
    assert "Do not invent what the manual says" in answer
    assert "any parameter schema already in your prompt" in answer


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


@pytest.mark.parametrize("policy", [SUPERVISOR_RAG_POLICY, SWEEP_RAG_POLICY])
def test_each_orchestrator_policy_names_all_four(policy: str) -> None:
    for name in ALL_FOUR:
        assert f"`{name}`" in policy


def test_guided_and_unattended_ambiguity_policies_do_not_conflict() -> None:
    """A sweep cannot follow a policy that tells it to call absent `ask_user`."""

    assert "use `ask_user`" in SUPERVISOR_RAG_POLICY
    assert "You have no `ask_user` tool" in SWEEP_RAG_POLICY
    assert "record the unresolved ambiguity under `limitations`" in SWEEP_RAG_POLICY


@pytest.mark.parametrize(
    "prompt",
    [MODULE_RAG_CONTEXT_NOTE, SUPERVISOR_RAG_POLICY, SWEEP_RAG_POLICY],
)
def test_every_rag_prompt_teaches_the_real_return_protocol(prompt: str) -> None:
    """The model must not mistake a refusal token for retrieved documentation."""

    for marker in ("NO_RESULTS", "AMBIGUOUS_QUERY", "RAG_UNAVAILABLE", "[Chunk n]"):
        assert marker in prompt


def test_prompts_name_documented_modules_this_application_cannot_run() -> None:
    """The manual is broader than the executable catalog; silence implies support."""

    for module in (
        "filter",
        "filter2D",
        "guide_ideal",
        "bender",
        "mon1",
        "mon2",
        "monpol",
        "mon_brilliance",
    ):
        assert f"**{module}**" in RAG_ANSWER_PROTOCOL
        assert f"`{module}`" not in RAG_ANSWER_PROTOCOL


def test_orchestrator_tools_and_policy_are_selected_as_one_unit() -> None:
    guided_tools, guided_policy = orchestrator_documentation(unattended=False)
    sweep_tools, sweep_policy = orchestrator_documentation(unattended=True)

    assert tuple(item.name for item in guided_tools) == ALL_FOUR
    assert tuple(item.name for item in sweep_tools) == ALL_FOUR
    assert guided_policy == SUPERVISOR_RAG_POLICY
    assert sweep_policy == SWEEP_RAG_POLICY


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


def test_an_embedded_package_tool_drift_fails_closed() -> None:
    """A fixed policy may not name four tools while the package supplies three."""
    with pytest.raises(RagUnavailable, match="unexpected tool set"):
        _validated_rag_tools(_unavailable_tools("test")[:-1])


def test_a_query_time_failure_degrades_for_that_call_and_keeps_the_real_tool(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An expired key is discovered after graph construction, on `invoke`.

    The second call proves degradation is per call. Replacing the cached tool
    set with stubs after the first 429 would make a transient outage permanent
    until the application container restarted.
    """
    calls = 0

    @tool("vitess_search", description="Search the VITESS manual.")
    def flaky(query: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("embedding endpoint timed out")
        return f"[Chunk 1] {query}"

    guarded = _guard_query_tool(flaky)

    first = guarded.invoke({"query": "guide width"})
    second = guarded.invoke({"query": "guide width"})

    assert first.startswith("RAG_UNAVAILABLE:")
    # Named, not just relayed. An invalid key arrives here as the OpenAI SDK's
    # `AttributeError: 'str' object has no attribute 'data'` -- measured against
    # the real endpoint -- and without the type that reads as a bug in this
    # application rather than a credential to check.
    assert "TimeoutError: embedding endpoint timed out" in first
    assert second == "[Chunk 1] guide width"
    assert guarded.name == flaky.name
    assert guarded.description == flaky.description
    assert "embedding endpoint timed out" in caplog.text


def test_query_guard_does_not_swallow_process_cancellation() -> None:
    """Catching `BaseException` turns cancellation into a request that never ends."""

    class StopRequest(BaseException):
        pass

    @tool("vitess_search", description="Search the VITESS manual.")
    def cancelled(query: str) -> str:
        _ = query
        raise StopRequest

    guarded = _guard_query_tool(cancelled)
    with pytest.raises(StopRequest):
        guarded.invoke({"query": "stop"})


def test_embedding_query_client_has_an_explicit_timeout_and_retry_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The OpenAI SDK default timeout is ten minutes, too long for an agent turn."""
    import openai

    captured: dict[str, object] = {}

    def fake_client(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(openai, "OpenAI", fake_client)
    monkeypatch.setattr(Config, "RAG_QUERY_TIMEOUT_SECONDS", 7.5)
    monkeypatch.setattr(Config, "RAG_MAX_RETRIES", 2)

    assert build_embedding_client() is not None
    assert captured["timeout"] == 7.5
    assert captured["max_retries"] == 2


def test_the_explicit_indexing_command_fails_when_indexing_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Graceful serving without RAG must not turn a failed build command green."""

    def fail() -> None:
        raise RuntimeError("embedding endpoint refused the request")

    monkeypatch.setattr(bootstrap, "bootstrap_rag_index", fail)

    assert bootstrap.main() == 1
    assert "embedding endpoint refused" in capsys.readouterr().out


def test_indexing_restarts_the_app_so_cached_unavailable_tools_are_replaced() -> None:
    launcher = (Path(__file__).resolve().parents[1] / "vitess").read_text(
        encoding="utf-8"
    )
    body = launcher.split("cmd_index_docs()", maxsplit=1)[1].split("\n}", maxsplit=1)[0]

    assert "python -m vitess_ai.retrieval.bootstrap" in body
    assert 'restart vitess-app' in body


def test_package_tool_drift_reaches_the_built_tools_not_only_the_checker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_validated_rag_tools` is a function; this is the line that calls it.

    Deleting the call from `get_rag_tools` leaves the checker and its own test
    untouched and green, while the deployment binds whatever the embedded
    package happened to expose -- and both supervisor prompts go on naming four
    tools regardless. The guarantee is the call, not the function.
    """
    import vitess_rag.tools as package

    monkeypatch.setattr("vitess_ai.retrieval.tools.rag_enabled", lambda: True)
    monkeypatch.setattr(
        "vitess_ai.retrieval.tools.get_rag_collection",
        lambda recreate=False: SimpleNamespace(count=lambda: 379),
    )
    monkeypatch.setattr(
        package,
        "create_vitess_tools",
        lambda collection: _unavailable_tools("drift")[:3],
    )

    get_rag_tools.cache_clear()
    try:
        tools = get_rag_tools()
    finally:
        get_rag_tools.cache_clear()

    assert tuple(item.name for item in tools) == RAG_TOOL_NAMES
    assert "unexpected tool set" in tools[0].invoke({"query": "x"})


def test_replacing_the_embedding_client_closes_the_one_it_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The package's constructor opens a client this deployment does not use.

    `build_embedding_function` runs on every graph construction, so dropping
    the replaced client without closing it leaks one idle HTTP transport per
    agent built -- invisible until a long-lived container runs out of sockets.
    """
    closed: list[str] = []

    class Recorder:
        def close(self) -> None:
            closed.append("closed")

    class FakeEmbeddingFunction:
        def __init__(self, **kwargs: object) -> None:
            self.client = Recorder()

    import vitess_rag.embeddings as embeddings

    monkeypatch.setattr(embeddings, "BlabladorEmbeddingFunction", FakeEmbeddingFunction)
    monkeypatch.setattr(
        "vitess_ai.retrieval.runtime.build_embedding_client", lambda: "bounded"
    )

    function = build_embedding_function()

    assert function.client == "bounded"
    assert closed == ["closed"], "the replaced client was never closed"
