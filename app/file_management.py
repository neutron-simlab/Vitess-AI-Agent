"""
File management functions for Streamlit UI.

This module provides functions for uploading, downloading, and managing files
in the Streamlit interface, including server health checks and client initialization.
"""
import streamlit as st
import httpx
from typing import Optional, List, Dict, Iterable
from io import BytesIO

from vitess_ai.clients.client import AgentClient
from vitess_ai.schema.server import ChatMessage


def check_server_health(server_url: str) -> bool:
    """Check if server is running by hitting /health endpoint."""
    try:
        response = httpx.get(f"{server_url}/health", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


def initialize_client(server_url: str, agent_id: str = "supervisor") -> Optional[AgentClient]:
    """Initialize AgentClient with server URL."""
    try:
        # Set get_info=False since /info endpoint doesn't exist in the service
        # Initialize without agent first, then set it with verify=False
        client = AgentClient(base_url=server_url, agent=None, get_info=False)
        # Set selected agent without verification
        client.update_agent(agent_id, verify=False)
        return client
    except Exception as e:
        st.error(f"Failed to initialize client: {e}")
        return None


def upload_file_to_server(
    file: BytesIO,
    filename: str,
    thread_id: str,
    module_type: str,
    server_url: str
) -> Optional[Dict]:
    """Upload a file to the server."""
    try:
        files = {"file": (filename, file, "application/octet-stream")}
        data = {
            "thread_id": thread_id,
            "module_type": module_type
        }
        
        response = httpx.post(
            f"{server_url}/files/upload",
            files=files,
            data=data,
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Failed to upload file: {e}")
        return None


def delete_file_from_server(
    file_id: str,
    thread_id: str,
    module_type: str,
    server_url: str
) -> bool:
    """Delete a file from the server."""
    try:
        response = httpx.delete(
            f"{server_url}/files/{file_id}",
            params={
                "thread_id": thread_id,
                "module_type": module_type
            },
            timeout=10.0
        )
        response.raise_for_status()
        return True
    except Exception as e:
        st.error(f"Failed to delete file: {e}")
        return False


def load_uploaded_files(thread_id: str, server_url: str) -> Dict[str, List[Dict]]:
    """Load uploaded files for a thread from the server."""
    try:
        response = httpx.get(
            f"{server_url}/files/thread/{thread_id}",
            timeout=10.0
        )
        response.raise_for_status()
        data = response.json()
        
        # Organize by module type
        files_by_module = {}
        for file_meta in data.get("files", []):
            module_type = file_meta.get("module_type")
            if module_type not in files_by_module:
                files_by_module[module_type] = []
            files_by_module[module_type].append(file_meta)
        
        return files_by_module
    except Exception as e:
        st.warning(f"Failed to load uploaded files: {e}")
        return {}


def get_active_module_from_messages(
    messages: List[ChatMessage],
    allowed_modules: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """
    Detect the currently active module from chat messages.
    
    Looks at the most recent AI messages to determine which module
    is currently active/being configured.
    
    Args:
        messages: List of chat messages
        
    Returns:
        Active module name or None
    """
    if not messages:
        return None

    allowed_set = set(allowed_modules) if allowed_modules is not None else None
    
    # Look at recent AI messages (most recent first)
    for message in reversed(messages):
        if message.type == "ai" and message.custom_data:
            module_name = message.custom_data.get("module_name")
            if not module_name:
                continue

            # Supervisor/default means no specific module is active.
            if module_name in {"supervisor", "default"}:
                continue

            if allowed_set is None or module_name in allowed_set:
                return module_name
    
    return None


def save_path_metadata_to_server(
    file_path: str,
    thread_id: str,
    module_type: str,
    server_url: str
) -> Optional[Dict]:
    """
    Save a file path as metadata to the server for modules that use paths (writeout, monitor1d, monitor2d).
    
    This creates a small metadata file that can be retrieved by MCP tools.
    
    Args:
        file_path: The file path to save
        thread_id: Thread ID
        module_type: Module type (writeout, monitor1d, monitor2d)
        server_url: Server URL
        
    Returns:
        Dictionary with file metadata or None if failed
    """
    try:
        # Create a small metadata file with the path
        metadata_content = file_path.encode('utf-8')
        filename = f"{module_type}_path.txt"
        
        files = {"file": (filename, BytesIO(metadata_content), "text/plain")}
        data = {
            "thread_id": thread_id,
            "module_type": module_type
        }
        
        response = httpx.post(
            f"{server_url}/files/upload",
            files=files,
            data=data,
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Failed to save path metadata: {e}")
        return None
