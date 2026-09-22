"""Stand-ins for the VITESS MCP server, and real state to run against it.

One definition, because two copies of a test double drift exactly as two copies
of anything else do -- and a drifted double is worse than a drifted helper,
because it makes two test files disagree about the contract while both pass.

`configured_modules` is the part worth reading: it does not hand-write
`module_results`. It stages real upload files, calls each module's **real**
validation tool, and returns what those tools wrote. So a test that runs a
pipeline runs one the specialists could actually have produced, and breaking a
validation tool breaks the tests that depend on its output.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from vitess_ai.agents.specialists.capture_flux.tools import (
    build_sweep_tools as capture_flux_sweep,
)
from vitess_ai.agents.specialists.capture_flux.tools import build_tools as capture_flux_tools
from vitess_ai.agents.specialists.guide.tools import build_sweep_tools as guide_sweep
from vitess_ai.agents.specialists.guide.tools import build_tools as guide_tools
from vitess_ai.agents.specialists.monitor1d.tools import build_sweep_tools as monitor1d_sweep
from vitess_ai.agents.specialists.monitor1d.tools import build_tools as monitor1d_tools
from vitess_ai.agents.specialists.monitor2d.tools import build_sweep_tools as monitor2d_sweep
from vitess_ai.agents.specialists.monitor2d.tools import build_tools as monitor2d_tools
from vitess_ai.agents.specialists.readin.tools import build_sweep_tools as readin_sweep
from vitess_ai.agents.specialists.readin.tools import build_tools as readin_tools
from vitess_ai.agents.specialists.writeout.tools import build_sweep_tools as writeout_sweep
from vitess_ai.agents.specialists.writeout.tools import build_tools as writeout_tools
from vitess_ai.mcp.connection import TOOL_NAMES
from vitess_ai.modules.catalog import execution_order

THREAD_ID = "11111111-1111-4111-8111-111111111111"
SIMULATION_RUN_ID = "22222222-2222-4222-8222-222222222222"
GRAPH_RUN_ID = "33333333-3333-4333-8333-333333333333"


# ---------------------------------------------------------------------------
# The MCP server, as the application sees it
# ---------------------------------------------------------------------------


class RawTool:
    """One discovered MCP tool: prose for the model, evidence in the artifact."""

    def __init__(self, name: str, handler: Any) -> None:
        self.name = name
        self._handler = handler
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, call: dict[str, Any]) -> ToolMessage:
        self.calls.append(call)
        result = self._handler(call)
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, ToolMessage):
            return result
        return ToolMessage(
            content="model-facing prose that is deliberately not parsed",
            tool_call_id=call["id"],
            artifact={"structured_content": result},
        )


def module_payload(name: str, exit_code: int = 0) -> dict[str, Any]:
    return {
        "name": name,
        "executable": f"/vitess/MODULES/{name}",
        "exit_code": exit_code,
        "started_at": "2026-09-16T12:00:00+00:00",
        "ended_at": "2026-09-16T12:00:01+00:00",
        "stdout_tail": "",
        "stderr_tail": "",
    }


def simulation_payload(
    *,
    thread_id: str = THREAD_ID,
    simulation_run_id: str = SIMULATION_RUN_ID,
    success: bool = True,
    exit_codes: tuple[int, ...] | None = None,
    files: list[dict[str, Any]] | None = None,
    modules: list[str] | None = None,
) -> dict[str, Any]:
    names = modules or list(execution_order())
    codes = exit_codes or (0,) * len(names)
    return {
        "success": success,
        "timed_out": False,
        "thread_id": thread_id,
        "simulation_run_id": simulation_run_id,
        "modules": [
            module_payload(name, code) for name, code in zip(names, codes, strict=True)
        ],
        "files": files or [],
        "message": "Pipeline completed" if success else "Pipeline failed",
    }


def raw_tools(**handlers: Any) -> list[RawTool]:
    defaults = {
        "run_simulation": lambda call: simulation_payload(
            thread_id=call["args"]["thread_id"],
            simulation_run_id=call["args"]["simulation_run_id"],
            modules=list(call["args"]["execution_order"]),
        ),
        "inspect_thread_folders": lambda call: {
            "thread_id": call["args"]["thread_id"],
            "exists": False,
            "uploads": [],
            "runs": [],
            "message": "Nothing staged",
        },
        "generate_monitor1d_plot": lambda call: {
            "kind": "monitor1d",
            "source": "monitor1D.dat",
            "path": "monitor1D.png",
            "size_bytes": 1,
            "title": "Monitor 1D",
            "x_label": "x",
            "y_label": "y",
            "message": "Rendered",
        },
        "generate_monitor2d_plot": lambda call: {
            "kind": "monitor2d",
            "source": "monitor2D.dat",
            "path": "monitor2D.png",
            "size_bytes": 1,
            "title": "Monitor 2D",
            "x_label": "x",
            "y_label": "y",
            "message": "Rendered",
        },
    }
    defaults.update(handlers)
    return [RawTool(name, defaults[name]) for name in TOOL_NAMES]


# ---------------------------------------------------------------------------
# Runtime and state
# ---------------------------------------------------------------------------


def runtime(
    *,
    state: dict[str, Any] | None = None,
    tool_call_id: str = "facade-call",
    thread_id: str = THREAD_ID,
) -> Any:
    return SimpleNamespace(
        execution_info=SimpleNamespace(thread_id=thread_id, run_id=GRAPH_RUN_ID),
        context=SimpleNamespace(user_id="user-a", thread_id=thread_id),
        state=state if state is not None else {},
        tool_call_id=tool_call_id,
    )


def named_tool(tools: list[Any], name: str) -> Any:
    return next(item for item in tools if item.name == name)


def stage_uploads(project_root: Path, thread_id: str = THREAD_ID) -> dict[str, str]:
    """Put real files where a real upload would have put them."""
    staged: dict[str, str] = {}
    for module, filename in (
        ("readin", "beam.dat"),
        ("instrument", "instrument.inf"),
        ("guide", "guide_shape.dat"),
    ):
        directory = project_root / thread_id / "uploads" / module
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        path.write_text("staged by the test\n", encoding="utf-8")
        staged[module] = str(path)
    return staged


def _validated(tool: Any, parameters: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Call one real validation tool and return what it wrote to state."""
    call = tool.coroutine or tool.func
    result = call(runtime=runtime(**kwargs), parameters=parameters)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    assert isinstance(result, Command), result
    written = result.update.get("module_results")
    if written is None:
        raise AssertionError(result.update["messages"][0].text)
    return written


def configured_modules(
    project_root: Path,
    thread_id: str = THREAD_ID,
    *,
    only: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """The `module_results` the six real validation tools produce for one thread.

    Uses each module's own tool, so these are configurations the specialists
    could have produced -- not a dictionary shaped to satisfy the reader.
    """
    staged = stage_uploads(project_root, thread_id)
    gateway = None  # the validation tools never touch it
    written: dict[str, Any] = {}

    written.update(
        _validated(
            named_tool(
                readin_tools(project_root=project_root, gateway=gateway),
                "validate_readin_parameters",
            ),
            {
                "sInputFileName": [staged["readin"]],
                "Weight": [1.0],
                "sInstrInfIn": staged["instrument"],
            },
            thread_id=thread_id,
        )
    )
    written.update(
        _validated(
            named_tool(
                guide_tools(project_root=project_root, gateway=gateway),
                "validate_guide_parameters",
            ),
            {},
            thread_id=thread_id,
        )
    )
    written.update(
        _validated(
            named_tool(
                writeout_tools(project_root=project_root),
                "validate_writeout_parameters",
            ),
            {"sOutFileName": "output.dat"},
            thread_id=thread_id,
        )
    )
    written.update(
        _validated(
            named_tool(
                monitor1d_tools(project_root=project_root),
                "validate_monitor1d_parameters",
            ),
            {},
            thread_id=thread_id,
        )
    )
    written.update(
        _validated(
            named_tool(
                monitor2d_tools(project_root=project_root),
                "validate_monitor2d_parameters",
            ),
            {},
            thread_id=thread_id,
        )
    )
    written.update(
        _validated(
            named_tool(
                capture_flux_tools(project_root=project_root),
                "validate_capture_flux_parameters",
            ),
            {},
            thread_id=thread_id,
        )
    )
    if only is not None:
        written = {name: value for name, value in written.items() if name in only}
    return written


def _swept(tool: Any, parameter_sets: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """Call one real sweep validation tool and return what it wrote to state."""
    call = tool.coroutine or tool.func
    result = call(runtime=runtime(**kwargs), parameter_sets=parameter_sets)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    assert isinstance(result, Command), result
    written = result.update.get("module_variants")
    if written is None:
        raise AssertionError(result.update["messages"][0].text)
    return written


def swept_modules(
    project_root: Path,
    thread_id: str = THREAD_ID,
    *,
    guide_widths: tuple[float, ...] = (3.0,),
) -> dict[str, Any]:
    """The `module_variants` the six real sweep tools produce for one thread.

    The sweep equivalent of `configured_modules`, and for the same reason: a
    plan built from hand-written variants would prove nothing about what a
    sweep specialist can actually record. Only the guide varies, which is what
    a one-parameter sweep looks like; the other five send the single-element
    list a module with no variation still has to send.
    """
    staged = stage_uploads(project_root, thread_id)
    gateway = None  # the validation tools never touch it
    written: dict[str, Any] = {}

    written.update(
        _swept(
            named_tool(
                readin_sweep(project_root=project_root, gateway=gateway),
                "validate_readin_variants",
            ),
            [
                {
                    "sInputFileName": [staged["readin"]],
                    "Weight": [1.0],
                    "sInstrInfIn": staged["instrument"],
                }
            ],
            thread_id=thread_id,
        )
    )
    written.update(
        _swept(
            named_tool(
                guide_sweep(project_root=project_root, gateway=gateway),
                "validate_guide_variants",
            ),
            [{"GuideEntrWidth": width} for width in guide_widths],
            thread_id=thread_id,
        )
    )
    written.update(
        _swept(
            named_tool(
                writeout_sweep(project_root=project_root),
                "validate_writeout_variants",
            ),
            [{"sOutFileName": "output.dat"}],
            thread_id=thread_id,
        )
    )
    written.update(
        _swept(
            named_tool(
                monitor1d_sweep(project_root=project_root),
                "validate_monitor1d_variants",
            ),
            [{}],
            thread_id=thread_id,
        )
    )
    written.update(
        _swept(
            named_tool(
                monitor2d_sweep(project_root=project_root),
                "validate_monitor2d_variants",
            ),
            [{}],
            thread_id=thread_id,
        )
    )
    written.update(
        _swept(
            named_tool(
                capture_flux_sweep(project_root=project_root),
                "validate_capture_flux_variants",
            ),
            [{}],
            thread_id=thread_id,
        )
    )
    return written
