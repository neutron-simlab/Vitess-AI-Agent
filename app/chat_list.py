"""The conversation list: pick one, rename it, delete it.

Extracted from the sidebar for the same reason the upload half became
`file_management`: the sidebar is navigation wiring, and a list with an inline
name editor and a per-row action menu is a panel with its own state. The state
it owns is one key, `editing_thread_id` -- which conversation, if any, is being
renamed -- and it lives in the session rather than in a widget because the
editor has to survive the rerun its own Save button causes.

The decision this panel must not get wrong is what happens to `thread_id` when
the open conversation is deleted, so that one is not decided here: it is
`session_state.leave_deleted_thread`, which is a pure function with tests.
"""

from __future__ import annotations

import textwrap
from typing import Any
from uuid import uuid4

import streamlit as st

from app.session_state import leave_deleted_thread

__all__ = ["DEFAULT_CHAT_TITLE", "chat_label", "render_chat_list", "title_key"]


#: `Chat.title`'s own default in core, and so what clearing the name restores.
DEFAULT_CHAT_TITLE = "New Chat"

#: Room for a title once the actions popover has taken its share of the row.
_TITLE_WIDTH = 22


def chat_label(chat: Any) -> tuple[str, str]:
    """The row label and the full title behind it, as juena-chatbot does it.

    An untitled conversation falls back to its thread id, because the default
    title is the same for every one of them -- a sidebar of four rows all
    reading "New Chat" cannot be navigated, which is the state this list was
    in before it could be renamed. A long title is shortened on a word
    boundary and kept whole in the tooltip.
    """

    title = " ".join((chat.title or "").split()).strip()
    if not title or title == DEFAULT_CHAT_TITLE:
        title = f"Chat {chat.thread_id[:8]}"
    if len(title) <= _TITLE_WIDTH:
        return title, title
    return textwrap.shorten(title, width=_TITLE_WIDTH, placeholder="..."), title


def _enter_chat(storage: Any, thread_id: str) -> None:
    loaded = storage.load_chat_with_messages(thread_id)
    st.session_state.thread_id = thread_id
    st.session_state.messages = loaded[1] if loaded else []
    st.session_state.chat_initialized = True


def title_key(thread_id: str) -> str:
    """The name field's widget key, one per conversation.

    Not one shared key. Streamlit binds widget state to the key and ignores
    `value=` once that key exists, so with a shared key the text typed for one
    conversation reappears as another's name. `_close_editor` covers Save and
    Cancel by clearing the key, but nothing clears it when the user opens
    Rename on a second conversation while the first editor is still open --
    and there the shared key shows, and saves, the name typed for the first.
    """

    return f"rename_title:{thread_id}"


def _close_editor(thread_id: str) -> None:
    """Forget the editor and the text typed into it, so Cancel discards."""

    st.session_state.pop("editing_thread_id", None)
    st.session_state.pop(title_key(thread_id), None)


def _render_rename_editor(storage: Any) -> None:
    """The name field, shown above the list while one chat is being renamed.

    A text input per row would put 25 of them on the page, all live, so the
    list stays buttons and the editor is the one row that replaces itself.
    """

    thread_id = st.session_state.get("editing_thread_id")
    if thread_id is None:
        return
    chat = storage.get_chat(thread_id)
    if chat is None:
        # Deleted from another tab while its editor was open.
        _close_editor(thread_id)
        return

    title = st.text_input(
        "Conversation name",
        value=chat.title,
        key=title_key(thread_id),
        label_visibility="collapsed",
        placeholder="Conversation name",
    )
    save, cancel = st.columns(2, gap="small")
    if save.button("Save", key="rename_save", width="stretch"):
        chat.title = title.strip() or DEFAULT_CHAT_TITLE
        try:
            storage.upsert_chat(chat)
        except Exception as error:  # noqa: BLE001 -- report, do not lose the page
            st.error(f"Could not rename this conversation: {error}")
            return
        _close_editor(thread_id)
        st.rerun()
    if cancel.button("Cancel", key="rename_cancel", width="stretch"):
        _close_editor(thread_id)
        st.rerun()
    st.divider()


def _render_chat_actions(storage: Any, agent: str, chat: Any, *, active: bool) -> None:
    """Rename and delete, behind a popover so a row stays one line.

    Opening the popover is the confirmation step for the delete: there is no
    undo, and a bare button beside every title is one mis-click from losing a
    conversation.
    """

    with st.popover("⋯"):
        if st.button("Rename", key=f"rename:{chat.thread_id}", width="stretch"):
            st.session_state.editing_thread_id = chat.thread_id
            st.rerun()
        if st.button("Delete", key=f"delete:{chat.thread_id}", width="stretch"):
            try:
                storage.delete_chat(chat.thread_id)
            except Exception as error:  # noqa: BLE001 -- report, do not lose the page
                st.error(f"Could not delete this conversation: {error}")
                return
            if st.session_state.get("editing_thread_id") == chat.thread_id:
                _close_editor(chat.thread_id)
            if active:
                # Scoped to this agent, because the list is: the other mode's
                # most recent conversation is not this one's fallback.
                listing = storage.list_chats(limit=2, agent_id=agent)
                entering = leave_deleted_thread(
                    st.session_state,
                    deleted=chat.thread_id,
                    remaining=[item.thread_id for item in listing],
                )
                if entering is not None:
                    _enter_chat(storage, entering)
            st.rerun()


def render_chat_list(client: Any, agent: str) -> None:
    storage = st.session_state.chat_storage
    if st.button("New conversation", width="stretch"):
        st.session_state.thread_id = str(uuid4())
        st.session_state.messages = []
        st.session_state.chat_initialized = True
        st.rerun()

    try:
        chats = storage.list_chats(limit=25, agent_id=agent)
    except Exception as error:  # noqa: BLE001 -- the list is not worth a crash
        st.caption(f"Could not list conversations: {error}")
        return

    _render_rename_editor(storage)

    for chat in chats:
        active = chat.thread_id == st.session_state.thread_id
        label, full_title = chat_label(chat)
        select, actions = st.columns([5, 1], gap="small")
        if select.button(
            ("• " if active else "") + label,
            key=f"chat:{chat.thread_id}",
            width="stretch",
            help=full_title,
        ):
            _enter_chat(storage, chat.thread_id)
            st.rerun()
        with actions:
            _render_chat_actions(storage, agent, chat, active=active)
