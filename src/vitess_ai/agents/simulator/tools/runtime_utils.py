"""
Helpers for resolving runtime-dependent values in simulator tools.
"""

from __future__ import annotations

import os
from typing import Any

from langchain.tools import ToolRuntime


def _get_configurable(config: Any) -> dict[str, Any]:
    """Best-effort extraction of RunnableConfig.configurable as a dictionary."""
    if config is None:
        return {}
    configurable = (
        config.get("configurable", None)
        if hasattr(config, "get")
        else getattr(config, "configurable", None)
    )
    return configurable if isinstance(configurable, dict) else {}


def resolve_thread_id(
    thread_id: str | None = None,
    runtime: ToolRuntime | None = None,
) -> str | None:
    """
    Resolve thread_id with fallback order:
    1) explicit argument
    2) runtime.config.configurable["thread_id"]
    3) runtime.state["thread_id"]
    4) process env THREAD_ID
    """
    if thread_id:
        return thread_id

    if runtime is not None:
        configurable = _get_configurable(getattr(runtime, "config", None))
        runtime_thread_id = configurable.get("thread_id")
        if runtime_thread_id:
            return str(runtime_thread_id)

        state = getattr(runtime, "state", None)
        if isinstance(state, dict):
            state_thread_id = state.get("thread_id")
            if state_thread_id:
                return str(state_thread_id)

    return os.environ.get("THREAD_ID")
