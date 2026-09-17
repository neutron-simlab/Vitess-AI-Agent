"""The staged-file manifest: every slot at once, and what is in it.

**This is a status panel with upload controls, not an upload form.** The
question it exists to answer is *"has read-in got everything it needs?"*, and
that question is answered by looking rather than by asking the agent. The first
generation's sidebar showed six upload widgets and nothing about what was
already there, so the only way to find out was to send a message.

Three slots, not six. `writeout`, `monitor1d` and `monitor2d` were declared as
uploads under a mode that uploaded nothing: each set an output filename the
parameter schema already owns, with its own flag and its own default. Those
rows are gone (03/CP2), and no output filename appears here at all -- the three
modules collect theirs conversationally, from the schema default.
"""

from __future__ import annotations

from typing import Any

import httpx
import streamlit as st

__all__ = ["render_file_manifest"]

#: What each slot is for, in the words of someone who has the file in front of
#: them. The catalog carries the same labels for the agent; these are shorter
#: because the panel is narrow and the answer has to be readable at a glance.
SLOT_LABELS = {
    "readin": ("Read-in", "Neutron trajectory files, up to 3."),
    "instrument": ("Instrument", "The instrument.inf of an earlier simulation."),
    "guide": ("Guide", "A guide shape or reflectivity file. Optional."),
}


def _refusal(error: httpx.HTTPStatusError) -> str:
    """The server's own sentence, which was written for this reader."""

    try:
        detail = error.response.json().get("detail")
    except Exception:  # noqa: BLE001 -- a non-JSON body is still a refusal
        detail = None
    return str(detail or error.response.text or error)


def _stage(client: Any, thread_id: str, module: str, uploaded: Any) -> None:
    try:
        client.stage_file(thread_id, module, uploaded.name, uploaded.getvalue())
    except httpx.HTTPStatusError as error:
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
    except httpx.HTTPError:
        # The panel is worth drawing from what we know even when the slot list
        # cannot be fetched; the labels below are the same three.
        modules = list(SLOT_LABELS)

    for module in modules:
        label, help_text = SLOT_LABELS.get(module, (module, ""))
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

            # Keyed on what is already staged, so the widget resets after an
            # upload instead of re-sending the same file on the next rerun.
            uploaded = st.file_uploader(
                f"Add to {label.lower()}",
                key=f"upload:{thread_id}:{module}:{len(files)}",
                label_visibility="collapsed",
            )
            if uploaded is not None:
                _stage(client, thread_id, module, uploaded)
                st.rerun()

    if not staged:
        st.caption(
            "Nothing staged yet. You can also upload from the chat: the agent will "
            "ask for a file when a module needs one."
        )
