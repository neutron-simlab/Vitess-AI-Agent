"""The vitess-ai FastAPI application: core's factory, plus what is VITESS's.

The routes, the streaming vocabulary, the lifespans and the identity seam are
`juena_core.server.service.create_app`'s. What is passed in here is what core
cannot know: a single local user instead of an institute login, the upload route
whose files a compiled binary opens, and the note that tells the supervisor
those files are real paths rather than text it can read.
"""

from __future__ import annotations

import asyncio
import warnings

from fastapi import HTTPException
from langchain_core._api import LangChainBetaWarning

from juena_core.log import get_logger
from juena_core.server.identity import local_principal
from juena_core.server.service import ThreadActivity, ThreadWorkspace, create_app
from vitess_ai.config import Config, configure_core
from vitess_ai.server.file_endpoints import build_file_router
from vitess_ai.server.uploads import UploadStore
from vitess_ai.workspace_lock import ThreadWorkspaceBusy

warnings.filterwarnings("ignore", category=LangChainBetaWarning)

# Order matters and it is the whole reason this is not further down: core's
# `settings()` raises until `configure()` has run, and the imports below build
# chat models and read the artifact root at import time.
Config.validate_required()
configure_core()

# Imported for their side effect: each module registers its own agent factory.
# Importing *this* module has to be enough, because the process serving the API
# is not always the launcher -- production runs
# `uvicorn vitess_ai.server.service:app` -- and registering only from a main
# script leaves those processes with an empty registry, so every invocation
# would 404.
import vitess_ai.agents.vitess_agent  # noqa: E402,F401  the guided simulator
import vitess_ai.agents.advanced_mode  # noqa: E402,F401  the parameter sweep

logger = get_logger(__name__)
logger.info("Service logging initialized")

#: One user, fixed, and stable across restarts because it owns every thread and
#: names the memory namespace. This is injected exactly where a real provider's
#: dependency would go, so adopting an institute login later replaces this
#: callable rather than rewriting any route.
principal = local_principal(
    user_id=Config.LOCAL_USER_ID,
    subject="local",
    issuer="vitess-ai",
    display_name="Local user",
)

uploads = UploadStore(
    Config.VITESS_PROJECT_PATH,
    max_bytes=Config.MAX_UPLOAD_BYTES,
    allowed_extensions=Config.UPLOAD_EXTENSIONS,
)
thread_activity = ThreadActivity()


async def _delete_thread_workspace(*, user_id: str, thread_id: str) -> None:
    """Remove exactly one UUID-named project directory from the shared volume."""

    del user_id
    try:
        await asyncio.to_thread(uploads.delete_thread, thread_id)
    except ThreadWorkspaceBusy as exc:
        raise HTTPException(
            status_code=409, detail="Thread has an active simulation"
        ) from exc


app = create_app(
    principal=principal,
    workspace=ThreadWorkspace(delete=_delete_thread_workspace),
    thread_activity=thread_activity,
    # A thread's staged files are already on the shared volume, which is the
    # only place they are of any use -- the VITESS binaries open them by path.
    # Copying them into graph state would produce a second, decoded copy that
    # nothing reads.
    closing_note=(
        "The user's input files are staged on the project volume, not in this "
        "conversation. `inspect_thread_folders` lists them, and the paths it "
        "returns are what a module's file parameter takes."
    ),
    title="vitess-ai",
    version="0.1.0",
    extra_routers=(
        build_file_router(principal, uploads, thread_activity=thread_activity),
    ),
)
