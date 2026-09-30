"""The in-chat builder and its server-confirmed handoff to guided configuration."""

from pathlib import Path
from typing import Any

import httpx
import streamlit as st
from juena_core.clients.base import AgentClientError

from app.file_management import _ensure_chat
from app.session_state import start_new_thread

_ASSETS = Path(__file__).parent / "flow_frontend" / "dist"


@st.cache_resource
def _component():
    return st.components.v2.component(
        "vitess_guide_flow",
        js=(_ASSETS / "flow.js").read_text(),
        css=(_ASSETS / "flow.css").read_text(),
    )


def _error_issues(error: httpx.HTTPStatusError) -> list[dict[str, Any]]:
    detail = error.response.json().get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("issues"), list):
        return detail["issues"]
    return [
        {
            "modules": [],
            "message": str(detail),
            "correction": "Reload the conversation and try again.",
        }
    ]


def render_pipeline_builder() -> tuple[bool, str | None]:
    """Return whether the canvas owns the page, and an accepted kickoff message."""
    if st.session_state.selected_agent != "vitess":
        return False, None
    client = st.session_state.client
    thread = st.session_state.thread_id
    active_key = f"builder_active:{thread}"
    draft_key = f"builder_draft:{thread}"
    preset_key = f"builder_preset:{thread}"
    issues_key = f"builder_issues:{thread}"
    try:
        record = client.get_pipeline(thread)
    except (httpx.HTTPError, AgentClientError) as exc:
        st.error(f"Could not load the pipeline: {exc}")
        return True, None

    confirmed = record is not None and record["status"] == "confirmed"
    if (
        st.session_state.messages
        and not record
        and st.button("Build pipeline", key=f"builder_open:{thread}")
    ):
        start_new_thread(st.session_state)
        thread = st.session_state.thread_id
        st.session_state[f"builder_active:{thread}"] = True
        st.rerun()

    correction = record is not None and record["status"] == "needs_correction"
    if not confirmed and not correction and not st.session_state.get(active_key):
        return False, None

    try:
        manifest = client.pipeline_modules()
    except (httpx.HTTPError, AgentClientError) as exc:
        st.error(f"Could not load the module palette: {exc}")
        return not confirmed, None
    if not (_ASSETS / "flow.js").is_file():
        st.error(
            "The pipeline canvas has not been built. Run npm ci and npm run build in app/flow_frontend."
        )
        return not confirmed, None

    revision = record["revision"] if record else None
    # A server correction replaces an earlier draft exactly once for this revision.
    reset_key = f"builder_correction:{thread}"
    if correction and st.session_state.get(reset_key) != revision:
        st.session_state[draft_key] = record["modules"]
        st.session_state[preset_key] = record["preset"]
        st.session_state[issues_key] = record["issues"]
        st.session_state[reset_key] = revision
    preset = (
        record["preset"]
        if confirmed
        else st.session_state.get(preset_key, manifest["default_preset"])
    )
    defaults = next(
        item["defaults"] for item in manifest["presets"] if item["id"] == preset
    )
    draft = (
        record["modules"]
        if confirmed
        else st.session_state.setdefault(draft_key, list(defaults))
    )
    issues = [] if confirmed else st.session_state.get(issues_key, [])

    def remember_draft() -> None:
        value = st.session_state.get(component_key, {}).get("draft")
        if value is not None and not confirmed:
            st.session_state[draft_key] = list(value["modules"])
            st.session_state[preset_key] = value["preset"]

    component_key = f"guide_flow:{thread}:{revision}"
    submitted_key = f"builder_submission:{thread}"
    result = _component()(
        data={
            "manifest": manifest,
            "modules": draft,
            "preset": preset,
            "issues": issues,
            "revision": revision,
            "feedback": st.session_state.get(submitted_key),
            "locked": confirmed,
        },
        key=component_key,
        default={"draft": {"modules": draft, "preset": preset}},
        on_draft_change=remember_draft,
        on_confirm_change=lambda: None,
    )
    kickoff_key = f"builder_kickoff:{thread}:{revision}"
    if confirmed:
        kickoff = st.session_state.pop(kickoff_key, None)
        # Only the checkpointed plan proves this revision reached the agent.
        # Older chat messages survive a correction and cannot acknowledge it.
        if not record["configuration_started"]:
            if kickoff:
                return False, kickoff
            if st.button(
                "Start configuration", key=f"builder_start:{thread}:{revision}"
            ):
                try:
                    accepted = client.confirm_pipeline(
                        thread,
                        record["modules"],
                        record["revision"],
                        preset=record["preset"],
                    )
                except (httpx.HTTPError, AgentClientError) as exc:
                    st.error(f"Could not start configuration: {exc}")
                else:
                    return False, accepted["message"]
        return not st.session_state.messages, None

    if result.confirm is not None and result.confirm["id"] != st.session_state.get(
        submitted_key
    ):
        # st.rerun can replay a component trigger. A rejected click must never
        # silently submit again when the error is being drawn.
        st.session_state[submitted_key] = result.confirm["id"]
        submitted = list(result.confirm["modules"])
        submitted_preset = result.confirm["preset"]
        st.session_state[draft_key] = submitted
        st.session_state[preset_key] = submitted_preset
        try:
            _ensure_chat(client, thread)
            accepted = client.confirm_pipeline(
                thread, submitted, revision, preset=submitted_preset
            )
        except httpx.HTTPStatusError as exc:
            st.session_state[issues_key] = _error_issues(exc)
            st.rerun()
        except (httpx.HTTPError, AgentClientError, RuntimeError) as exc:
            st.session_state[issues_key] = [
                {
                    "modules": [],
                    "message": str(exc),
                    "correction": "Try confirming again when the service is available.",
                }
            ]
            st.rerun()
        st.session_state.pop(issues_key, None)
        st.session_state[active_key] = False
        # Render the accepted canvas as locked before the chat starts streaming.
        st.session_state[
            f"builder_kickoff:{thread}:{accepted['pipeline']['revision']}"
        ] = accepted["message"]
        st.rerun()
    return True, None
