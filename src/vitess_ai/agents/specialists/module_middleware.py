"""The hooks that run around a module specialist's model turns.

These are not tools: the model never calls them. `create_agent` runs them
before or after each model call, or once when the specialist finishes, and
`build_module_specialist` in `module_specialist.py` decides which ones a
specialist gets and in what order.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage
from pydantic import BaseModel, ValidationError

from juena_core.schema.agents import SpecialistReport
from vitess_ai.cli.arguments import ParameterConversionError, parameters_to_arguments
from vitess_ai.schema.module_result import ModuleConfigurationResult

__all__ = [
    "GuidedAskUserMiddleware",
    "ModuleReportMiddleware",
]


class GuidedAskUserMiddleware(AgentMiddleware):
    """Turn a guided specialist's premature prose exit into a real question.

    Some tool-calling models can ignore both the prompt and ``tool_choice`` and
    emit the question they meant to pass to ``ask_user`` as ordinary assistant
    text. LangChain treats an assistant message without tool calls as the end of
    the subgraph, so the question otherwise returns to the supervisor and the
    specialist outcome is correctly, but unhelpfully, marked unverified.

    Before this specialist has recorded its validated module result, ordinary
    prose cannot be a valid terminal result. Preserve that prose verbatim as the
    question and route it through the already-bound ``ask_user`` tool. Once the
    validation tool has written the module result, this middleware is inert so
    it cannot interfere with the final structured report.
    """

    def __init__(self, *, module: str) -> None:
        self._module = module

    def _redirect(self, state: Any) -> dict[str, Any] | None:
        values = state if isinstance(state, Mapping) else {}
        if values.get("structured_response") is not None:
            return None
        module_results = values.get("module_results")
        if isinstance(module_results, Mapping) and self._module in module_results:
            return None

        messages = values.get("messages", [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        message = messages[-1]
        if message.tool_calls:
            return None
        question = str(message.text).strip()
        if not question:
            return None

        redirected = message.model_copy(
            update={
                "tool_calls": [
                    {
                        "name": "ask_user",
                        "args": {"question": question, "options": []},
                        "id": f"ask_user_{uuid4().hex}",
                        "type": "tool_call",
                    }
                ]
            }
        )
        return {"messages": [redirected], "jump_to": "tools"}

    @hook_config(can_jump_to=["tools"])
    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self._redirect(state)

    @hook_config(can_jump_to=["tools"])
    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self._redirect(state)


class ModuleReportMiddleware(AgentMiddleware):
    """Report the configuration the validation tool recorded, when the model didn't.

    A module specialist's deliverable is the `ModuleConfigurationResult` its
    validation tool wrote -- the one object in this subgraph a model cannot
    author. The `SpecialistReport` is only how that result is *narrated* to the
    supervisor, and narration is the part a weak model drops. `create_agent`
    ends the loop at the first assistant message without tool calls, *before*
    it checks for structured output at all, so a specialist that signs off in
    prose leaves `structured_response` unset and gets no retry. A report
    emitted in the same turn as another tool call is lost too: it is captured,
    then cleared by the next model call because `response_format` is set.

    `SpecialistOutcomeMiddleware` then calls the hand-off unverified. That is
    right for a research specialist whose report is its only deliverable, and
    wrong here -- the configuration is recorded, it crosses the boundary in
    `module_results`, and the supervisor is nonetheless told to tell the user
    the attempt failed. One live readin run validated `guide-1_in.dat`, signed
    off with its finding as prose, and reached the user as a specialist that
    "didn't have enough information".

    So when the result is there and the report is not, the server writes the
    report from the result. This runs *before* `SpecialistOutcomeMiddleware`
    because `after_agent` hooks run in reverse order of the middleware list and
    `build_specialist_middleware` mounts that one first.
    """

    def __init__(
        self, *, module: str, model: type[BaseModel], unattended: bool
    ) -> None:
        self._module = module
        self._model = model
        # The guided tool records one configuration; the sweep's records a list.
        self._channel = "module_variants" if unattended else "module_results"

    def _arguments(self, result: ModuleConfigurationResult) -> str | None:
        """The one canonical rendering of what this configuration runs as.

        Derived here rather than read from a stored copy, which is the rule
        `ModuleConfigurationResult` sets: two answers to "what does this run
        as" drift. `validate_module_parameters` already converted these exact
        parameters, so this cannot fail on a result recorded by this build --
        but `schema_version` exists precisely because a configuration
        checkpointed under an older schema can come back, and that is the case
        this gives up on rather than losing the whole report to.
        """
        try:
            return " ".join(parameters_to_arguments(self._model(**result.parameters)))
        except (ValidationError, ParameterConversionError):
            return None

    def _report(self, results: list[ModuleConfigurationResult]) -> SpecialistReport:
        recorded = (
            f"{len(results)} variants"
            if self._channel == "module_variants"
            else "its parameters"
        )
        evidence: list[str] = []
        for result in results:
            evidence.append(
                f"Recorded {result.validated_at.isoformat()} "
                f"(schema {result.schema_version})"
            )
            arguments = self._arguments(result)
            if arguments is not None:
                evidence.append(f"VITESS will run it as: {arguments}")
        return SpecialistReport(
            status="completed",
            finding=(
                f"{self._module} is configured: the validation tool recorded "
                f"{recorded} for this conversation."
            ),
            evidence=evidence,
            # Said plainly, because the supervisor would otherwise present
            # server-authored narration as the specialist's own reasoning.
            limitations=[
                "The server wrote this report from the recorded configuration "
                "because the specialist ended without returning one. Nothing it "
                "said mid-run is included here."
            ],
        )

    def _fill(self, state: Any) -> dict[str, Any] | None:
        values = state if isinstance(state, Mapping) else {}
        # A report the model did return is its own work; this only fills a gap.
        if values.get("structured_response") is not None:
            return None
        recorded = values.get(self._channel)
        own = recorded.get(self._module) if isinstance(recorded, Mapping) else None
        if own is None:
            return None
        try:
            results = [
                ModuleConfigurationResult.model_validate(item)
                for item in (own if isinstance(own, list) else [own])
            ]
        except ValidationError:
            return None
        if not results:
            return None
        return {"structured_response": self._report(results)}

    def after_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self._fill(state)

    async def aafter_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self._fill(state)
