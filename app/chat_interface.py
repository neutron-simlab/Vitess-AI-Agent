"""The main chat page: the message history, the input box and the starter
questions.

Receiving the agent's reply as it streams in, and drawing it, is done by
juena-core (`juena_core.ui.streaming`), because that code has to match what
core's server sends. This file only lays out the page and shows the starter
questions.

There is no "approve this command" card. juena-chatbot needs one because its
model can suggest a shell command that a person must approve before it runs.
Here VITESS is a trusted program, and its settings are checked before it runs,
so what the user confirms is the settings themselves. That happens in the chat:
the agent in charge of a module shows its settings and asks with `ask_user`
before saving anything.
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
    # way would be mangled into the transcript. Files go through the sidebar;
    # the agent's question keeps this turn paused while the user uploads there.
    user_message = ChatMessage(type="human", content=prompt)
    st.session_state.messages.append(user_message)
    render_message(user_message)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        stream_and_display_response(prompt, placeholder)
