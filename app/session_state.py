"""Small, testable state transitions for the two-agent Streamlit page."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable
from uuid import UUID, uuid4

__all__ = ["adopt_thread_agent", "start_new_thread"]


def start_new_thread(
    state: MutableMapping[str, Any],
    *,
    make_id: Callable[[], UUID] = uuid4,
) -> None:
    """Leave the current agent's thread before entering the other mode."""

    state["thread_id"] = str(make_id())
    state["messages"] = []
    state["chat_initialized"] = True


def adopt_thread_agent(
    state: MutableMapping[str, Any], agent_id: str, *, known_agents: set[str]
) -> bool:
    """Restore the graph a persisted thread belongs to.

    Returns whether the caller must rerun so its client is rebuilt for that
    agent before any message is sent.
    """

    if agent_id not in known_agents:
        raise ValueError(f"Conversation belongs to unknown agent {agent_id!r}")
    if state.get("selected_agent") == agent_id:
        return False
    state["selected_agent"] = agent_id
    return True
