"""
Sidebar configuration UI for Streamlit app.

This module provides the sidebar UI for server configuration, LLM settings,
Vitess environment configuration, thread management, and file uploads.
"""
import streamlit as st
import httpx
from uuid import uuid4
from pathlib import Path
from io import BytesIO

from vitess_ai.schema.llm_models import Provider, OpenAIModelName, BlabladorModelName
from file_management import (
    check_server_health,
    initialize_client,
    upload_file_to_server,
    delete_file_from_server,
    load_uploaded_files,
    get_active_module_from_messages,
    save_path_metadata_to_server
)

# Paths and assets
_assets_dir = Path(__file__).parent / "assets"
_logo_path = _assets_dir / "logo.png"


def render_sidebar() -> None:
    """Render the sidebar with all configuration options."""
    with st.sidebar:
        if _logo_path.exists():
            st.image(str(_logo_path), use_container_width=True)
        st.title("Vitess AI Agent Chatbot")
        st.divider()

        # 1. LLM Configuration
        with st.expander("LLM Configuration", expanded=False):
            # Show confirmation dialog if provider change is pending
            if st.session_state.provider_change_pending and st.session_state.pending_provider:
                st.warning(
                    f"**Provider Change Pending**\n\n"
                    f"You selected **{st.session_state.pending_provider}** as the provider.\n\n"
                    f"This will regenerate the agent graph with the new LLM. "
                    f"Your current conversation will continue with the new model.\n\n"
                    f"**Model**: {st.session_state.pending_model or ('alias-function-call' if st.session_state.pending_provider == Provider.BLABLADOR.value else 'gpt-4o-mini')}"
                )
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Confirm", use_container_width=True, type="primary"):
                        # Apply the provider change
                        st.session_state.selected_provider = st.session_state.pending_provider
                        if st.session_state.pending_model:
                            st.session_state.selected_model = st.session_state.pending_model
                        elif st.session_state.pending_provider == Provider.BLABLADOR.value:
                            st.session_state.selected_model = BlabladorModelName.ALIAS_FUNCTION_CALL.value
                        else:
                            st.session_state.selected_model = OpenAIModelName.GPT_4O_MINI.value
                        
                        # Clear pending state
                        st.session_state.provider_change_pending = False
                        st.session_state.pending_provider = None
                        st.session_state.pending_model = None
                        
                        # Restart the graph with new provider/model if server is connected
                        if st.session_state.server_connected and st.session_state.client:
                            try:
                                st.session_state.client.restart(
                                    provider=st.session_state.selected_provider,
                                    model=st.session_state.selected_model
                                )
                                # Clear conversation state for fresh start
                                st.session_state.thread_id = str(uuid4())
                                st.session_state.user_id = str(uuid4())
                                st.session_state.messages = []
                                st.session_state.current_interrupt = None
                                st.session_state.welcome_initialized = False
                                st.success(f"Switched to **{st.session_state.selected_provider}** with model **{st.session_state.selected_model}**. Graph restarted and conversation cleared for fresh start!")
                            except Exception as e:
                                st.warning(f"Provider/model changed, but graph restart failed: {e}. Graph will regenerate on next request.")
                        else:
                            st.success(f"Switched to **{st.session_state.selected_provider}** with model **{st.session_state.selected_model}**. Graph will regenerate on next request.")
                        st.rerun()
                
                with col2:
                    if st.button("Cancel", use_container_width=True):
                        # Cancel the change
                        st.session_state.provider_change_pending = False
                        st.session_state.pending_provider = None
                        st.session_state.pending_model = None
                        st.rerun()
                
                st.divider()
                # Show current provider (not pending one) while confirmation is pending
                st.info(f"**Current Provider**: {st.session_state.selected_provider}")
            else:
                # Provider selector (only show when not pending confirmation)
                provider_options = [Provider.OPENAI.value, Provider.BLABLADOR.value]
                selected_provider = st.radio(
                    "Provider",
                    options=provider_options,
                    index=provider_options.index(st.session_state.selected_provider) if st.session_state.selected_provider in provider_options else 0,  # Default to OpenAI (index 0)
                    help="Select the LLM provider to use"
                )
                
                # Handle provider change - require confirmation for Blablador
                if selected_provider != st.session_state.selected_provider:
                    if selected_provider == Provider.BLABLADOR.value:
                        # For Blablador, require confirmation
                        st.session_state.provider_change_pending = True
                        st.session_state.pending_provider = selected_provider
                        st.session_state.pending_model = BlabladorModelName.ALIAS_FUNCTION_CALL.value
                        st.rerun()
                    else:
                        # For OpenAI, apply immediately
                        st.session_state.selected_provider = selected_provider
                        st.session_state.selected_model = OpenAIModelName.GPT_4O_MINI.value
                        
                        # Restart the graph with new provider/model if server is connected
                        if st.session_state.server_connected and st.session_state.client:
                            try:
                                st.session_state.client.restart(
                                    provider=st.session_state.selected_provider,
                                    model=st.session_state.selected_model
                                )
                                # Clear conversation state for fresh start
                                st.session_state.thread_id = str(uuid4())
                                st.session_state.user_id = str(uuid4())
                                st.session_state.messages = []
                                st.session_state.current_interrupt = None
                                st.session_state.welcome_initialized = False
                                st.info("Switched to OpenAI. Graph restarted and conversation cleared for fresh start!")
                            except Exception as e:
                                st.warning(f"Provider/model changed, but graph restart failed: {e}. Graph will regenerate on next request.")
                        else:
                            st.info("Switched to OpenAI. Graph will regenerate on next request.")
                
                # Model selector based on provider
                if st.session_state.selected_provider == Provider.OPENAI.value:
                    model_options = [model.value for model in OpenAIModelName]
                    # Ensure selected model is valid for current provider
                    if st.session_state.selected_model not in model_options:
                        st.session_state.selected_model = OpenAIModelName.GPT_4O_MINI.value
                    selected_model = st.selectbox(
                        "Model",
                        options=model_options,
                        index=model_options.index(st.session_state.selected_model) if st.session_state.selected_model in model_options else 0,
                        help="Select the OpenAI model to use"
                    )
                else:  # Blablador
                    model_options = [model.value for model in BlabladorModelName]
                    # Ensure selected model is valid for current provider, or auto-select alias-function-call
                    if st.session_state.selected_model not in model_options:
                        st.session_state.selected_model = BlabladorModelName.ALIAS_FUNCTION_CALL.value
                    selected_model = st.selectbox(
                        "Model",
                        options=model_options,
                        index=model_options.index(st.session_state.selected_model) if st.session_state.selected_model in model_options else 0,
                        help="Select the Blablador model to use (defaults to alias-function-call)"
                    )
                
                # Update model if changed
                if selected_model != st.session_state.selected_model:
                    st.session_state.selected_model = selected_model
                    
                    # Restart the graph with new model if server is connected
                    if st.session_state.server_connected and st.session_state.client:
                        try:
                            st.session_state.client.restart(
                                provider=st.session_state.selected_provider,
                                model=st.session_state.selected_model
                            )
                            # Clear conversation state for fresh start
                            st.session_state.thread_id = str(uuid4())
                            st.session_state.user_id = str(uuid4())
                            st.session_state.messages = []
                            st.session_state.current_interrupt = None
                            st.session_state.welcome_initialized = False
                            st.info(f"Model changed to **{selected_model}**. Graph restarted and conversation cleared for fresh start!")
                        except Exception as e:
                            st.warning(f"Model changed, but graph restart failed: {e}. Graph will regenerate on next request.")
                    else:
                        st.info(f"Model changed to **{selected_model}**. Graph will regenerate with the new model on next request.")

        # 2. Vitess Environment Configuration
        with st.expander("Vitess Environment", expanded=False):
            if st.session_state.server_connected:
                # Initialize Vitess config in session state if not present
                if "vitess_config" not in st.session_state:
                    st.session_state.vitess_config = {
                        "modules_path": "/usr/local/vitess/bin",
                        "project_path": "/tmp/vitess_project",
                        "log_path": "/tmp/vitess_logs"
                    }
                
                # Load current config from server (only once per session)
                if "vitess_config_loaded" not in st.session_state:
                    try:
                        response = httpx.get(
                            f"{st.session_state.server_url}/config/vitess",
                            timeout=5.0
                        )
                        if response.status_code == 200:
                            config_data = response.json().get("config", {})
                            st.session_state.vitess_config = {
                                "modules_path": config_data.get("VITESS_MODULES_PATH", st.session_state.vitess_config["modules_path"]),
                                "project_path": config_data.get("VITESS_PROJECT_PATH", st.session_state.vitess_config["project_path"]),
                                "log_path": config_data.get("VITESS_LOG_PATH", st.session_state.vitess_config["log_path"])
                            }
                            st.session_state.vitess_config_loaded = True
                    except Exception as e:
                        st.warning(f"Could not load Vitess config from server: {e}")
                        st.session_state.vitess_config_loaded = True  # Mark as attempted to avoid repeated warnings
                
                # Configuration inputs
                modules_path = st.text_input(
                    "Vitess Modules Path (V)",
                    value=st.session_state.vitess_config["modules_path"],
                    help="Path to Vitess binary modules (default: /usr/local/vitess/bin)",
                    key="vitess_modules_path"
                )
                
                project_path = st.text_input(
                    "Vitess Project Path (P)",
                    value=st.session_state.vitess_config["project_path"],
                    help="Path to Vitess project directory for simulations (default: /tmp/vitess_project)",
                    key="vitess_project_path"
                )
                
                log_path = st.text_input(
                    "Vitess Log Path (L)",
                    value=st.session_state.vitess_config["log_path"],
                    help="Path to Vitess log directory (default: /tmp/vitess_logs)",
                    key="vitess_log_path"
                )
                
                # Update button
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Save Config", use_container_width=True):
                        try:
                            response = httpx.put(
                                f"{st.session_state.server_url}/config/vitess",
                                params={
                                    "modules_path": modules_path,
                                    "project_path": project_path,
                                    "log_path": log_path
                                },
                                timeout=10.0
                            )
                            response.raise_for_status()
                            result = response.json()
                            
                            # Update session state
                            st.session_state.vitess_config = {
                                "modules_path": modules_path,
                                "project_path": project_path,
                                "log_path": log_path
                            }
                            
                            st.success("Vitess configuration saved!")
                        except Exception as e:
                            st.error(f"Failed to save Vitess config: {e}")
                
                with col2:
                    if st.button("Reset to Defaults", use_container_width=True):
                        try:
                            response = httpx.post(
                                f"{st.session_state.server_url}/config/vitess/reset",
                                timeout=10.0
                            )
                            response.raise_for_status()
                            result = response.json()
                            config_data = result.get("config", {})
                            
                            # Update session state with defaults
                            st.session_state.vitess_config = {
                                "modules_path": config_data.get("VITESS_MODULES_PATH", "/usr/local/vitess/bin"),
                                "project_path": config_data.get("VITESS_PROJECT_PATH", "/tmp/vitess_project"),
                                "log_path": config_data.get("VITESS_LOG_PATH", "/tmp/vitess_logs")
                            }
                            
                            st.success("Vitess configuration reset to defaults!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to reset Vitess config: {e}")
                
                # Display current configuration
                with st.expander("Current Configuration", expanded=False):
                    st.json({
                        "V (Modules)": st.session_state.vitess_config["modules_path"],
                        "P (Project)": st.session_state.vitess_config["project_path"],
                        "L (Logs)": st.session_state.vitess_config["log_path"]
                    })
            else:
                st.info("Connect to server to configure Vitess environment")

        # 3. File Upload Section
        with st.expander("File Upload", expanded=False):
            if st.session_state.server_connected:
                # Load uploaded files for this thread
                if st.session_state.thread_id:
                    uploaded_files_by_module = load_uploaded_files(
                        st.session_state.thread_id,
                        st.session_state.server_url
                    )
                    st.session_state.uploaded_files = uploaded_files_by_module
                
                # Detect active module from chat messages
                active_module = get_active_module_from_messages(st.session_state.messages)
                
                # Module selection with dropdown menu
                module_options = {
                    "readin": "Read-in Module",
                    "guide": "Guide Module",
                    "monitor1d": "Monitor1D Module",
                    "monitor2d": "Monitor2D Module",
                    "instrument": "Instrument Module",
                    "writeout": "Writeout Module"
                }
                
                # If there's an active module, show it; otherwise let user select
                if active_module and active_module in module_options:
                    # Auto-select the active module
                    if st.session_state.selected_upload_module != active_module:
                        st.session_state.selected_upload_module = active_module
                        st.rerun()
                    selected_module = active_module
                    st.info(f"Active Module: **{module_options[active_module]}** (upload enabled)")
                else:
                    # No active module - allow user to select
                    selected_module = st.selectbox(
                        "Select Module",
                        options=list(module_options.keys()),
                        format_func=lambda x: module_options[x],
                        index=list(module_options.keys()).index(st.session_state.selected_upload_module) if st.session_state.selected_upload_module in module_options else 0,
                        key="module_selector",
                        help="Select the module to upload files for"
                    )
                    
                    if selected_module != st.session_state.selected_upload_module:
                        st.session_state.selected_upload_module = selected_module
                        st.rerun()
                    
                    if active_module is None:
                        st.info("No module is currently active. You can still upload files for any module.")
                
                st.divider()
                
                # Determine if upload should be enabled for this module
                is_module_active = (active_module == selected_module) if active_module else False
                
                # Show upload UI based on selected module
                _render_file_upload_ui(selected_module, is_module_active)
                
                # Summary of all uploaded files
                st.divider()
                st.markdown("**Summary of All Uploaded Files**")
                total_files = sum(len(files) for files in st.session_state.uploaded_files.values())
                if total_files > 0:
                    summary_cols = st.columns(6)
                    with summary_cols[0]:
                        readin_count = len(st.session_state.uploaded_files.get("readin", []))
                        st.metric("Read-in", readin_count, help="Number of read-in files")
                    with summary_cols[1]:
                        guide_count = len(st.session_state.uploaded_files.get("guide", []))
                        st.metric("Guide", guide_count, help="Number of guide files")
                    with summary_cols[2]:
                        monitor1d_count = len(st.session_state.uploaded_files.get("monitor1d", []))
                        st.metric("Monitor1D", monitor1d_count, help="Number of Monitor1D files")
                    with summary_cols[3]:
                        monitor2d_count = len(st.session_state.uploaded_files.get("monitor2d", []))
                        st.metric("Monitor2D", monitor2d_count, help="Number of Monitor2D files")
                    with summary_cols[4]:
                        instrument_count = len(st.session_state.uploaded_files.get("instrument", []))
                        st.metric("Instrument", instrument_count, help="Number of instrument files")
                    with summary_cols[5]:
                        writeout_count = len(st.session_state.uploaded_files.get("writeout", []))
                        st.metric("Writeout", writeout_count, help="Number of writeout paths")
                else:
                    st.info("No files uploaded yet for this thread.")
            else:
                st.info("Connect to server to upload files")

        # Server Configuration
        with st.expander("Server Configuration", expanded=False):
            server_url_input = st.text_input(
                "Server URL",
                value=st.session_state.server_url,
                help="FastAPI server URL (default: http://localhost:8000)"
            )

            if server_url_input != st.session_state.server_url:
                st.session_state.server_url = server_url_input
                st.session_state.client = None
                st.session_state.server_connected = False
                st.session_state._health_checked = False

            # Health Check
            if st.button("Check Server Status", use_container_width=True):
                st.session_state.server_connected = check_server_health(st.session_state.server_url)
                if st.session_state.server_connected:
                    st.session_state.client = initialize_client(st.session_state.server_url)
                    if st.session_state.client is None:
                        st.session_state.server_connected = False
                else:
                    st.session_state.client = None

            # Auto-check on load (only if not already checked)
            if st.session_state.client is None:
                # Only check if we haven't initialized or if server was previously disconnected
                if not hasattr(st.session_state, '_health_checked'):
                    st.session_state.server_connected = check_server_health(st.session_state.server_url)
                    st.session_state._health_checked = True
                    if st.session_state.server_connected:
                        st.session_state.client = initialize_client(st.session_state.server_url)
                        if st.session_state.client is None:
                            st.session_state.server_connected = False

            # Display connection status
            if st.session_state.server_connected:
                st.success("Server Connected")
            else:
                st.error("Server Disconnected")
                st.info(
                    """
                    **Server not running. Please start the server:**
                    ```bash
                    python main.py
                    ```
                    Server should run on `http://localhost:8000`
                    """
                )

        # Thread Management
        with st.expander("Thread Management", expanded=False):
            st.text(f"Thread ID: {st.session_state.thread_id[:8]}...")
            st.text(f"User ID: {st.session_state.user_id[:8]}...")

            if st.button("New Thread", use_container_width=True):
                st.session_state.thread_id = str(uuid4())
                st.session_state.user_id = str(uuid4())
                st.session_state.messages = []
                st.session_state.current_interrupt = None
                st.rerun()

            if st.button("Clear Chat", use_container_width=True):
                st.session_state.messages = []
                st.session_state.current_interrupt = None
                st.rerun()

        # Debug Options
        with st.expander("Debug Options", expanded=False):
            show_system = st.checkbox(
                "Show System Messages",
                value=st.session_state.show_system_messages,
                help="Show internal system messages (for debugging)"
            )
            if show_system != st.session_state.show_system_messages:
                st.session_state.show_system_messages = show_system
                st.rerun()

        # Information
        with st.expander("About", expanded=False):
            st.info(
                """
                **Vitess AI Supervisor** helps configure neutron simulation
                parameters through an interactive chat interface.
                
                The system guides you through:
                - Read-in parameters
                - Guide configuration
                - Monitor1D and Monitor2D parameters
                - Writeout settings
                - Simulation execution
                """
            )


def _render_file_upload_ui(selected_module: str, is_module_active: bool) -> None:
    """Render file upload UI for the selected module."""
    if selected_module == "readin":
        st.markdown("**Read-in Module Files** (max 3 files)")
        
        if not is_module_active:
            st.warning("Read-in module is not currently active. Upload files when the Read-in module is being configured.")
        
        readin_files = st.file_uploader(
            "Browse input files",
            type=["dat", "txt", "csv", "nxs", "h5"],
            accept_multiple_files=True,
            key="readin_uploader",
            help="Select up to 3 input files for neutron simulation",
            disabled=not is_module_active
        )
        
        # Get existing files before processing uploads
        existing_readin = st.session_state.uploaded_files.get("readin", [])
        existing_filenames = {f.get("filename") for f in existing_readin}
        
        # Initialize session state for pending files
        if "pending_readin_files" not in st.session_state:
            st.session_state.pending_readin_files = []
        
        # Store selected files in session state (read bytes before they're consumed)
        if readin_files:
            # Store file data in session state
            pending_files_data = []
            for f in readin_files:
                if f.name not in existing_filenames:
                    # Read file bytes and store
                    file_bytes = f.read()
                    pending_files_data.append({
                        "name": f.name,
                        "bytes": file_bytes,
                        "size": len(file_bytes)
                    })
            
            if pending_files_data:
                st.session_state.pending_readin_files = pending_files_data
            else:
                st.info("All selected files are already uploaded.")
                st.session_state.pending_readin_files = []
        else:
            # Clear pending files if file selection is cleared
            if st.session_state.pending_readin_files:
                st.session_state.pending_readin_files = []
        
        # Show pending files and upload button
        if st.session_state.pending_readin_files:
            current_count = len(existing_readin)
            remaining_slots = 3 - current_count
            
            if remaining_slots <= 0:
                st.warning(f"Maximum 3 files allowed. You already have {current_count} files uploaded. Please delete some files before uploading new ones.")
                st.session_state.pending_readin_files = []
            else:
                # Show files to be uploaded
                st.markdown("**Selected files to upload:**")
                files_to_upload = st.session_state.pending_readin_files[:remaining_slots]
                for file_data in files_to_upload:
                    st.text(f"  • {file_data['name']} ({file_data['size']:,} bytes)")
                
                if len(st.session_state.pending_readin_files) > remaining_slots:
                    st.warning(f"Only the first {remaining_slots} of {len(st.session_state.pending_readin_files)} files will be uploaded.")
                
                # Upload button
                if st.button("Upload Files", key="upload_readin_files", use_container_width=True, disabled=not is_module_active):
                    uploaded_count = 0
                    for file_data in files_to_upload:
                        file_bytes = BytesIO(file_data["bytes"])
                        result = upload_file_to_server(
                            file_bytes,
                            file_data["name"],
                            st.session_state.thread_id,
                            "readin",
                            st.session_state.server_url
                        )
                        if result and result.get("status") == "success":
                            uploaded_count += 1
                    
                    if uploaded_count > 0:
                        st.success(f"Successfully uploaded {uploaded_count} file(s)")
                        # Clear pending files
                        st.session_state.pending_readin_files = []
                        # Reload files from server and rerun
                        uploaded_files_by_module = load_uploaded_files(
                            st.session_state.thread_id,
                            st.session_state.server_url
                        )
                        st.session_state.uploaded_files = uploaded_files_by_module
                        st.rerun()
        
        # Display uploaded readin files
        readin_list = st.session_state.uploaded_files.get("readin", [])
        if readin_list:
            st.markdown(f"**Uploaded Read-in Files:** ({len(readin_list)} file(s))")
            for file_meta in readin_list:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.text(f"{file_meta.get('filename', 'unknown')} ({file_meta.get('file_size', 0):,} bytes)")
                with col2:
                    if st.button("Delete", key=f"delete_readin_{file_meta.get('file_id')}"):
                        if delete_file_from_server(
                            file_meta.get("file_id"),
                            st.session_state.thread_id,
                            "readin",
                            st.session_state.server_url
                        ):
                            # Reload files from server after deletion
                            uploaded_files_by_module = load_uploaded_files(
                                st.session_state.thread_id,
                                st.session_state.server_url
                            )
                            st.session_state.uploaded_files = uploaded_files_by_module
                            st.rerun()
        else:
            st.info("No files uploaded yet. Upload files above.")
    
    elif selected_module == "guide":
        st.markdown("**Guide Module File** (single file)")
        
        if not is_module_active:
            st.warning("Guide module is not currently active. Upload files when the Guide module is being configured.")
        
        guide_file = st.file_uploader(
            "Browse guide file",
            type=["dat", "txt", "csv", "nxs", "h5"],
            accept_multiple_files=False,
            key="guide_uploader",
            help="Select guide input file for neutron simulation",
            disabled=not is_module_active
        )
        
        # Get existing files before processing upload
        existing_guide = st.session_state.uploaded_files.get("guide", [])
        existing_filenames = {f.get("filename") for f in existing_guide}
        
        # Initialize session state for pending file
        if "pending_guide_file" not in st.session_state:
            st.session_state.pending_guide_file = None
        
        # Store selected file in session state
        if guide_file is not None:
            # Check if file already exists
            if guide_file.name in existing_filenames:
                st.info(f"File '{guide_file.name}' is already uploaded.")
                st.session_state.pending_guide_file = None
            else:
                # Check if we already have a guide file (single file limit)
                if len(existing_guide) > 0:
                    st.warning("Guide module allows only one file. Please delete the existing file before uploading a new one.")
                    st.session_state.pending_guide_file = None
                else:
                    # Read file bytes and store
                    file_bytes = guide_file.read()
                    st.session_state.pending_guide_file = {
                        "name": guide_file.name,
                        "bytes": file_bytes,
                        "size": len(file_bytes)
                    }
        else:
            # Clear pending file if file selection is cleared
            if st.session_state.pending_guide_file:
                st.session_state.pending_guide_file = None
        
        # Show pending file and upload button
        if st.session_state.pending_guide_file:
            file_data = st.session_state.pending_guide_file
            st.markdown("**Selected file to upload:**")
            st.text(f"  • {file_data['name']} ({file_data['size']:,} bytes)")
            
            # Upload button
            if st.button("Upload File", key="upload_guide_file", use_container_width=True, disabled=not is_module_active):
                file_bytes = BytesIO(file_data["bytes"])
                result = upload_file_to_server(
                    file_bytes,
                    file_data["name"],
                    st.session_state.thread_id,
                    "guide",
                    st.session_state.server_url
                )
                if result and result.get("status") == "success":
                    st.success(f"Uploaded: {file_data['name']}")
                    # Clear pending file
                    st.session_state.pending_guide_file = None
                    # Reload files from server and rerun
                    uploaded_files_by_module = load_uploaded_files(
                        st.session_state.thread_id,
                        st.session_state.server_url
                    )
                    st.session_state.uploaded_files = uploaded_files_by_module
                    st.rerun()
        
        # Display uploaded guide file
        guide_list = st.session_state.uploaded_files.get("guide", [])
        if guide_list:
            st.markdown(f"**Uploaded Guide File:** ({len(guide_list)} file(s))")
            for file_meta in guide_list:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.text(f"{file_meta.get('filename', 'unknown')} ({file_meta.get('file_size', 0):,} bytes)")
                with col2:
                    if st.button("Delete", key=f"delete_guide_{file_meta.get('file_id')}"):
                        if delete_file_from_server(
                            file_meta.get("file_id"),
                            st.session_state.thread_id,
                            "guide",
                            st.session_state.server_url
                        ):
                            # Reload files from server after deletion
                            uploaded_files_by_module = load_uploaded_files(
                                st.session_state.thread_id,
                                st.session_state.server_url
                            )
                            st.session_state.uploaded_files = uploaded_files_by_module
                            st.rerun()
        else:
            st.info("No file uploaded yet. Upload a file above.")
    
    elif selected_module == "instrument":
        st.markdown("**Instrument File** (.inf)")
        
        if not is_module_active:
            st.warning("Instrument module is not currently active. Upload files when the Instrument module is being configured.")
        
        instrument_file = st.file_uploader(
            "Browse instrument file",
            type=["inf", "dat", "txt"],
            accept_multiple_files=False,
            key="instrument_uploader",
            help="Select instrument file (.inf) for neutron simulation",
            disabled=not is_module_active
        )
        
        # Get existing files before processing upload
        existing_instrument = st.session_state.uploaded_files.get("instrument", [])
        existing_filenames = {f.get("filename") for f in existing_instrument}
        
        # Initialize session state for pending file
        if "pending_instrument_file" not in st.session_state:
            st.session_state.pending_instrument_file = None
        
        # Store selected file in session state
        if instrument_file is not None:
            # Check if file already exists
            if instrument_file.name in existing_filenames:
                st.info(f"File '{instrument_file.name}' is already uploaded.")
                st.session_state.pending_instrument_file = None
            else:
                # Check if we already have an instrument file (single file limit)
                if len(existing_instrument) > 0:
                    st.warning("Instrument module allows only one file. Please delete the existing file before uploading a new one.")
                    st.session_state.pending_instrument_file = None
                else:
                    # Read file bytes and store
                    file_bytes = instrument_file.read()
                    st.session_state.pending_instrument_file = {
                        "name": instrument_file.name,
                        "bytes": file_bytes,
                        "size": len(file_bytes)
                    }
        else:
            # Clear pending file if file selection is cleared
            if st.session_state.pending_instrument_file:
                st.session_state.pending_instrument_file = None
        
        # Show pending file and upload button
        if st.session_state.pending_instrument_file:
            file_data = st.session_state.pending_instrument_file
            st.markdown("**Selected file to upload:**")
            st.text(f"  • {file_data['name']} ({file_data['size']:,} bytes)")
            
            # Upload button
            if st.button("Upload File", key="upload_instrument_file", use_container_width=True, disabled=not is_module_active):
                file_bytes = BytesIO(file_data["bytes"])
                result = upload_file_to_server(
                    file_bytes,
                    file_data["name"],
                    st.session_state.thread_id,
                    "instrument",
                    st.session_state.server_url
                )
                if result and result.get("status") == "success":
                    st.success(f"Uploaded: {file_data['name']}")
                    # Clear pending file
                    st.session_state.pending_instrument_file = None
                    # Reload files from server and rerun
                    uploaded_files_by_module = load_uploaded_files(
                        st.session_state.thread_id,
                        st.session_state.server_url
                    )
                    st.session_state.uploaded_files = uploaded_files_by_module
                    st.rerun()
        
        # Display uploaded instrument file
        instrument_list = st.session_state.uploaded_files.get("instrument", [])
        if instrument_list:
            st.markdown(f"**Uploaded Instrument File:** ({len(instrument_list)} file(s))")
            for file_meta in instrument_list:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.text(f"{file_meta.get('filename', 'unknown')} ({file_meta.get('file_size', 0):,} bytes)")
                with col2:
                    if st.button("Delete", key=f"delete_instrument_{file_meta.get('file_id')}"):
                        if delete_file_from_server(
                            file_meta.get("file_id"),
                            st.session_state.thread_id,
                            "instrument",
                            st.session_state.server_url
                        ):
                            # Reload files from server after deletion
                            uploaded_files_by_module = load_uploaded_files(
                                st.session_state.thread_id,
                                st.session_state.server_url
                            )
                            st.session_state.uploaded_files = uploaded_files_by_module
                            st.rerun()
        else:
            st.info("No file uploaded yet. Upload a file above.")
    
    elif selected_module == "monitor1d":
        st.markdown("**Monitor1D Output File Path**")
        
        if not is_module_active:
            st.warning("Monitor1D module is not currently active. Configure output file path when the Monitor1D module is being configured.")
        
        # Calculate default path: root/{thread_id}/outputs/monitor1D.dat
        default_path = ""
        if st.session_state.get("thread_id") and st.session_state.get("vitess_config"):
            project_path = st.session_state.vitess_config.get("project_path", "/tmp/vitess_project")
            thread_id = st.session_state.thread_id
            default_path = f"{project_path}/{thread_id}/outputs/monitor1D.dat"
        elif st.session_state.get("thread_id"):
            # Fallback if vitess_config not loaded yet
            thread_id = st.session_state.thread_id
            default_path = f"/tmp/vitess_project/{thread_id}/outputs/monitor1D.dat"
        
        # Get current monitor1d path or use default
        current_path = st.session_state.get("monitor1d_path", default_path)
        
        monitor1d_path = st.text_input(
            "Monitor1D output file path",
            value=current_path,
            key="monitor1d_path_input",
            help=f"Default location: {default_path} (automatically set if left empty). Enter a custom path if you want a different location.",
            disabled=not is_module_active,
            placeholder=default_path if default_path else "Enter monitor1D output file path..."
        )
        
        # Show default path info
        if default_path:
            st.info(f"**Default location:** `{default_path}`\n\nThis path will be used automatically if you don't specify a custom location.")
        
        if monitor1d_path:
            st.session_state.monitor1d_path = monitor1d_path
            # Save to file storage as metadata
            if st.button("Save Path", key="save_monitor1d_path", use_container_width=True, disabled=not is_module_active):
                # Save path as metadata to server
                result = save_path_metadata_to_server(
                    monitor1d_path,
                    st.session_state.thread_id,
                    "monitor1d",
                    st.session_state.server_url
                )
                if result and result.get("status") == "success":
                    st.success(f"Monitor1D output path saved: {monitor1d_path}")
                    # Reload files from server
                    uploaded_files_by_module = load_uploaded_files(
                        st.session_state.thread_id,
                        st.session_state.server_url
                    )
                    st.session_state.uploaded_files = uploaded_files_by_module
                    st.rerun()
                else:
                    st.error("Failed to save path. Please try again.")
        
        # Display saved monitor1d path
        monitor1d_list = st.session_state.uploaded_files.get("monitor1d", [])
        if monitor1d_list:
            st.markdown("**Saved Monitor1D Output Path:**")
            for file_meta in monitor1d_list:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.text(f"{file_meta.get('filename', file_meta.get('file_path', 'unknown'))}")
                with col2:
                    if st.button("Delete", key=f"delete_monitor1d_{file_meta.get('file_id')}"):
                        if delete_file_from_server(
                            file_meta.get("file_id"),
                            st.session_state.thread_id,
                            "monitor1d",
                            st.session_state.server_url
                        ):
                            st.rerun()
        else:
            if default_path:
                st.info(f"**Default path will be used:** `{default_path}`\n\nYou can enter a custom path above if needed.")
            else:
                st.info("No output path saved yet. Enter a path above and click 'Save Path'.")
    
    elif selected_module == "monitor2d":
        st.markdown("**Monitor2D Output File Path**")
        
        if not is_module_active:
            st.warning("Monitor2D module is not currently active. Configure output file path when the Monitor2D module is being configured.")
        
        # Calculate default path: root/{thread_id}/outputs/monitor2D.dat
        default_path = ""
        if st.session_state.get("thread_id") and st.session_state.get("vitess_config"):
            project_path = st.session_state.vitess_config.get("project_path", "/tmp/vitess_project")
            thread_id = st.session_state.thread_id
            default_path = f"{project_path}/{thread_id}/outputs/monitor2D.dat"
        elif st.session_state.get("thread_id"):
            # Fallback if vitess_config not loaded yet
            thread_id = st.session_state.thread_id
            default_path = f"/tmp/vitess_project/{thread_id}/outputs/monitor2D.dat"
        
        # Get current monitor2d path or use default
        current_path = st.session_state.get("monitor2d_path", default_path)
        
        monitor2d_path = st.text_input(
            "Monitor2D output file path",
            value=current_path,
            key="monitor2d_path_input",
            help=f"Default location: {default_path} (automatically set if left empty). Enter a custom path if you want a different location.",
            disabled=not is_module_active,
            placeholder=default_path if default_path else "Enter monitor2D output file path..."
        )
        
        # Show default path info
        if default_path:
            st.info(f"**Default location:** `{default_path}`\n\nThis path will be used automatically if you don't specify a custom location.")
        
        if monitor2d_path:
            st.session_state.monitor2d_path = monitor2d_path
            # Save to file storage as metadata
            if st.button("Save Path", key="save_monitor2d_path", use_container_width=True, disabled=not is_module_active):
                # Save path as metadata to server
                result = save_path_metadata_to_server(
                    monitor2d_path,
                    st.session_state.thread_id,
                    "monitor2d",
                    st.session_state.server_url
                )
                if result and result.get("status") == "success":
                    st.success(f"Monitor2D output path saved: {monitor2d_path}")
                    # Reload files from server
                    uploaded_files_by_module = load_uploaded_files(
                        st.session_state.thread_id,
                        st.session_state.server_url
                    )
                    st.session_state.uploaded_files = uploaded_files_by_module
                    st.rerun()
                else:
                    st.error("Failed to save path. Please try again.")
        
        # Display saved monitor2d path
        monitor2d_list = st.session_state.uploaded_files.get("monitor2d", [])
        if monitor2d_list:
            st.markdown("**Saved Monitor2D Output Path:**")
            for file_meta in monitor2d_list:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.text(f"{file_meta.get('filename', file_meta.get('file_path', 'unknown'))}")
                with col2:
                    if st.button("Delete", key=f"delete_monitor2d_{file_meta.get('file_id')}"):
                        if delete_file_from_server(
                            file_meta.get("file_id"),
                            st.session_state.thread_id,
                            "monitor2d",
                            st.session_state.server_url
                        ):
                            st.rerun()
        else:
            if default_path:
                st.info(f"**Default path will be used:** `{default_path}`\n\nYou can enter a custom path above if needed.")
            else:
                st.info("No output path saved yet. Enter a path above and click 'Save Path'.")
    
    elif selected_module == "writeout":
        st.markdown("**Writeout Save Path**")
        
        if not is_module_active:
            st.warning("Writeout module is not currently active. Configure save path when the Writeout module is being configured.")
        
        # Calculate default path: root/{thread_id}/outputs/output.out
        default_path = ""
        if st.session_state.get("thread_id") and st.session_state.get("vitess_config"):
            project_path = st.session_state.vitess_config.get("project_path", "/tmp/vitess_project")
            thread_id = st.session_state.thread_id
            default_path = f"{project_path}/{thread_id}/outputs/output.out"
        elif st.session_state.get("thread_id"):
            # Fallback if vitess_config not loaded yet
            thread_id = st.session_state.thread_id
            default_path = f"/tmp/vitess_project/{thread_id}/outputs/output.out"
        
        # Get current writeout path or use default
        current_path = st.session_state.get("writeout_path", default_path)
        
        writeout_path = st.text_input(
            "Output file path",
            value=current_path,
            key="writeout_path_input",
            help=f"Default location: {default_path} (automatically set if left empty). Enter a custom path if you want a different location.",
            disabled=not is_module_active,
            placeholder=default_path if default_path else "Enter output file path..."
        )
        
        # Show default path info
        if default_path:
            st.info(f"**Default location:** `{default_path}`\n\nThis path will be used automatically if you don't specify a custom location.")
        
        if writeout_path:
            st.session_state.writeout_path = writeout_path
            # Save to file storage as metadata
            if st.button("Save Path", key="save_writeout_path", use_container_width=True, disabled=not is_module_active):
                # Save path as metadata to server
                result = save_path_metadata_to_server(
                    writeout_path,
                    st.session_state.thread_id,
                    "writeout",
                    st.session_state.server_url
                )
                if result and result.get("status") == "success":
                    st.success(f"Output path saved: {writeout_path}")
                    # Reload files from server
                    uploaded_files_by_module = load_uploaded_files(
                        st.session_state.thread_id,
                        st.session_state.server_url
                    )
                    st.session_state.uploaded_files = uploaded_files_by_module
                    st.rerun()
                else:
                    st.error("Failed to save path. Please try again.")
        
        # Display saved writeout path
        writeout_list = st.session_state.uploaded_files.get("writeout", [])
        if writeout_list:
            st.markdown("**Saved Output Path:**")
            for file_meta in writeout_list:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.text(f"{file_meta.get('filename', file_meta.get('file_path', 'unknown'))}")
                with col2:
                    if st.button("Delete", key=f"delete_writeout_{file_meta.get('file_id')}"):
                        if delete_file_from_server(
                            file_meta.get("file_id"),
                            st.session_state.thread_id,
                            "writeout",
                            st.session_state.server_url
                        ):
                            st.rerun()
        else:
            if default_path:
                st.info(f"**Default path will be used:** `{default_path}`\n\nYou can enter a custom path above if needed.")
            else:
                st.info("No output path saved yet. Enter a path above and click 'Save Path'.")
