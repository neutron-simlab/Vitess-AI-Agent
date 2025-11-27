"""
Streamlit UI for Vitess AI Supervisor Agent

This Streamlit application provides a web interface for interacting with the
Vitess AI supervisor agent through the FastAPI service.
"""
import streamlit as st
from uuid import uuid4
from pathlib import Path
import sys

# Add parent directory to path to import vitess_ai modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitess_ai.schema.llm_models import Provider, OpenAIModelName

# Import UI modules
from sidebar import render_sidebar
from chat_interface import render_chat_interface
from file_management import check_server_health, initialize_client

# Paths and assets
_assets_dir = Path(__file__).parent / "assets"
_logo_path = _assets_dir / "logo.png"

# Page configuration
st.set_page_config(
    page_title="Vitess AI Agent Chatbot",
    page_icon=str(_logo_path) if _logo_path.exists() else None,
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid4())

if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid4())

if "server_url" not in st.session_state:
    st.session_state.server_url = "http://localhost:8000"

if "client" not in st.session_state:
    st.session_state.client = None

if "current_interrupt" not in st.session_state:
    st.session_state.current_interrupt = None

if "server_connected" not in st.session_state:
    st.session_state.server_connected = False

if "show_system_messages" not in st.session_state:
    st.session_state.show_system_messages = False

if "selected_provider" not in st.session_state:
    st.session_state.selected_provider = Provider.OPENAI.value

if "selected_model" not in st.session_state:
    st.session_state.selected_model = OpenAIModelName.GPT_4O_MINI.value

if "provider_change_pending" not in st.session_state:
    st.session_state.provider_change_pending = False

if "pending_provider" not in st.session_state:
    st.session_state.pending_provider = None

if "pending_model" not in st.session_state:
    st.session_state.pending_model = None

if "uploaded_files" not in st.session_state:
    st.session_state.uploaded_files = {}  # {module_type: [file_metadata]}

if "selected_upload_module" not in st.session_state:
    st.session_state.selected_upload_module = "readin"

# Auto-connect to server on app load (only check once per session)
if not hasattr(st.session_state, '_health_checked'):
    st.session_state.server_connected = check_server_health(st.session_state.server_url)
    if st.session_state.server_connected:
        st.session_state.client = initialize_client(st.session_state.server_url)
        if st.session_state.client is None:
            st.session_state.server_connected = False
    else:
        st.session_state.client = None
    st.session_state._health_checked = True

# Render sidebar
render_sidebar()

# Render main chat interface
render_chat_interface()
