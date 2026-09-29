"""The sidebar panel that lists the input files for this conversation.

Its main job is to answer one question at a glance: does the read-in step have
every file it needs? You can see the answer here instead of asking the agent.
Each slot also has buttons to add or remove files.

There are three slots. The first version had six, but three of those
(writeout, monitor1d and monitor2d) never uploaded anything -- they only set
the name of an output file, which each module's settings already decide. So
they were removed, and those three modules now ask for their output file name
in the chat.
"""

from __future__ import annotations

from typing import Any

import httpx
import streamlit as st
from juena_core.clients.base import AgentClientError

__all__ = ["render_file_manifest"]

def _refusal(error: Exception) -> str:
    """The server's own sentence, which was written for this reader."""

    if isinstance(error, httpx.HTTPStatusError):
        try:
            detail = error.response.json().get("detail")
        except Exception:  # noqa: BLE001 -- a non-JSON body is still a refusal
            detail = None
        return str(detail or error.response.text or error)
    return str(error)


def _ensure_chat(client: Any, thread_id: str) -> None:
    """Give a sidebar-first upload the chat row ownership is checked against."""

    existing = client.get_chat(thread_id, include_messages=False)
    if existing is None:
        client.create_chat(
            thread_id,
            agent_id=client.agent,
            title="New Chat",
        )
        return
    if str(existing.get("agent_id")) != client.agent:
        raise RuntimeError(
            "This conversation belongs to the other VITESS mode. Start or open "
            "a conversation in the selected mode before staging a file."
        )


def _stage(client: Any, thread_id: str, module: str, uploaded: Any) -> None:
    try:
        _ensure_chat(client, thread_id)
        client.stage_file(thread_id, module, uploaded.name, uploaded.getvalue())
    except (AgentClientError, httpx.HTTPError, RuntimeError) as error:
        st.error(_refusal(error))
        return
    st.session_state[f"staged_marker:{thread_id}:{module}"] = uploaded.name


def render_file_manifest(client: Any, thread_id: str) -> None:
    """Draw every slot, what is staged in it, and the way to change that."""

    st.subheader("Input files")
    try:
        staged = client.list_staged(thread_id)
    except httpx.HTTPError as error:
        st.warning(f"Could not read the staged files: {error}")
        return

    by_module: dict[str, list[dict[str, Any]]] = {}
    for item in staged:
        by_module.setdefault(str(item["module"]), []).append(item)

    try:
        modules = client.upload_modules()
    except httpx.HTTPError as error:
        # Labels are presentation, not a fallback catalog. If the server cannot
        # name the slots, drawing controls from this module would recreate the
        # second source of truth CP2 removed.
        st.warning(f"Could not read the upload slots: {error}")
        return

    for slot in modules:
        module = str(slot["name"])
        label = str(slot["label"])
        help_text = str(slot["help"])
        extensions = [str(item) for item in slot["extensions"]]
        max_files = int(slot["max_files"])
        files = by_module.get(module, [])
        with st.expander(f"{label} — {len(files)} staged", expanded=not files):
            st.caption(help_text)
            for item in files:
                columns = st.columns([5, 1])
                columns[0].write(f"`{item['filename']}`  ·  {item['size_bytes']:,} bytes")
                if columns[1].button(
                    "Remove",
                    key=f"remove:{thread_id}:{module}:{item['filename']}",
                    help="Staged in the wrong slot? Remove it and upload it again.",
                ):
                    try:
                        client.remove_staged(thread_id, module, item["filename"])
                    except httpx.HTTPStatusError as error:
                        st.error(_refusal(error))
                    else:
                        st.rerun()

            if len(files) < max_files:
                # Keyed on what is already staged, so the widget resets after an
                # upload instead of re-sending the same file on the next rerun.
                uploaded = st.file_uploader(
                    f"Add to {label.lower()}",
                    type=extensions,
                    key=f"upload:{thread_id}:{module}:{len(files)}",
                    label_visibility="collapsed",
                )
                if uploaded is not None:
                    _stage(client, thread_id, module, uploaded)
                    st.rerun()
            else:
                st.caption(
                    f"This slot is full ({max_files} of {max_files}). Remove a file "
                    "before uploading another."
                )

    if not staged:
        st.caption(
            "Nothing staged yet. If the agent asks for a file, upload it here while "
            "the conversation waits, then answer its question card."
        )
