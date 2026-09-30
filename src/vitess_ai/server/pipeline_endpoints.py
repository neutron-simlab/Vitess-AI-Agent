"""Owned guide-builder plans; confirmation validates but never invokes an agent."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from juena_core.server.api.endpoints import ThreadActivity
from juena_core.server.chat.repository import ChatNotFoundError, get_owned_chat
from juena_core.server.database.checkpointer import get_checkpointer
from juena_core.server.database.connection import get_db_session
from juena_core.server.identity import Principal, PrincipalDependency
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from vitess_ai.pipeline import (
    PipelineConflict,
    PipelineInvalid,
    PipelineRecord,
    PipelineStore,
    PresetId,
    builder_manifest,
)
from vitess_ai.workspace_lock import ThreadWorkspaceDeleted


class ConfirmPipeline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: PresetId = "guide_test"
    modules: list[str] = Field(max_length=32)
    revision: int | None = Field(default=None, ge=1)


def build_pipeline_router(
    principal: PrincipalDependency,
    store: PipelineStore,
    *,
    thread_activity: ThreadActivity,
) -> APIRouter:
    router = APIRouter(prefix="/pipelines", tags=["pipelines"])

    async def owned(thread_id: UUID, user: Principal, session: AsyncSession) -> str:
        canonical = str(thread_id)
        try:
            await get_owned_chat(session, user.id, canonical, agent_id="vitess")
        except ChatNotFoundError as exc:
            raise HTTPException(404, "Chat not found") from exc
        return canonical

    async def payload(record: PipelineRecord, thread_id: str) -> dict:
        started = False
        if record.status == "confirmed":
            checkpoint = await get_checkpointer().aget(
                {"configurable": {"thread_id": thread_id}}
            )
            state = checkpoint["channel_values"] if checkpoint else {}
            started = (
                state.get("pipeline_revision") == record.revision
                and state.get("planned_execution_order") == record.modules
            )
        return {**record.model_dump(mode="json"), "configuration_started": started}

    @router.get("/modules")
    def modules(user: Annotated[Principal, Depends(principal)]) -> dict:
        return builder_manifest()

    @router.get("/{thread_id}")
    async def get_pipeline(
        thread_id: UUID,
        user: Annotated[Principal, Depends(principal)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict:
        canonical = await owned(thread_id, user, session)
        if not thread_activity.reserve_run(canonical):
            raise HTTPException(409, "Thread deletion is in progress")
        try:
            record = store.get(canonical)
            return {"pipeline": await payload(record, canonical) if record else None}
        except ThreadWorkspaceDeleted as exc:
            raise HTTPException(404, "Chat not found") from exc
        finally:
            thread_activity.release_run(canonical)

    @router.post("/{thread_id}/confirm")
    async def confirm_pipeline(
        thread_id: UUID,
        body: ConfirmPipeline,
        user: Annotated[Principal, Depends(principal)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict:
        canonical = await owned(thread_id, user, session)
        if not thread_activity.reserve_run(canonical):
            raise HTTPException(409, "Thread deletion is in progress")
        try:
            record = store.confirm(
                canonical, body.modules, body.revision, preset=body.preset
            )
            return {
                "pipeline": await payload(record, canonical),
                "message": record.kickoff,
            }
        except PipelineInvalid as exc:
            raise HTTPException(
                422, {"issues": [issue.model_dump() for issue in exc.issues]}
            ) from exc
        except PipelineConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ThreadWorkspaceDeleted as exc:
            raise HTTPException(404, "Chat not found") from exc
        finally:
            thread_activity.release_run(canonical)

    return router
