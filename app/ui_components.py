"""The page header and a couple of style rules.

Drawing chat messages, files the agent produced, and a reply as it streams in
is done by juena-core (`juena_core.ui.components`), because that code has to
match what core's server sends. What is left here is what makes this page look
like VITESS AI Agent: the header and two style rules.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from juena_core.ui.components import (  # noqa: F401  re-exported for the page
    render_message,
    reset_rendered_artifacts,
)

__all__ = [
    "logo_path",
    "render_chat_input_styles",
    "render_header",
    "render_message",
    "reset_rendered_artifacts",
]

_ASSETS = Path(__file__).parent / "assets"


def logo_path() -> Path | None:
    candidate = _ASSETS / "logo.png"
    return candidate if candidate.exists() else None


def render_header(agent: str) -> None:
    """Name the product and, plainly, which of the two agents is answering."""

    logo = logo_path()
    if logo is not None:
        row = st.container(
            horizontal=True,
            vertical_alignment="center",
            gap="small",
        )
        with row:
            st.image(str(logo), width=64)
            target = st.container()
    else:
        target = st.container()
    with target:
        st.title("VITESS AI Agent")
        st.caption(
            "Guided simulation — one run, configured with you, module by module."
            if agent == "vitess"
            else "Advanced mode — a parameter sweep, run unattended once it is planned."
        )


def render_chat_input_styles() -> None:
    """Keep the composer legible on a wide monitor."""

    st.markdown(
        """
        <style>
        [data-testid="stChatInput"] textarea { font-size: 0.95rem; }
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
            min-height: 3.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
