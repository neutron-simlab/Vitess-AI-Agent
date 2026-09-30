"""In-process API client for the canvas browser harness."""

import tempfile
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from juena_core.server.api.endpoints import ThreadActivity
from juena_core.server.chat.repository import ChatNotFoundError
from juena_core.server.database.connection import get_db_session

from vitess_ai.clients import VitessClient
from vitess_ai.pipeline import PipelineStore
from vitess_ai.server import pipeline_endpoints


class BrowserClient(VitessClient):
    def __init__(self):
        super().__init__("http://testserver", agent="vitess")
        self.close()
        self.chats = {}
        self.messages = {}
        self.checkpoints = {}
        self.store = PipelineStore(tempfile.mkdtemp(prefix="vitess-browser-"))
        self.reject_once = False
        self.lose_response_once = False
        self.pause_handoff_once = False

        async def owned(session, user_id, thread_id, *, agent_id):
            if thread_id not in self.chats:
                raise ChatNotFoundError("Chat not found")

        async def db():
            yield None

        async def checkpoint(config):
            return self.checkpoints.get(config["configurable"]["thread_id"])

        pipeline_endpoints.get_owned_chat = owned
        pipeline_endpoints.get_checkpointer = lambda: SimpleNamespace(aget=checkpoint)
        app = FastAPI()
        app.dependency_overrides[get_db_session] = db
        app.include_router(
            pipeline_endpoints.build_pipeline_router(
                lambda: SimpleNamespace(id=uuid4()),
                self.store,
                thread_activity=ThreadActivity(),
            )
        )
        self.api = TestClient(app)

        # Starlette's TestClient uses httpx2; the production client uses httpx.
        # Keep the real client's response and exception types in this harness.
        def send(request):
            response = self.api.request(
                request.method,
                str(request.url),
                content=request.content,
                headers=dict(request.headers),
            )
            return httpx.Response(
                response.status_code,
                content=response.content,
                headers=dict(response.headers),
            )

        self._client = httpx.Client(transport=httpx.MockTransport(send))

    def get_chat(self, thread_id, *, include_messages=False):
        return self.chats.get(thread_id)

    def create_chat(self, thread_id, *, agent_id, title):
        self.chats[thread_id] = {"agent_id": agent_id, "title": title}

    def get_pending_interrupt(self, *args, **kwargs):
        return None

    def confirm_pipeline(self, thread_id, modules, revision, *, preset="guide_test"):
        if self.reject_once:
            self.reject_once = False
            modules = list(reversed(modules))
        result = super().confirm_pipeline(thread_id, modules, revision, preset=preset)
        if self.lose_response_once:
            self.lose_response_once = False
            raise httpx.ReadTimeout("The confirmation response was lost after saving.")
        return result
