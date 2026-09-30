"""The canvas is a checked execution contract, including revision and correction."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from doubles import (
    THREAD_ID,
    configured_modules,
    named_tool,
    raw_tools,
    runtime,
    simulation_payload,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from juena_core.artifacts import ArtifactStore, set_artifact_store_for_tests
from juena_core.server.api.endpoints import ThreadActivity
from juena_core.server.chat.repository import ChatNotFoundError
from juena_core.server.database.connection import get_db_session

from vitess_ai.agents.pipeline_middleware import PipelineCorrectionMiddleware
from vitess_ai.agents.specialists.eval_elast.tools import build_tools as eval_tools
from vitess_ai.agents.specialists.sample_elasticisotr.tools import (
    build_tools as sample_tools,
)
from vitess_ai.agents.specialists.screen.tools import build_tools as screen_tools
from vitess_ai.clients import VitessClient
from vitess_ai.pipeline import (
    BASE_MODULES,
    BUILDER_ORDER,
    PRESETS,
    PipelineConflict,
    PipelineInvalid,
    PipelineStore,
    builder_manifest,
    tof_dependency_issues,
)
from vitess_ai.run import VitessGateway
from vitess_ai.server import pipeline_endpoints
from vitess_ai.server.uploads import UploadStore
from vitess_ai.tools import build_plan_tool, build_vitess_tools
from vitess_ai.workspace_lock import ThreadWorkspaceDeleted

COMBINATIONS = [
    (
        preset,
        [
            name
            for name in BUILDER_ORDER
            if name in definition["required"] or name in extra
        ],
    )
    for preset, definition in PRESETS.items()
    for optional in [sorted(set(BUILDER_ORDER) - set(definition["required"]))]
    for size in range(len(optional) + 1)
    for extra in combinations(optional, size)
]


@pytest.fixture
def checkpointer(monkeypatch):
    saver = SimpleNamespace(aget=AsyncMock(return_value=None))
    monkeypatch.setattr(pipeline_endpoints, "get_checkpointer", lambda: saver)
    return saver


@pytest.fixture
def api(tmp_path, monkeypatch, checkpointer):
    async def owned(session, user_id, thread_id, *, agent_id):
        assert agent_id == "vitess"
        if thread_id != THREAD_ID:
            raise ChatNotFoundError("Chat not found")

    async def db():
        yield None

    monkeypatch.setattr(pipeline_endpoints, "get_owned_chat", owned)
    store = PipelineStore(tmp_path)
    activity = ThreadActivity()
    app = FastAPI()
    app.dependency_overrides[get_db_session] = db
    app.include_router(
        pipeline_endpoints.build_pipeline_router(
            lambda: SimpleNamespace(id=uuid4()),
            store,
            thread_activity=activity,
        )
    )
    with TestClient(app) as client:
        yield client, store, activity


@pytest.mark.parametrize("preset,modules", COMBINATIONS)
def test_all_supported_combinations_confirm_through_api(api, preset, modules):
    client, store, _ = api
    response = client.post(
        f"/pipelines/{THREAD_ID}/confirm", json={"modules": modules, "preset": preset}
    )
    assert response.status_code == 200, response.text
    assert response.json()["pipeline"]["modules"] == modules
    assert response.json()["pipeline"]["preset"] == preset
    assert store.get(THREAD_ID).revision == 1
    assert (
        client.get(f"/pipelines/{THREAD_ID}").json()["pipeline"]
        == response.json()["pipeline"]
    )
    assert client.get("/pipelines/modules").json() == builder_manifest()


@pytest.mark.parametrize(
    "missing", ["readin", "guide", "sample_elasticisotr", "screen"]
)
def test_sample_preset_requires_its_transport_sample_and_detector(api, missing):
    client, store, _ = api
    modules = [
        name for name in PRESETS["isotropic_sample_test"]["defaults"] if name != missing
    ]
    response = client.post(
        f"/pipelines/{THREAD_ID}/confirm",
        json={
            "preset": "isotropic_sample_test",
            "modules": modules,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["issues"][0]["modules"] == [missing]
    assert store.get(THREAD_ID) is None


def test_unknown_preset_and_changing_a_locked_preset_are_rejected(api):
    client, store, _ = api
    url = f"/pipelines/{THREAD_ID}/confirm"
    assert (
        client.post(
            url, json={"preset": "unknown", "modules": list(BASE_MODULES)}
        ).status_code
        == 422
    )
    assert store.get(THREAD_ID) is None
    modules = list(BUILDER_ORDER)
    assert (
        client.post(url, json={"preset": "guide_test", "modules": modules}).status_code
        == 200
    )
    response = client.post(
        url, json={"preset": "isotropic_sample_test", "modules": modules, "revision": 1}
    )
    assert response.status_code == 409
    assert store.get(THREAD_ID).preset == "guide_test"


def test_existing_saved_pipeline_restores_as_guide_test(tmp_path):
    directory = tmp_path / THREAD_ID
    directory.mkdir()
    (directory / "pipeline.json").write_text(
        '{"modules":["readin","guide","writeout","monitor1d","monitor2d"],"revision":1}'
    )
    record = PipelineStore(tmp_path).get(THREAD_ID)
    assert record.preset == "guide_test"
    assert record.modules == list(BASE_MODULES)


@pytest.mark.parametrize(
    "modules,code",
    [
        (list(BASE_MODULES)[1:], "required_module"),
        ([*BASE_MODULES, "guide"], "duplicate_module"),
        ([*BASE_MODULES, "source"], "unknown_module"),
        (["guide", "readin", *BASE_MODULES[2:]], "module_order"),
        ([*BASE_MODULES, "eval_elast", "screen"], "module_order"),
        (["readin", "sample_elasticisotr", *BASE_MODULES[1:]], "module_order"),
    ],
)
def test_rejection_keeps_no_accepted_plan(api, modules, code):
    client, store, _ = api
    response = client.post(f"/pipelines/{THREAD_ID}/confirm", json={"modules": modules})
    assert response.status_code == 422
    assert code in {issue["code"] for issue in response.json()["detail"]["issues"]}
    assert store.get(THREAD_ID) is None


def test_ownership_and_deletion_are_enforced(api):
    client, store, activity = api
    foreign = str(uuid4())
    assert client.get(f"/pipelines/{foreign}").status_code == 404
    assert (
        client.post(
            f"/pipelines/{foreign}/confirm", json={"modules": list(BASE_MODULES)}
        ).status_code
        == 404
    )
    assert activity.reserve_delete(THREAD_ID)
    assert (
        client.post(
            f"/pipelines/{THREAD_ID}/confirm", json={"modules": list(BASE_MODULES)}
        ).status_code
        == 409
    )
    assert store.get(THREAD_ID) is None


@pytest.mark.parametrize(
    "planned_revision,planned_modules,started",
    [
        (None, [], False),
        (1, [*BASE_MODULES, "eval_elast"], False),
        (2, list(BASE_MODULES), False),
        (2, [*BASE_MODULES, "screen", "eval_elast"], True),
    ],
)
def test_handoff_status_uses_checkpointed_revision_and_sequence(
    api, checkpointer, planned_revision, planned_modules, started
):
    client, store, _ = api
    store.confirm(THREAD_ID, [*BASE_MODULES, "eval_elast"], None)
    with pytest.raises(PipelineInvalid):
        store.check_module(THREAD_ID, "eval_elast", {"bTOF": True})
    corrected = [*BASE_MODULES, "screen", "eval_elast"]
    # The server accepted a revision, but its HTTP response never reached the UI.
    store.confirm(THREAD_ID, corrected, 1)
    checkpointer.aget.return_value = {
        "channel_values": {
            "messages": ["Existing conversation and old configuration"],
            "pipeline_revision": planned_revision,
            "planned_execution_order": planned_modules,
        }
    }

    restored = client.get(f"/pipelines/{THREAD_ID}").json()["pipeline"]
    assert restored["revision"] == 2
    assert restored["configuration_started"] is started
    checkpointer.aget.assert_awaited_once_with(
        {"configurable": {"thread_id": THREAD_ID}}
    )
    retried = client.post(
        f"/pipelines/{THREAD_ID}/confirm", json={"modules": corrected, "revision": 1}
    ).json()
    assert retried["pipeline"] == restored
    assert retried["message"] == store.get(THREAD_ID).kickoff


def test_foreign_pipeline_never_reads_checkpoint(api, checkpointer):
    client, _, _ = api
    assert client.get(f"/pipelines/{uuid4()}").status_code == 404
    checkpointer.aget.assert_not_awaited()


def test_real_planner_checkpoint_acknowledges_the_confirmed_revision(
    api, tmp_path, monkeypatch, configured
):
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from vitess_ai.state import VitessBridgeState

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    client, store, _ = api
    modules = [*BASE_MODULES, "capture_flux"]
    store.confirm(THREAD_ID, modules, None)
    saver = InMemorySaver()
    monkeypatch.setattr(pipeline_endpoints, "get_checkpointer", lambda: saver)
    assert not client.get(f"/pipelines/{THREAD_ID}").json()["pipeline"][
        "configuration_started"
    ]
    graph = create_agent(
        Model(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "plan",
                            "name": "plan_simulation",
                            "args": {"include_optional": ["capture_flux"]},
                        }
                    ],
                ),
                AIMessage(content="Ready to configure."),
            ]
        ),
        tools=[build_plan_tool(tmp_path)],
        state_schema=VitessBridgeState,
        checkpointer=saver,
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="Configure my confirmed pipeline")]},
        {"configurable": {"thread_id": THREAD_ID}, "run_id": uuid4()},
        context=runtime().context,
    )
    assert result["messages"][-2].status == "success", result["messages"][-2].content
    saved = graph.get_state({"configurable": {"thread_id": THREAD_ID}}).values
    assert saved["pipeline_revision"] == 1
    assert saved["planned_execution_order"] == modules
    assert client.get(f"/pipelines/{THREAD_ID}").json()["pipeline"][
        "configuration_started"
    ]


def test_repeat_confirm_is_idempotent_and_locked(api):
    client, store, _ = api
    url = f"/pipelines/{THREAD_ID}/confirm"
    first = client.post(url, json={"modules": list(BASE_MODULES)}).json()
    assert client.post(url, json={"modules": list(BASE_MODULES)}).json() == first
    assert (
        client.post(url, json={"modules": [*BASE_MODULES, "capture_flux"]}).status_code
        == 409
    )
    assert store.get(THREAD_ID).modules == list(BASE_MODULES)


def test_concurrent_confirmations_cannot_overwrite(tmp_path):
    store = PipelineStore(tmp_path)

    def confirm(modules):
        try:
            return store.confirm(THREAD_ID, modules, None)
        except PipelineConflict:
            return None

    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(confirm, [list(BASE_MODULES), [*BASE_MODULES, "screen"]])
        )
    assert sum(record is not None for record in results) == 1
    assert PipelineStore(tmp_path).get(THREAD_ID) == next(
        record for record in results if record
    )


def test_correction_revision_stale_configuration_and_deletion(tmp_path):
    store = PipelineStore(tmp_path)
    initial = [*BASE_MODULES, "eval_elast"]
    record = store.confirm(THREAD_ID, initial, None)
    issues = tof_dependency_issues(initial, tof=True)
    store.invalidate(THREAD_ID, record.revision, issues)
    with pytest.raises(PipelineInvalid):
        store.require_current(THREAD_ID, initial, 1)
    corrected = [*BASE_MODULES, "screen", "eval_elast"]
    with pytest.raises(PipelineConflict):
        store.confirm(THREAD_ID, corrected, None)
    assert store.confirm(THREAD_ID, corrected, 1).revision == 2
    with pytest.raises(PipelineConflict):
        store.require_current(THREAD_ID, corrected, 1)
    # A delayed error from revision 1 cannot invalidate the new revision.
    store.invalidate(THREAD_ID, 1, issues)
    assert store.require_current(THREAD_ID, corrected, 2).status == "confirmed"
    UploadStore(tmp_path, max_bytes=100, allowed_extensions=(".dat",)).delete_thread(
        THREAD_ID
    )
    assert store.get(THREAD_ID) is None
    with pytest.raises(ThreadWorkspaceDeleted):
        store.confirm(THREAD_ID, list(BASE_MODULES), None)


def test_store_rejects_workspace_symlinks(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / THREAD_ID).symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        PipelineStore(tmp_path).confirm(THREAD_ID, list(BASE_MODULES), None)


def _configured_plan(tmp_path, modules, results):
    state = build_plan_tool(tmp_path).func(runtime=runtime()).update
    state["module_results"] = results
    state["simulation_order_events"] += [
        {"kind": "configured", "module": name} for name in modules
    ]
    return state


@pytest.mark.parametrize("preset", ["guide_test", "isotropic_sample_test"])
def test_agent_runs_exact_canvas_sequence_without_capture_flux(
    tmp_path, configured, preset
):
    store = PipelineStore(tmp_path)
    results = configured_modules(tmp_path)
    modules = list(PRESETS[preset]["defaults"])
    store.confirm(THREAD_ID, modules, None, preset=preset)
    if preset == "isotropic_sample_test":
        for name, factory in [
            ("sample_elasticisotr", sample_tools),
            ("screen", screen_tools),
        ]:
            validator = named_tool(
                factory(project_root=tmp_path), f"validate_{name}_parameters"
            )
            results.update(
                validator.func(runtime=runtime(), parameters={}).update[
                    "module_results"
                ]
            )
    state = _configured_plan(tmp_path, modules, results)
    assert state["pipeline_revision"] == 1
    calls = []

    def run(call):
        calls.append(call)
        return simulation_payload(
            modules=call["args"]["execution_order"],
            simulation_run_id=call["args"]["simulation_run_id"],
        )

    artifacts = ArtifactStore(tmp_path / "artifacts", tmp_path / "audit.jsonl")
    set_artifact_store_for_tests(artifacts)
    try:
        tool = named_tool(
            build_vitess_tools(
                VitessGateway(raw_tools(run_simulation=run)), project_root=tmp_path
            ),
            "run_simulation",
        )
        asyncio.run(tool.coroutine(runtime=runtime(state=state)))
        assert calls[0]["args"]["execution_order"] == modules
        assert set(calls[0]["args"]["module_results"]) == set(modules)
        assert "capture_flux" not in calls[0]["args"]["module_results"]
        calls.clear()
        state["pipeline_revision"] = 99
        result = asyncio.run(tool.coroutine(runtime=runtime(state=state)))
        assert not calls
        assert "older pipeline" in result.update["messages"][0].content
        state["pipeline_revision"] = 1
        state["simulation_order_events"] = (
            build_plan_tool(tmp_path)
            .func(runtime=runtime())
            .update["simulation_order_events"]
        )
        result = asyncio.run(tool.coroutine(runtime=runtime(state=state)))
        assert not calls
        assert "not configured in order" in result.update["messages"][0].content
    finally:
        set_artifact_store_for_tests(None)


def test_late_dependency_reopens_canvas_and_ends_specialist(tmp_path, configured):
    store = PipelineStore(tmp_path)
    modules = [*BASE_MODULES, "eval_elast"]
    store.confirm(THREAD_ID, modules, None)
    tool = named_tool(
        eval_tools(project_root=tmp_path), "validate_eval_elast_parameters"
    )
    result = tool.func(
        runtime=runtime(),
        parameters={"bTOF": True, "TotLength": 1100, "DetDist": 100, "LmbdRef": 0},
    )
    assert result.goto == "__end__"
    assert "module_results" not in result.update
    assert store.get(THREAD_ID).status == "needs_correction"
    guard = PipelineCorrectionMiddleware(tmp_path)
    assert guard.before_model({}, runtime())["jump_to"] == "end"
    refused = build_plan_tool(tmp_path).func(runtime=runtime())
    assert "planned_execution_order" not in refused.update
    store.confirm(THREAD_ID, [*BASE_MODULES, "screen", "eval_elast"], 1)
    assert guard.before_model({}, runtime()) is None
    fresh = build_plan_tool(tmp_path).func(runtime=runtime()).update
    assert fresh["pipeline_revision"] == 2
    assert len(fresh["simulation_order_events"]) == 1


def test_api_exposes_correction_and_requires_revision_for_reconfirmation(api):
    client, store, _ = api
    modules = [*BASE_MODULES, "eval_elast"]
    url = f"/pipelines/{THREAD_ID}"
    assert client.post(url + "/confirm", json={"modules": modules}).status_code == 200
    with pytest.raises(PipelineInvalid):
        store.check_module(THREAD_ID, "eval_elast", {"bTOF": True})
    current = client.get(url).json()["pipeline"]
    assert current["status"] == "needs_correction"
    assert current["issues"][0]["code"] == "tof_requires_screen"
    corrected = [*BASE_MODULES, "screen", "eval_elast"]
    assert client.post(url + "/confirm", json={"modules": corrected}).status_code == 409
    result = client.post(url + "/confirm", json={"modules": corrected, "revision": 1})
    assert result.status_code == 200
    assert result.json()["pipeline"]["revision"] == 2


@pytest.mark.parametrize("extra", [[], ["capture_flux"]])
def test_reconfirmation_rejects_unresolved_tof_dependency(api, extra):
    client, store, _ = api
    modules = [*BASE_MODULES, "eval_elast"]
    store.confirm(THREAD_ID, modules, None)
    with pytest.raises(PipelineInvalid):
        store.check_module(THREAD_ID, "eval_elast", {"bTOF": True})
    previous = store.get(THREAD_ID)

    response = client.post(
        f"/pipelines/{THREAD_ID}/confirm",
        json={"modules": [*BASE_MODULES, *extra, "eval_elast"], "revision": 1},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["issues"][0]["code"] == "tof_requires_screen"
    assert store.get(THREAD_ID) == previous
    assert (
        client.get(f"/pipelines/{THREAD_ID}").json()["pipeline"]["status"]
        == "needs_correction"
    )


@pytest.mark.parametrize("optional", [["screen", "eval_elast"], []])
def test_reconfirmation_accepts_a_resolved_tof_dependency(api, optional):
    client, store, _ = api
    store.confirm(THREAD_ID, [*BASE_MODULES, "eval_elast"], None)
    with pytest.raises(PipelineInvalid):
        store.check_module(THREAD_ID, "eval_elast", {"bTOF": True})
    response = client.post(
        f"/pipelines/{THREAD_ID}/confirm",
        json={"modules": [*BASE_MODULES, *optional], "revision": 1},
    )
    assert response.status_code == 200
    assert response.json()["pipeline"]["revision"] == 2
    assert response.json()["pipeline"]["issues"] == []


@pytest.mark.parametrize("selected", [True, False])
def test_builder_planner_accepts_capture_flux_in_tool_schema(
    tmp_path, configured, selected
):
    modules = [*BASE_MODULES, "capture_flux"] if selected else list(BASE_MODULES)
    PipelineStore(tmp_path).confirm(THREAD_ID, modules, None)
    planner = build_plan_tool(tmp_path)
    arguments = planner.tool_call_schema.model_validate(
        {"include_optional": ["capture_flux"]}
    )
    result = planner.func(runtime=runtime(), **arguments.model_dump())
    if selected:
        assert result.update["planned_execution_order"] == modules
        assert result.update["pipeline_revision"] == 1
    else:
        assert "planned_execution_order" not in result.update
        assert result.update["messages"][0].status == "error"


def test_builder_planner_keeps_ordinary_chat_capture_flux_default(tmp_path, configured):
    planner = build_plan_tool(tmp_path)
    arguments = planner.tool_call_schema.model_validate(
        {"include_optional": ["capture_flux", "screen"]}
    )
    result = planner.func(runtime=runtime(), **arguments.model_dump())
    assert result.update["planned_execution_order"] == [
        *BASE_MODULES,
        "capture_flux",
        "screen",
    ]
    assert result.update["pipeline_revision"] is None


def test_agent_cannot_add_a_module_missing_from_the_canvas(tmp_path, configured):
    PipelineStore(tmp_path).confirm(THREAD_ID, list(BASE_MODULES), None)
    result = build_plan_tool(tmp_path).func(
        runtime=runtime(), include_optional=["screen"]
    )
    assert "planned_execution_order" not in result.update
    assert result.update["messages"][0].status == "error"


def test_client_uses_authenticated_pipeline_routes():
    seen = []

    def answer(request):
        assert request.headers["cookie"] == "juena_session=token"
        seen.append((request.method, request.url.path))
        return httpx.Response(
            200, json={"pipeline": None, "modules": [], "message": "Configure"}
        )

    client = VitessClient("http://vitess.test", agent="vitess", session_token="token")
    client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(answer))
    try:
        client.pipeline_modules()
        client.get_pipeline(THREAD_ID)
        client.confirm_pipeline(THREAD_ID, list(BASE_MODULES), None)
    finally:
        client.close()
    assert seen == [
        ("GET", "/pipelines/modules"),
        ("GET", f"/pipelines/{THREAD_ID}"),
        ("POST", f"/pipelines/{THREAD_ID}/confirm"),
    ]


def test_dependency_failure_exits_real_specialist_graph_without_another_question(
    tmp_path, configured
):
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langchain_core.messages import AIMessage, HumanMessage

    from vitess_ai.agents.specialists.module_middleware import GuidedAskUserMiddleware
    from vitess_ai.state import VitessBridgeState

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    store = PipelineStore(tmp_path)
    store.confirm(THREAD_ID, [*BASE_MODULES, "eval_elast"], None)
    tool = named_tool(
        eval_tools(project_root=tmp_path), "validate_eval_elast_parameters"
    )
    model = Model(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "configure",
                        "name": tool.name,
                        "args": {
                            "parameters": {
                                "bTOF": True,
                                "TotLength": 1100,
                                "DetDist": 100,
                                "LmbdRef": 0,
                            }
                        },
                    }
                ],
            ),
            AIMessage(content="This must never become another question."),
        ]
    )
    graph = create_agent(
        model,
        tools=[tool],
        middleware=[GuidedAskUserMiddleware(module="eval_elast")],
        state_schema=VitessBridgeState,
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="Configure TOF")]},
        context=SimpleNamespace(thread_id=THREAD_ID),
    )
    assert store.get(THREAD_ID).status == "needs_correction"
    assert result["messages"][-1].type == "tool"
    assert "module_results" not in result or not result["module_results"]
