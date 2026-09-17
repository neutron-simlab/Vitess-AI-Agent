"""The VITESS AI Agent web interface.

Deliberately shorter than juena-chatbot's equivalent, and every line that is
missing is missing for a reason: there is no sign-in, because this deployment
has one fixed local user, and no session cookie to carry. Identity is injected
at the API as `local_principal`, exactly where an institute login's dependency
would go.

What this file owns is session state: which agent, which conversation, which
model. Everything it draws is in `sidebar` and `chat_interface`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from juena_core.llms_providers import get_available_providers, get_default_model  # noqa: E402
from juena_core.schema.llm_models import Provider  # noqa: E402
from juena_core.ui.chat_storage import get_chat_storage  # noqa: E402
from juena_core.ui.client_setup import initialize_client  # noqa: E402

from app.chat_interface import render_chat_interface  # noqa: E402
from app.sidebar import AGENTS, render_sidebar  # noqa: E402
from app.session_state import adopt_thread_agent  # noqa: E402
from app.ui_components import logo_path  # noqa: E402
from vitess_ai.clients import VitessClient  # noqa: E402
from vitess_ai.config import Config  # noqa: E402

API_URL = f"http://{Config.BIND_HOST}:{Config.API_PORT}"

st.set_page_config(
    page_title="VITESS AI Agent",
    page_icon=str(logo_path()) if logo_path() else "⚛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "selected_agent" not in st.session_state:
    st.session_state.selected_agent = next(iter(AGENTS))
if "show_system_messages" not in st.session_state:
    st.session_state.show_system_messages = False
if "messages" not in st.session_state:
    st.session_state.messages = []

# The active conversation lives in the URL as well as in session state: session
# state is per-Streamlit-session, so a browser reload would otherwise start a
# brand new thread every time.
if "thread_id" not in st.session_state:
    st.session_state.thread_id = st.query_params.get("thread") or str(uuid4())

if "selected_provider" not in st.session_state:
    available = get_available_providers()
    providers = [item.value for item in Provider if available.get(item.value, False)]
    st.session_state.selected_provider = (
        Config.DEFAULT_PROVIDER.lower()
        if Config.DEFAULT_PROVIDER.lower() in providers
        else (providers[0] if providers else Provider.OPENAI.value)
    )
if "selected_model" not in st.session_state:
    st.session_state.selected_model = (
        get_default_model(st.session_state.selected_provider) or Config.DEFAULT_MODEL
    )

# One client per agent: `agent_id` is part of the stream URL, and switching
# modes has to switch which registered graph the next message reaches.
client = st.session_state.get("client")
if client is None or client.agent != st.session_state.selected_agent:
    if client is not None:
        client.close()
    client = initialize_client(
        API_URL,
        agent_id=st.session_state.selected_agent,
        timeout=float(Config.TIMEOUT_SECONDS),
        client_class=VitessClient,
    )
    st.session_state.client = client
    st.session_state.chat_storage = get_chat_storage(client)

if not client.health():
    st.error(
        "The VITESS service is not answering. If you started the stack just now, "
        "give it a moment; otherwise check `vitess logs`."
    )
    st.stop()

# Resume the thread named in the URL, if there is one. A thread with no row yet
# is simply an unsent conversation -- the row is created server side by the
# first message, so reloading an empty chat leaves no stray entry behind.
if "chat_initialized" not in st.session_state:
    loaded = st.session_state.chat_storage.load_chat_with_messages(
        st.session_state.thread_id
    )
    if loaded is not None:
        chat, st.session_state.messages = loaded
        if adopt_thread_agent(
            st.session_state,
            chat.agent_id,
            known_agents=set(AGENTS),
        ):
            # The client above was built for the previously selected agent.
            # Re-enter from the top so no request can reach the wrong graph.
            st.session_state.chat_initialized = True
            st.rerun()
    st.session_state.chat_initialized = True

if st.query_params.get("thread") != st.session_state.thread_id:
    st.query_params["thread"] = st.session_state.thread_id

render_sidebar(client)
render_chat_interface()
