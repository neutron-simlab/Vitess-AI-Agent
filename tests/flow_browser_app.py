"""Browser harness: real chat canvas and API; deterministic agent handoff, no LLM."""

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
from conftest import make_settings
from juena_core.config import configure

configure(make_settings())

from doubles import runtime
from flow_browser_client import BrowserClient
from juena_core.schema.server import ChatMessage

from app import chat_interface
from vitess_ai.pipeline import PipelineInvalid
from vitess_ai.tools import build_plan_tool


@st.cache_resource
def client():
    return BrowserClient()


st.set_page_config(layout="wide")
st.session_state.setdefault("client", client())
st.session_state.setdefault("thread_id", st.query_params.get("thread") or str(uuid4()))
st.query_params["thread"] = st.session_state.thread_id
st.session_state.setdefault("selected_agent", "vitess")
st.session_state.setdefault("selected_provider", "blablador")
st.session_state.setdefault("selected_model", "test")
st.session_state.setdefault(
    "messages", list(client().messages.get(st.session_state.thread_id, []))
)
st.session_state.setdefault("show_system_messages", False)


def handoff(message, placeholder):
    thread = st.session_state.thread_id
    if client().pause_handoff_once:
        client().pause_handoff_once = False
        client().messages[thread] = list(st.session_state.messages)
        st.info("Handoff paused before planning")
        return
    plan = build_plan_tool(client().store.root).func(runtime=runtime(thread_id=thread))
    client().checkpoints[thread] = {"channel_values": plan.update}
    st.session_state.messages.append(
        ChatMessage(
            type="ai", content="Configuration started for the confirmed pipeline."
        )
    )
    client().messages[thread] = list(st.session_state.messages)
    st.rerun()


chat_interface.stream_and_display_response = handoff
with st.sidebar:
    st.write("Existing sidebar")
chat_interface.render_chat_interface()
with st.expander("Browser test controls"):
    if st.button("Lose next confirmation response"):
        client().lose_response_once = True
    if client().lose_response_once:
        st.caption("Next confirmation response will be lost")
    if st.button("Pause next handoff"):
        client().pause_handoff_once = True
    if client().pause_handoff_once:
        st.caption("Next handoff will pause before planning")
    if st.button("Reject next submission"):
        client().reject_once = True
    if client().reject_once:
        st.caption("Next submission will be rejected")
    if st.button("Simulate TOF dependency"):
        try:
            client().store.check_module(
                st.session_state.thread_id, "eval_elast", {"bTOF": True}
            )
        except PipelineInvalid:
            st.rerun()
