"""The one HTTP route staged VITESS inputs arrive through.

Both ways in post here: the sidebar's per-module upload control, and the answer
to an `ask_user` card when a specialist asks for a file in the chat. One route
means one place where the module is named, the extension is checked and the
bytes are written, so the two ways in cannot diverge in what they accept.

Ownership is checked against the chat rather than against the directory. A
thread id the caller does not own must 404 whether or not anything is staged on
it -- otherwise the reply distinguishes "not yours" from "nothing there", which
is a thread-id oracle.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from juena_core.server.chat.repository import ChatNotFoundError, get_owned_chat
from juena_core.server.database.connection import get_db_session
from juena_core.server.identity import Principal, PrincipalDependency
from vitess_ai.server.uploads import UploadRefused, UploadStore, upload_module_names

__all__ = ["build_file_router"]


def build_file_router(
    principal: PrincipalDependency, store: UploadStore
) -> APIRouter:
    """A router over one upload store, authenticating with one principal."""

    router = APIRouter(prefix="/files", tags=["files"])

    async def _owned(session: AsyncSession, user: Principal, thread_id: UUID) -> None:
        try:
            # `agent_id=None`: addressed by thread, runs no graph. Core makes
            # the argument mandatory-but-nullable so a route that *does* run
            # one cannot skip the check by leaving it out.
            await get_owned_chat(session, user.id, str(thread_id), agent_id=None)
        except ChatNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Chat not found") from exc

    @router.get("/modules")
    async def list_modules() -> dict[str, Any]:
        """The slots that exist. The sidebar renders exactly these."""

        return {"modules": list(upload_module_names())}

    @router.post("/{thread_id}/{module}")
    async def stage_file(
        thread_id: UUID,
        module: str,
        upload: UploadFile = File(...),
        user: Principal = Depends(principal),
        session: AsyncSession = Depends(get_db_session),
    ) -> dict[str, Any]:
        """Write one input file into a thread's slot on the shared volume."""

        await _owned(session, user, thread_id)
        content = await upload.read()
        try:
            staged = store.stage(
                content,
                filename=upload.filename or "",
                thread_id=thread_id,
                module=module,
            )
        except UploadRefused as exc:
            # 422, not 400: the request was well-formed and the file was not
            # acceptable. The message is written for the person who chose it.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return staged.as_dict()

    @router.get("/{thread_id}")
    async def list_staged(
        thread_id: UUID,
        module: str | None = None,
        user: Principal = Depends(principal),
        session: AsyncSession = Depends(get_db_session),
    ) -> dict[str, Any]:
        """Everything staged for one thread, which is what the manifest shows."""

        await _owned(session, user, thread_id)
        try:
            files = store.staged(thread_id, module)
        except UploadRefused as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"files": [item.as_dict() for item in files]}

    @router.delete("/{thread_id}/{module}/{filename}")
    async def remove_staged(
        thread_id: UUID,
        module: str,
        filename: str,
        user: Principal = Depends(principal),
        session: AsyncSession = Depends(get_db_session),
    ) -> dict[str, Any]:
        """Remove one staged file, so a wrong slot can be corrected."""

        await _owned(session, user, thread_id)
        try:
            removed = store.remove(thread_id, module, filename)
        except UploadRefused as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not removed:
            raise HTTPException(status_code=404, detail="No such staged file")
        return {"removed": filename, "module": module}

    #: Deliberately absent: everything to do with *output* files. The first
    #: generation's store also saved, listed and deleted simulation outputs,
    #: which in v2 belong to two owners that already exist -- the MCP server
    #: writes them under the run id it was given, and core's artifact store
    #: delivers them (03/CP3a). A third copy of "which files may be handed to a
    #: user" is how a sweep quietly delivers what the guided path refuses.

    return router
