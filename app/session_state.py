"""Small, testable state transitions for the two-agent Streamlit page."""

from __future__ import annotations

from collections.abc import MutableMapping, Sequence
from typing import Any, Callable
from uuid import UUID, uuid4

__all__ = ["adopt_thread_agent", "leave_deleted_thread", "start_new_thread"]


def start_new_thread(
    state: MutableMapping[str, Any],
    *,
    make_id: Callable[[], UUID] = uuid4,
) -> None:
    """Leave the current agent's thread before entering the other mode."""

    state["thread_id"] = str(make_id())
    state["messages"] = []
    state["chat_initialized"] = True


def leave_deleted_thread(
    state: MutableMapping[str, Any],
    *,
    deleted: str,
    remaining: Sequence[str],
    make_id: Callable[[], UUID] = uuid4,
) -> str | None:
    """Enter a surviving conversation after deleting the one being viewed.

    Returns the thread whose messages the caller must load, or `None` when
    nothing survived and a fresh thread was started instead.

    Leaving `thread_id` on a deleted thread is the one outcome that must not
    happen: the page would go on sending messages to it and the server would
    keep answering, so the user would be talking to a conversation the sidebar
    no longer lists. `deleted` is therefore filtered out here rather than by
    the caller -- the listing it passes comes from the server and may still
    hold the row that was just removed.
    """

    survivors = [thread for thread in remaining if thread != deleted]
    if not survivors:
        start_new_thread(state, make_id=make_id)
        return None
    state["thread_id"] = survivors[0]
    state["messages"] = []
    state["chat_initialized"] = True
    return survivors[0]


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
