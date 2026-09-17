"""The chat page.

The stream loop, the chunk classifiers and the question card are
`juena_core.ui.streaming`'s -- they implement the SSE contract core's server
emits. What is left here is the layout and the starter chips.

There is no approval card. juena-chatbot has one because a model there proposes
a shell command for a person to approve; VITESS runs a trusted binary with
parameters a validator has already accepted, so the thing being confirmed is
the *configuration*, and that happens in the conversation itself -- the
specialist presents it and calls `ask_user` before recording anything.
"""

from __future__ import annotations

import streamlit as st

from juena_core.schema.server import ChatMessage
from juena_core.ui.streaming import render_pending_interrupt, stream_and_display_response

from app.starters import build_starter_prompts
from app.ui_components import (
    render_chat_input_styles,
    render_header,
    render_message,
    reset_rendered_artifacts,
)

__all__ = ["render_chat_interface"]

STARTER_PILLS_KEY = "starter_pills"


def _render_starters(agent: str) -> str | None:
    """Starter chips for an empty thread, for the selected agent only."""

    starters = build_starter_prompts(agent)
    if not starters:
        return None

    st.caption("Not sure where to start?")
    chosen = st.pills(
        "Starter topics",
        options=[starter.label for starter in starters],
        selection_mode="single",
        default=None,
        key=f"{STARTER_PILLS_KEY}:{st.session_state.thread_id}",
        label_visibility="collapsed",
    )
    if not chosen:
        return None
    return next(starter.prompt for starter in starters if starter.label == chosen)


def render_chat_interface() -> None:
    """Render the header, the transcript, any pending question, and the composer."""

    reset_rendered_artifacts()
    render_header(st.session_state.selected_agent)
    render_chat_input_styles()

    for message in st.session_state.messages:
        render_message(message, show_system=st.session_state.show_system_messages)

    # A specialist that needs a file asks here, in the chat, rather than leaving
    # the user to discover the sidebar. `ask_user` already raises a LangGraph
    # interrupt, already renders as a card and already resumes the thread; this
    # is the whole mechanism, and there is no second one.
    if render_pending_interrupt():
        return

    # On an empty thread the composer sits under the title with the chips below
    # it, so the first thing anyone sees is where to type. `st.chat_input` pins
    # itself to the bottom only when called at the top level of the script.
    starter: str | None = None
    if not st.session_state.messages:
        with st.container():
            submission = st.chat_input(placeholder="Describe the simulation you want…")
        starter = _render_starters(st.session_state.selected_agent)
    else:
        submission = st.chat_input(placeholder="Describe the simulation you want…")

    prompt = str(submission or "") or (starter or "")
    if not prompt:
        return

    # Deliberately no `accept_file`: a VITESS input file is a real path on the
    # shared volume that a compiled binary opens, and the composer's attachment
    # path decodes uploads as text into graph state. A trajectory file sent that
    # way would be mangled into the transcript. Files go through the sidebar or
    # through the agent's own question, both of which post to `/files`.
    user_message = ChatMessage(type="human", content=prompt)
    st.session_state.messages.append(user_message)
    render_message(user_message)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        stream_and_display_response(prompt, placeholder)
