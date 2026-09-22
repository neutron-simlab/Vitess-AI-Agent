"""Trusted application gateway to the raw VITESS MCP tools.

The tools discovered from :mod:`vitess_ai.mcp.server` are deliberately not
model tools: their schemas contain ownership identifiers and already-validated
module parameters.  This module is the one place application code invokes
them.  It validates MCP ``structuredContent`` before turning it into typed
execution evidence; prose in the MCP text block is never parsed as evidence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID, uuid4

from langchain_core.messages import ToolMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from juena_core.schema.interrupts import ExecutionEvidence
from vitess_ai.mcp.connection import TOOL_NAMES
from vitess_ai.mcp.payloads import (
    PlotResult,
    RunFile,
    SimulationResult,
    ThreadInspection,
)

__all__ = [
    "GatewayFailure",
    "GatewayResult",
    "InternalSimulationRequest",
    "MCPToolArtifact",
    "SimulationOutcome",
    "VitessGateway",
    "safe_run_file",
]

_ERROR_LIMIT = 2_000
_TAIL_LIMIT = 8_192


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MCPToolArtifact(_StrictModel):
    """The LangChain representation of an MCP result's structured channel."""

    structured_content: dict[str, Any]


class InternalSimulationRequest(_StrictModel):
    """A request assembled from trusted runtime state, never model arguments."""

    thread_id: UUID
    simulation_run_id: UUID
    graph_run_id: str = Field(min_length=1, max_length=255)
    module_results: dict[str, dict[str, Any]]
    execution_order: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def complete_pipeline(self) -> InternalSimulationRequest:
        expected = set(self.execution_order)
        actual = set(self.module_results)
        if len(expected) != len(self.execution_order):
            raise ValueError("execution_order contains duplicate module names")
        if actual != expected:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            detail = []
            if missing:
                detail.append(f"missing: {', '.join(missing)}")
            if unexpected:
                detail.append(f"unexpected: {', '.join(unexpected)}")
            raise ValueError("module_results do not match execution_order (" + "; ".join(detail) + ")")
        for module, result in self.module_results.items():
            arguments = result.get("cli_parameters")
            if (
                not isinstance(arguments, list)
                or not arguments
                or any(not isinstance(item, str) or not item for item in arguments)
            ):
                raise ValueError(
                    f"module_results[{module!r}].cli_parameters must be a non-empty list[str]"
                )
        return self


FailureStatus = Literal["timed_out", "unavailable", "tool_error"]


class GatewayFailure(_StrictModel):
    status: FailureStatus
    message: str = Field(min_length=1, max_length=_ERROR_LIMIT)


PayloadT = TypeVar("PayloadT")


@dataclass(frozen=True, slots=True)
class GatewayResult(Generic[PayloadT]):
    """Exactly one of ``value`` and ``failure`` is populated."""

    value: PayloadT | None = None
    failure: GatewayFailure | None = None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.failure is None):
            raise ValueError("A gateway result must contain one value or one failure")


@dataclass(frozen=True, slots=True)
class SimulationOutcome:
    result: SimulationResult | None
    events: tuple[ExecutionEvidence, ...]
    failure: GatewayFailure | None = None

    @property
    def success(self) -> bool:
        return self.result is not None and self.result.success and self.failure is None


def _bounded_error(value: object) -> str:
    text = str(value).strip() or type(value).__name__
    return text if len(text) <= _ERROR_LIMIT else text[: _ERROR_LIMIT - 1] + "…"


def _safe_relative_path(value: str, *, field_name: str) -> PurePosixPath:
    """Validate a server-authored path before it ever reaches ``pathlib.Path``."""

    if not value or len(value) > 4_096 or "\x00" in value or "\\" in value:
        raise ValueError(f"{field_name} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError(f"{field_name} must stay beneath the simulation run directory")
    return path


def safe_run_file(
    project_root: str | Path,
    *,
    thread_id: str,
    simulation_run_id: str,
    descriptor: RunFile,
) -> Path:
    """Resolve and verify one file claimed by the MCP server.

    The application performs this check against its own mount.  Sharing a
    volume does not make an absolute path or a symlink supplied by another
    process trustworthy.
    """

    try:
        canonical_thread = str(UUID(thread_id))
        canonical_run = str(UUID(simulation_run_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("thread_id and simulation_run_id must be UUIDs") from exc
    if thread_id != canonical_thread or simulation_run_id != canonical_run:
        raise ValueError("thread_id and simulation_run_id must use canonical UUID form")

    relative = _safe_relative_path(descriptor.path, field_name="Produced file path")
    root = Path(project_root).expanduser().resolve()
    thread_root = root / canonical_thread
    outputs_root = thread_root / "outputs"
    lexical_run_root = outputs_root / canonical_run
    for component, label in (
        (thread_root, "Thread directory"),
        (outputs_root, "Outputs directory"),
        (lexical_run_root, "Simulation run directory"),
    ):
        if component.is_symlink():
            raise ValueError(f"{label} must not be a symbolic link")
    run_root = lexical_run_root.resolve()
    try:
        run_root.relative_to(root)
    except ValueError as exc:
        raise ValueError("Simulation run directory escapes the project root") from exc

    candidate = run_root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(
                f"Produced file path must not contain a symbolic link: {descriptor.path}"
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(run_root)
    except FileNotFoundError as exc:
        raise ValueError(f"MCP claimed an absent file: {descriptor.path}") from exc
    except ValueError as exc:
        raise ValueError(f"Produced file escapes the simulation run: {descriptor.path}") from exc
    if not resolved.is_file():
        raise ValueError(f"MCP result path is not a file: {descriptor.path}")
    actual_size = resolved.stat().st_size
    if actual_size != descriptor.size_bytes:
        raise ValueError(
            f"MCP file size mismatch for {descriptor.path}: "
            f"claimed {descriptor.size_bytes}, found {actual_size}"
        )
    return resolved


class VitessGateway:
    """Invoke and validate the four raw tools discovered from VITESS MCP."""

    def __init__(self, tools: Iterable[Any]) -> None:
        indexed: dict[str, Any] = {}
        for tool in tools:
            name = getattr(tool, "name", None)
            if not isinstance(name, str) or not name:
                raise ValueError("Every raw VITESS tool must have a name")
            if name in indexed:
                raise ValueError(f"Duplicate raw VITESS tool: {name}")
            indexed[name] = tool
        expected = set(TOOL_NAMES)
        if set(indexed) != expected:
            missing = sorted(expected - set(indexed))
            unexpected = sorted(set(indexed) - expected)
            detail = []
            if missing:
                detail.append(f"missing: {', '.join(missing)}")
            if unexpected:
                detail.append(f"unexpected: {', '.join(unexpected)}")
            raise ValueError("Raw VITESS tool set mismatch (" + "; ".join(detail) + ")")
        self._tools = indexed

    async def _call(
        self,
        name: str,
        arguments: Mapping[str, Any],
        payload_type: type[PayloadT],
    ) -> GatewayResult[PayloadT]:
        call = {
            "type": "tool_call",
            "id": f"vitess-internal-{uuid4()}",
            "name": name,
            "args": dict(arguments),
        }
        try:
            message = await self._tools[name].ainvoke(call)
        except asyncio.TimeoutError as exc:
            return GatewayResult(
                failure=GatewayFailure(status="timed_out", message=_bounded_error(exc))
            )
        except Exception as exc:  # the adapter's transport exception is not public API
            return GatewayResult(
                failure=GatewayFailure(status="unavailable", message=_bounded_error(exc))
            )

        if not isinstance(message, ToolMessage):
            return GatewayResult(
                failure=GatewayFailure(
                    status="tool_error",
                    message=f"VITESS MCP returned {type(message).__name__}, not ToolMessage",
                )
            )
        if message.status == "error":
            return GatewayResult(
                failure=GatewayFailure(
                    status="tool_error",
                    message=_bounded_error(message.text),
                )
            )
        try:
            artifact = MCPToolArtifact.model_validate(message.artifact)
            value = payload_type.model_validate(artifact.structured_content)
        except (TypeError, ValidationError, ValueError) as exc:
            return GatewayResult(
                failure=GatewayFailure(
                    status="tool_error",
                    message=f"Invalid VITESS MCP structured content: {_bounded_error(exc)}",
                )
            )
        return GatewayResult(value=value)

    @staticmethod
    def _failure_event(
        request: InternalSimulationRequest,
        failure: GatewayFailure,
    ) -> ExecutionEvidence:
        return ExecutionEvidence(
            graph_run_id=request.graph_run_id,
            command="VITESS simulation",
            status=failure.status,
            exit_code=None,
        )

    @staticmethod
    def _validate_simulation_result(
        request: InternalSimulationRequest,
        result: SimulationResult,
    ) -> None:
        if result.thread_id != str(request.thread_id):
            raise ValueError("MCP returned evidence for a different thread_id")
        if result.simulation_run_id != str(request.simulation_run_id):
            raise ValueError("MCP returned evidence for a different simulation_run_id")

        names = [module.name for module in result.modules]
        expected = list(request.execution_order)
        if names and names != expected:
            raise ValueError(
                f"MCP module order mismatch: expected {expected!r}, received {names!r}"
            )
        for module in result.modules:
            executable = Path(module.executable)
            if not executable.is_absolute() or "$" in module.executable:
                raise ValueError(f"MCP returned an unresolved executable for {module.name}")
            for label, value in (
                ("started_at", module.started_at),
                ("ended_at", module.ended_at),
            ):
                try:
                    datetime.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(f"MCP returned an invalid {label} for {module.name}") from exc
            if len(module.stdout_tail) > _TAIL_LIMIT or len(module.stderr_tail) > _TAIL_LIMIT:
                raise ValueError(f"MCP returned an unbounded output tail for {module.name}")

        if result.success:
            if result.timed_out or names != expected or any(
                module.exit_code != 0 for module in result.modules
            ):
                raise ValueError("MCP success flag contradicts its module evidence")
        elif result.modules and not result.timed_out and all(
            module.exit_code == 0 for module in result.modules
        ):
            raise ValueError("MCP failure flag contradicts its module evidence")

        seen: set[str] = set()
        for descriptor in result.files:
            _safe_relative_path(descriptor.path, field_name="Produced file path")
            if descriptor.path in seen:
                raise ValueError(f"MCP returned duplicate produced file: {descriptor.path}")
            seen.add(descriptor.path)

    @staticmethod
    def _events(
        request: InternalSimulationRequest,
        result: SimulationResult,
    ) -> tuple[ExecutionEvidence, ...]:
        # A failed pipeline is one failed operation.  Reporting its earlier
        # zero-exit modules as separate successful attempts would let generic
        # retry semantics label the whole pipeline VERIFIED.
        if not result.success:
            failed_code = next(
                (module.exit_code for module in result.modules if module.exit_code != 0),
                None,
            )
            return (
                ExecutionEvidence(
                    graph_run_id=request.graph_run_id,
                    command="VITESS simulation",
                    status="timed_out" if result.timed_out else "failed",
                    exit_code=failed_code,
                ),
            )

        return tuple(
            ExecutionEvidence(
                graph_run_id=request.graph_run_id,
                command=f"{module.name}: {module.executable}",
                status="completed",
                exit_code=module.exit_code,
            )
            for module in result.modules
        )

    async def run_simulation(
        self,
        request: InternalSimulationRequest,
    ) -> SimulationOutcome:
        response = await self._call(
            "run_simulation",
            {
                "thread_id": str(request.thread_id),
                "simulation_run_id": str(request.simulation_run_id),
                "module_results": request.module_results,
                "execution_order": list(request.execution_order),
            },
            SimulationResult,
        )
        if response.failure is not None:
            return SimulationOutcome(
                result=None,
                events=(self._failure_event(request, response.failure),),
                failure=response.failure,
            )
        assert response.value is not None
        try:
            self._validate_simulation_result(request, response.value)
        except ValueError as exc:
            failure = GatewayFailure(status="tool_error", message=_bounded_error(exc))
            return SimulationOutcome(
                result=None,
                events=(self._failure_event(request, failure),),
                failure=failure,
            )
        return SimulationOutcome(
            result=response.value,
            events=self._events(request, response.value),
        )

    async def inspect_thread(self, thread_id: str) -> GatewayResult[ThreadInspection]:
        response = await self._call(
            "inspect_thread_folders",
            {"thread_id": thread_id},
            ThreadInspection,
        )
        if response.value is not None and response.value.thread_id != thread_id:
            return GatewayResult(
                failure=GatewayFailure(
                    status="tool_error",
                    message="MCP returned an inspection for a different thread_id",
                )
            )
        return response

    async def generate_plot(
        self,
        *,
        kind: Literal["monitor1d", "monitor2d"],
        thread_id: str,
        simulation_run_id: str,
        filename: str | None = None,
    ) -> GatewayResult[PlotResult]:
        name = f"generate_{kind}_plot"
        arguments: dict[str, Any] = {
            "thread_id": thread_id,
            "simulation_run_id": simulation_run_id,
        }
        if filename is not None:
            arguments["filename"] = filename
        response = await self._call(name, arguments, PlotResult)
        if response.value is not None:
            if response.value.kind != kind:
                return GatewayResult(
                    failure=GatewayFailure(
                        status="tool_error",
                        message=f"MCP returned {response.value.kind} for a {kind} request",
                    )
                )
            try:
                _safe_relative_path(response.value.path, field_name="Plot path")
                _safe_relative_path(response.value.source, field_name="Plot source")
            except ValueError as exc:
                return GatewayResult(
                    failure=GatewayFailure(status="tool_error", message=_bounded_error(exc))
                )
        return response
