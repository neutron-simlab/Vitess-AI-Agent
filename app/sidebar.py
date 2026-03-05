"""
Sidebar configuration UI for Streamlit app.

This module provides the sidebar UI for server configuration, LLM settings,
Vitess environment configuration, thread management, and file uploads.
"""
import streamlit as st
import httpx
from pathlib import Path
from io import BytesIO
from typing import Any, Dict, List
from uuid import uuid4

from vitess_ai.schema.llm_models import (
    Provider,
    OpenAIModelName,
    BlabladorModelName,
    get_blablador_model_display_name,
    get_default_model_for_provider,
)
from vitess_ai.core.llms_providers import get_available_providers, get_available_models
from file_management import (
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
            st.image(str(_logo_path), width='stretch')
        st.title("Vitess AI Agent Chatbot")
        
        # Connection status indicator
        if st.session_state.server_connected:
            st.success("🟢 Server Connected")
        else:
            st.error("🔴 Server Disconnected")
        
        st.divider()

        # 1. Agent mode
        st.subheader("Agent Mode")
        mode_to_agent = {
            "Simulator": "supervisor",
            "High-Throughput": "high_throughput",
        }
        mode_options = list(mode_to_agent.keys())
        current_mode = st.session_state.get("selected_agent_mode", "Simulator")
        if current_mode not in mode_options:
            current_mode = "Simulator"

        selected_mode = st.radio(
            "Mode",
            options=mode_options,
            index=mode_options.index(current_mode),
            help="Simulator uses the deterministic supervisor flow. High-Throughput uses deep-agent orchestration.",
        )

        selected_agent_id = mode_to_agent[selected_mode]
        previous_agent_id = st.session_state.get("selected_agent_id", "supervisor")
        st.session_state.selected_agent_mode = selected_mode
        st.session_state.selected_agent_id = selected_agent_id

        if selected_agent_id != previous_agent_id:
            if st.session_state.get("client"):
                try:
                    st.session_state.client.update_agent(selected_agent_id, verify=False)
                except Exception as exc:
                    st.error(f"Failed to switch agent mode: {exc}")
            # Keep modes isolated by resetting conversation/thread context.
            st.session_state.thread_id = str(uuid4())
            st.session_state.messages = []
            st.session_state.current_turn_tasks = {}
            st.session_state.uploaded_files = {}
            st.session_state.welcome_initialized = False
            st.info(f"Switched to **{selected_mode}** mode.")
            st.rerun()

        st.checkbox(
            "Show delegated tool bodies",
            value=bool(st.session_state.get("show_delegated_tool_bodies", False)),
            key="show_delegated_tool_bodies",
            help="Debug option: render full delegated task tool payloads inline in chat.",
            disabled=selected_agent_id != "high_throughput",
        )

        st.divider()

        # 2. LLM Configuration
        st.subheader("LLM Configuration")
        
        # Get available providers dynamically (future-proof for new providers)
        available_providers = get_available_providers()
        provider_options = [p.value for p in Provider if available_providers.get(p.value, False)]
        
        # Handle edge case: No providers available
        if not provider_options:
            st.error("❌ No LLM providers are configured. Please configure at least one provider (OpenAI, Blablador, etc.) with valid API keys in your .env file.")
            return
        
        # Auto-select first available provider if current selection is unavailable
        if st.session_state.selected_provider not in provider_options:
            st.session_state.selected_provider = provider_options[0]
            # Also update model to match the new provider
            try:
                provider_enum = Provider(st.session_state.selected_provider)
                st.session_state.selected_model = get_default_model_for_provider(provider_enum)
            except ValueError:
                pass  # Provider enum might not have this value yet
            st.warning(f"⚠️ Previously selected provider is unavailable. Auto-selected: **{st.session_state.selected_provider}**")
        
        selected_provider = st.radio(
            "Provider",
            options=provider_options,
            index=provider_options.index(st.session_state.selected_provider) if st.session_state.selected_provider in provider_options else 0,
            help="Select the LLM provider to use"
        )
        # Handle provider change (apply immediately for both OpenAI and Blablador)
        if selected_provider != st.session_state.selected_provider:
            st.session_state.selected_provider = selected_provider
            if selected_provider == Provider.BLABLADOR.value:
                st.session_state.selected_model = BlabladorModelName.GPT_OSS.value
            else:
                st.session_state.selected_model = OpenAIModelName.GPT_4O_MINI.value
            st.info(f"Switched to **{selected_provider}**. Next message will use the new model.")
        # Model selector based on provider
        # Get available models from config (filtered by .env if configured)
        model_options = get_available_models(st.session_state.selected_provider)
        
        if st.session_state.selected_provider == Provider.OPENAI.value:
            # Ensure selected model is valid for current provider
            if st.session_state.selected_model not in model_options:
                # Use default model if available, otherwise first available model
                default_model = get_default_model_for_provider(Provider.OPENAI)
                st.session_state.selected_model = default_model if default_model in model_options else (model_options[0] if model_options else OpenAIModelName.GPT_4O_MINI.value)
            selected_model = st.selectbox(
                "Model",
                options=model_options,
                index=model_options.index(st.session_state.selected_model) if st.session_state.selected_model in model_options else 0,
                help="Select the OpenAI model to use"
            )
        else:  # Blablador
            # Ensure selected model is valid for current provider, or auto-select GPT-OSS-120b
            if st.session_state.selected_model not in model_options:
                # Use default model if available, otherwise first available model
                default_model = get_default_model_for_provider(Provider.BLABLADOR)
                st.session_state.selected_model = default_model if default_model in model_options else (model_options[0] if model_options else BlabladorModelName.GPT_OSS.value)
            selected_model = st.selectbox(
                "Model",
                options=model_options,
                index=model_options.index(st.session_state.selected_model) if st.session_state.selected_model in model_options else 0,
                format_func=get_blablador_model_display_name,
                help="Select the Blablador model to use (GPT-OSS-120b)",
            )
        # Update model if changed (no restart: next message uses new model via config)
        if selected_model != st.session_state.selected_model:
            st.session_state.selected_model = selected_model
            st.info(f"Model changed to **{selected_model}**. Next message will use the new model.")


        # 3. File Upload Section
        st.subheader("File Upload")
        if st.session_state.server_connected:
            if st.session_state.thread_id:
                uploaded_files_by_module = load_uploaded_files(
                    st.session_state.thread_id,
                    st.session_state.server_url
                )
                st.session_state.uploaded_files = uploaded_files_by_module

            catalog = _get_modules_catalog_from_backend(st.session_state.server_url)
            upload_modules = catalog.get("upload_modules", [])
            module_options = {
                m.get("name"): m.get("display_name", m.get("name", "Unknown"))
                for m in upload_modules
                if m.get("name")
            }

            if not module_options:
                st.info("No upload-enabled modules found from server configuration.")
            else:
                active_module = get_active_module_from_messages(
                    st.session_state.messages,
                    allowed_modules=module_options.keys(),
                )

                if st.session_state.selected_upload_module not in module_options:
                    st.session_state.selected_upload_module = list(module_options.keys())[0]

                if active_module and active_module in module_options:
                    if st.session_state.selected_upload_module != active_module:
                        st.session_state.selected_upload_module = active_module
                        st.rerun()
                    selected_module = active_module
                    st.info(f"Active Module: **{module_options[active_module]}** (upload enabled)")
                else:
                    selected_module = st.selectbox(
                        "Select Module",
                        options=list(module_options.keys()),
                        format_func=lambda x: module_options[x],
                        index=list(module_options.keys()).index(st.session_state.selected_upload_module),
                        key="module_selector",
                        help="Select the module to upload files for",
                    )
                    if selected_module != st.session_state.selected_upload_module:
                        st.session_state.selected_upload_module = selected_module
                        st.rerun()
                    if active_module is None:
                        st.info("No module is currently active. You can still upload files for any module.")

                st.divider()
                is_module_active = (active_module == selected_module) if active_module else False
                selected_spec = next(
                    (m for m in upload_modules if m.get("name") == selected_module),
                    {
                        "name": selected_module,
                        "display_name": module_options[selected_module],
                        "upload_schema_sidebar": {},
                    },
                )
                _render_catalog_upload_ui(selected_spec, is_module_active)

                st.divider()
                _render_upload_summary(upload_modules)
        else:
            st.info("Connect to server to upload files")

        # Information
        st.subheader("About")
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


def _get_project_path_from_backend(server_url: str) -> str:
    """
    Get the project path from the backend server.
    
    Args:
        server_url: Base URL of the server
        
    Returns:
        Project path string, defaults to /tmp/vitess_project if fetch fails
    """
    # Check if we have cached project path
    if "project_path_cache" not in st.session_state:
        st.session_state.project_path_cache = {}
    
    cache_key = f"project_path_{server_url}"
    if cache_key in st.session_state.project_path_cache:
        return st.session_state.project_path_cache[cache_key]
    
    # Try to fetch from server
    try:
        response = httpx.get(
            f"{server_url}/config/vitess",
            timeout=5.0
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "success":
            config = data.get("config", {})
            project_path = config.get("VITESS_PROJECT_PATH", "/tmp/vitess_project")
            # Cache the result
            st.session_state.project_path_cache[cache_key] = project_path
            return project_path
    except Exception:
        # If fetch fails, return default
        pass
    
    # Return default if fetch fails
    default_path = "/tmp/vitess_project"
    st.session_state.project_path_cache[cache_key] = default_path
    return default_path


def _get_modules_catalog_from_backend(server_url: str) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch module and upload catalog from backend and cache it in session state."""
    if "modules_catalog_cache" not in st.session_state:
        st.session_state.modules_catalog_cache = {}

    cache_key = f"modules_catalog_{server_url}"
    cached = st.session_state.modules_catalog_cache.get(cache_key)

    try:
        response = httpx.get(f"{server_url}/config/modules", timeout=5.0)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "success":
            modules = data.get("modules", [])
            upload_modules = data.get("upload_modules", [])
            if not upload_modules:
                upload_modules = [
                    module for module in modules
                    if (
                        (module.get("upload_schema_sidebar") or module.get("upload_schema") or {})
                        .get("mode")
                    )
                ]
            payload = {
                "modules": modules,
                "upload_modules": upload_modules,
            }
            st.session_state.modules_catalog_cache[cache_key] = payload
            return payload
    except Exception:
        pass

    return cached or {"modules": [], "upload_modules": []}


def _reload_uploaded_files_from_server() -> None:
    """Reload uploaded files for the current thread from backend."""
    if not st.session_state.get("thread_id"):
        return
    st.session_state.uploaded_files = load_uploaded_files(
        st.session_state.thread_id,
        st.session_state.server_url,
    )


def _build_default_output_path(module_name: str, upload_schema_sidebar: Dict[str, Any]) -> str:
    """Build a default output path for path-only modules."""
    thread_id = st.session_state.get("thread_id")
    if not thread_id:
        return ""

    default_filename = upload_schema_sidebar.get("default_filename", f"{module_name}.dat")
    if st.session_state.server_connected:
        project_path = _get_project_path_from_backend(st.session_state.server_url)
    else:
        project_path = "/tmp/vitess_project"
    return f"{project_path}/{thread_id}/outputs/{default_filename}"


def _render_catalog_upload_ui(module_spec: Dict[str, Any], is_module_active: bool) -> None:
    """Render upload UI dynamically from module upload schema."""
    module_name = module_spec.get("name", "")
    display_name = module_spec.get("display_name", module_name.title())
    upload_schema_sidebar = (
        module_spec.get("upload_schema_sidebar")
        or module_spec.get("upload_schema")
        or {}
    )
    mode = upload_schema_sidebar.get("mode", "none")

    if not module_name:
        st.warning("Invalid upload module configuration.")
        return

    if not is_module_active:
        st.info(
            f"{display_name} is not the current chat focus. You can still upload files for it to use when the module runs."
        )

    if mode in {"file_single", "file_multi"}:
        _render_file_upload_mode(
            module_name, display_name, upload_schema_sidebar, is_module_active
        )
        return
    if mode == "path_only":
        _render_path_upload_mode(
            module_name, display_name, upload_schema_sidebar, is_module_active
        )
        return

    st.info(f"No upload UI configured for {display_name}.")


def _render_file_upload_mode(
    module_name: str,
    display_name: str,
    upload_schema_sidebar: Dict[str, Any],
    is_module_active: bool,
) -> None:
    """Render file-based upload UI for single/multi file modes."""
    mode = upload_schema_sidebar.get("mode", "file_single")
    max_files = int(upload_schema_sidebar.get("max_files", 1))
    allow_multiple = mode == "file_multi"
    extensions = upload_schema_sidebar.get("extensions") or ["dat", "txt", "csv", "nxs", "h5"]

    st.markdown(f"**{upload_schema_sidebar.get('label', display_name)}**")
    uploader_label = "Browse files" if allow_multiple else "Browse file"
    uploader_help = upload_schema_sidebar.get("help", "Select file(s) for this module.")
    selected_files_raw = st.file_uploader(
        uploader_label,
        type=extensions,
        accept_multiple_files=allow_multiple,
        key=f"{module_name}_uploader_dynamic",
        help=uploader_help,
        disabled=False,
    )

    selected_files: List[Any] = []
    if allow_multiple:
        selected_files = selected_files_raw or []
    elif selected_files_raw is not None:
        selected_files = [selected_files_raw]

    existing_files = st.session_state.uploaded_files.get(module_name, [])
    existing_names = {f.get("filename") for f in existing_files}
    pending_key = f"pending_upload_{module_name}"
    if pending_key not in st.session_state:
        st.session_state[pending_key] = []

    if selected_files:
        pending = []
        for selected_file in selected_files:
            if selected_file.name in existing_names:
                continue
            data = selected_file.read()
            pending.append({
                "name": selected_file.name,
                "bytes": data,
                "size": len(data),
            })
        st.session_state[pending_key] = pending
        if not pending:
            st.info("All selected files are already uploaded.")
    elif st.session_state[pending_key]:
        st.session_state[pending_key] = []

    pending_files = st.session_state[pending_key]
    remaining_slots = max_files - len(existing_files)
    if remaining_slots <= 0:
        st.warning(f"Maximum {max_files} file(s) allowed. Delete existing files to upload new ones.")
        pending_files = []
        st.session_state[pending_key] = []

    files_to_upload = pending_files[:remaining_slots] if allow_multiple else pending_files[:1]
    if files_to_upload:
        st.markdown("**Selected file(s) to upload:**")
        for item in files_to_upload:
            st.text(f"- {item['name']} ({item['size']:,} bytes)")

        if len(pending_files) > len(files_to_upload):
            st.warning(
                f"Only {len(files_to_upload)} file(s) will be uploaded due to module file limits."
            )

        button_label = "Upload Files" if allow_multiple else "Upload File"
        if st.button(
            button_label,
            key=f"upload_button_{module_name}",
            width='stretch',
            disabled=False,
        ):
            uploaded_count = 0
            for item in files_to_upload:
                result = upload_file_to_server(
                    BytesIO(item["bytes"]),
                    item["name"],
                    st.session_state.thread_id,
                    module_name,
                    st.session_state.server_url,
                )
                if result and result.get("status") == "success":
                    uploaded_count += 1

            if uploaded_count > 0:
                st.success(f"Uploaded {uploaded_count} file(s).")
                st.session_state[pending_key] = []
                _reload_uploaded_files_from_server()
                st.rerun()

    if existing_files:
        st.markdown(f"**Uploaded Files ({len(existing_files)})**")
        for file_meta in existing_files:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.text(
                    f"{file_meta.get('filename', 'unknown')} "
                    f"({file_meta.get('file_size', 0):,} bytes)"
                )
            with col2:
                if st.button("Delete", key=f"delete_{module_name}_{file_meta.get('file_id')}"):
                    if delete_file_from_server(
                        file_meta.get("file_id"),
                        st.session_state.thread_id,
                        module_name,
                        st.session_state.server_url,
                    ):
                        _reload_uploaded_files_from_server()
                        st.rerun()
    else:
        st.info("No files uploaded yet.")


def _render_path_upload_mode(
    module_name: str,
    display_name: str,
    upload_schema_sidebar: Dict[str, Any],
    is_module_active: bool,
) -> None:
    """Render path-only upload UI for modules that store path metadata."""
    st.markdown(f"**{upload_schema_sidebar.get('label', display_name)}**")
    default_path = _build_default_output_path(module_name, upload_schema_sidebar)
    state_key = f"{module_name}_path"
    input_key = f"{module_name}_path_input_dynamic"
    current_path = st.session_state.get(state_key, default_path)

    path_value = st.text_input(
        upload_schema_sidebar.get("input_label", "Output file path"),
        value=current_path,
        key=input_key,
        help=upload_schema_sidebar.get(
            "help",
            f"Default location: {default_path}. Enter a custom path if needed.",
        ),
        disabled=False,
        placeholder=default_path if default_path else "Enter output file path...",
    )

    if default_path:
        st.info(f"Default location: `{default_path}`")

    if path_value:
        st.session_state[state_key] = path_value
        if st.button(
            upload_schema_sidebar.get("button_text", "Save Path"),
            key=f"save_path_{module_name}",
            width='stretch',
            disabled=False,
        ):
            result = save_path_metadata_to_server(
                path_value,
                st.session_state.thread_id,
                module_name,
                st.session_state.server_url,
            )
            if result and result.get("status") == "success":
                st.success(f"Saved path for {display_name}: {path_value}")
                _reload_uploaded_files_from_server()
                st.rerun()
            else:
                st.error("Failed to save path. Please try again.")

    stored_items = st.session_state.uploaded_files.get(module_name, [])
    if stored_items:
        st.markdown("**Saved Path Metadata**")
        for file_meta in stored_items:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.text(file_meta.get("filename", file_meta.get("file_path", "unknown")))
            with col2:
                if st.button("Delete", key=f"delete_path_{module_name}_{file_meta.get('file_id')}"):
                    if delete_file_from_server(
                        file_meta.get("file_id"),
                        st.session_state.thread_id,
                        module_name,
                        st.session_state.server_url,
                    ):
                        _reload_uploaded_files_from_server()
                        st.rerun()
    elif default_path:
        st.info(f"No saved path metadata yet. Default path will be used: `{default_path}`")


def _render_upload_summary(upload_modules: List[Dict[str, Any]]) -> None:
    """Render summary counts for upload modules."""
    st.markdown("**Summary of Uploaded Files**")
    total_files = sum(len(files) for files in st.session_state.uploaded_files.values())
    if total_files <= 0:
        st.info("No files uploaded yet for this thread.")
        return

    for module in upload_modules:
        module_name = module.get("name")
        if not module_name:
            continue
        display_name = module.get("display_name", module_name)
        count = len(st.session_state.uploaded_files.get(module_name, []))
        st.text(f"{display_name}: {count}")


def _render_file_upload_ui(selected_module: str, is_module_active: bool) -> None:
    """
    Backward-compatible wrapper for legacy callers.

    This now routes to the central catalog-driven upload renderer instead of the
    old hardcoded per-module implementation.
    """
    catalog = _get_modules_catalog_from_backend(st.session_state.server_url)
    upload_modules = catalog.get("upload_modules", [])
    selected_spec = next(
        (module for module in upload_modules if module.get("name") == selected_module),
        {
            "name": selected_module,
            "display_name": selected_module.replace("_", " ").title(),
            "upload_schema_sidebar": {},
        },
    )
    _render_catalog_upload_ui(selected_spec, is_module_active)
