"""The sidebar: which agent, which conversation, and what is staged for it.

596 lines in the first generation, most of it six per-module upload widgets and
a path-only mode that uploaded nothing. The upload half now lives in
`file_management.render_file_manifest`, over three slots, and what is left here
is navigation: the agent, the model, the conversation list.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from juena_core.llms_providers import get_available_providers, get_default_model
from juena_core.schema.llm_models import Provider

from app.chat_list import render_chat_list
from app.file_management import render_file_manifest
from app.session_state import start_new_thread

__all__ = ["AGENTS", "render_sidebar"]

#: The two registered agents, and what distinguishes them in one line. They
#: differ in *interaction model*, not expertise -- one is a conversation, the
#: other a batch -- which is why they are two agent ids on separate threads
#: rather than one supervisor with two specialists (03/CP5).
AGENTS = {
    "vitess": ("Guided simulation", "Configure and run one simulation, with you."),
    "advanced_mode": ("Advanced mode", "Plan a parameter sweep and run it unattended."),
}


def _render_agent_picker() -> None:
    chosen = st.radio(
        "Mode",
        options=list(AGENTS),
        format_func=lambda key: AGENTS[key][0],
        key="selected_agent",
        on_change=start_new_thread,
        args=(st.session_state,),
        help="Each mode keeps its own conversations.",
    )
    st.caption(AGENTS[chosen][1])


def _render_model_picker() -> None:
    available = get_available_providers()
    providers = [item.value for item in Provider if available.get(item.value, False)]
    if not providers:
        st.warning("No model provider is configured; set an API key and restart.")
        return

    if st.session_state.selected_provider not in providers:
        st.session_state.selected_provider = providers[0]
    provider = st.selectbox(
        "Provider", options=providers, key="selected_provider"
    )
    default = get_default_model(provider)
    if st.session_state.get("selected_model_provider") != provider:
        st.session_state.selected_model = default or ""
        st.session_state.selected_model_provider = provider
    st.text_input("Model", key="selected_model", help="The model the agent runs on.")


def render_sidebar(client: Any) -> None:
    with st.sidebar:
        _render_agent_picker()
        st.divider()

        # The manifest sits above the conversation list on purpose: it is the
        # thing a user checks before sending a message, not after.
        render_file_manifest(client, st.session_state.thread_id)
        st.divider()

        render_chat_list(client, st.session_state.selected_agent)
        st.divider()

        with st.expander("Model", expanded=False):
            _render_model_picker()
        st.toggle("Show tool messages", key="show_system_messages")
