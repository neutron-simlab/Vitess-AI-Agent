"""End a guided turn when its confirmed topology needs a canvas correction."""

from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage

from vitess_ai.pipeline import PipelineStore


class PipelineCorrectionMiddleware(AgentMiddleware):
    def __init__(self, project_root: Path):
        self.store = PipelineStore(project_root)

    def _check(self, runtime: Any) -> dict | None:
        context = runtime.context
        thread_id = (
            context.get("thread_id")
            if isinstance(context, dict)
            else getattr(context, "thread_id", None)
        )
        if not thread_id:
            return None
        record = self.store.get(thread_id)
        if record and record.status == "needs_correction":
            return {
                "messages": [
                    AIMessage(
                        id=f"pipeline-correction-{record.revision}",
                        content="The pipeline needs a correction before configuration can continue. "
                        + " ".join(
                            f"{issue.message} {issue.correction}"
                            for issue in record.issues
                        )
                        + " Return to the canvas above, correct it, and confirm again.",
                    )
                ],
                "jump_to": "end",
            }
        return None

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: Any, runtime: Any) -> dict | None:
        return self._check(runtime)

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: Any, runtime: Any) -> dict | None:
        return self._check(runtime)
