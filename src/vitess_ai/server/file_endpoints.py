"""The one HTTP route staged VITESS inputs arrive through.

The sidebar's per-module control posts here. When a specialist needs a file,
`ask_user` pauses the conversation while the user uploads through that same
sidebar and then answers the waiting card. Core's clarification reply is text;
pretending the card itself carries binary bytes would create a second upload
protocol with no structured module destination.

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

from juena_core.server.api.endpoints import ThreadActivity
from juena_core.server.chat.repository import ChatNotFoundError, get_owned_chat
from juena_core.server.database.connection import get_db_session
from juena_core.server.identity import Principal, PrincipalDependency
from vitess_ai.server.uploads import UploadRefused, UploadStore, upload_module_manifest

__all__ = ["build_file_router"]


async def _read_upload_bytes(upload: UploadFile, max_bytes: int) -> bytes:
    """Read at most one byte beyond the limit, then release the spool file.

    The store is still the authority that accepts or refuses the body. This
    boundary only prevents a client from making the API allocate an unbounded
    body before the store gets a chance to enforce its 100 MB policy.
    """

    try:
        return await upload.read(max_bytes + 1)
    finally:
        await upload.close()


def build_file_router(
    principal: PrincipalDependency,
    store: UploadStore,
    *,
    thread_activity: ThreadActivity | None = None,
) -> APIRouter:
    """A router over one upload store, authenticating with one principal."""

    router = APIRouter(prefix="/files", tags=["files"])
    thread_activity = thread_activity or ThreadActivity()

    def _reserve(thread_id: UUID) -> str:
        canonical = str(thread_id)
        if not thread_activity.reserve_run(canonical):
            raise HTTPException(status_code=409, detail="Thread deletion is in progress")
        return canonical

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
        """The slots and limits that exist. The sidebar renders exactly these."""

        return {"modules": list(upload_module_manifest())}

    @router.post("/{thread_id}/{module}")
    async def stage_file(
        thread_id: UUID,
        module: str,
        upload: UploadFile = File(...),
        user: Principal = Depends(principal),
        session: AsyncSession = Depends(get_db_session),
    ) -> dict[str, Any]:
        """Write one input file into a thread's slot on the shared volume."""

        reserved = _reserve(thread_id)
        try:
            await _owned(session, user, thread_id)
            content = await _read_upload_bytes(upload, store.max_bytes)
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
        finally:
            thread_activity.release_run(reserved)
        return staged.as_dict()

    @router.get("/{thread_id}")
    async def list_staged(
        thread_id: UUID,
        module: str | None = None,
        user: Principal = Depends(principal),
        session: AsyncSession = Depends(get_db_session),
    ) -> dict[str, Any]:
        """Everything staged for one thread, which is what the manifest shows."""

        reserved = _reserve(thread_id)
        try:
            await _owned(session, user, thread_id)
            files = store.staged(thread_id, module)
        except UploadRefused as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            thread_activity.release_run(reserved)
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

        reserved = _reserve(thread_id)
        try:
            await _owned(session, user, thread_id)
            removed = store.remove(thread_id, module, filename)
        except UploadRefused as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            thread_activity.release_run(reserved)
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
