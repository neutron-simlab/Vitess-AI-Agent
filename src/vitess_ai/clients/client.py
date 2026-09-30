"""Core's API client, plus the four file-upload routes only VITESS needs.

`BaseAgentClient` from juena-core already covers chats, streamed replies,
resuming a paused chat, generated files and questions to the user. What it
cannot know about is `/files`, because uploaded input files are a VITESS idea:
a real file on a shared volume that a compiled program opens. Core's
`client_class` option exists for exactly this kind of addition, so the shared
setup code stays in core, and core does not need to know which extra routes a
subclass adds.

The web page never touches the volume itself. It runs as a separate process
from the API (a separate container in production), and a file path only works
at all because both containers mount the same volume at the same place. Going
through the API keeps one set of rules for which module a file belongs to, what
may be uploaded and how big it may be.
"""

from __future__ import annotations

from typing import Any

from juena_core.clients.base import BaseAgentClient

__all__ = ["VitessClient"]


class VitessClient(BaseAgentClient):
    """Everything core's client does, and the staged-file routes."""

    def pipeline_modules(self) -> dict[str, Any]:
        response = self._client.get(f"{self.base_url}/pipelines/modules", headers=self._headers)
        response.raise_for_status()
        return response.json()

    def get_pipeline(self, thread_id: str) -> dict[str, Any] | None:
        response = self._client.get(f"{self.base_url}/pipelines/{thread_id}", headers=self._headers)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()["pipeline"]

    def confirm_pipeline(
        self, thread_id: str, modules: list[str], revision: int | None,
        *, preset: str = "guide_test",
    ) -> dict[str, Any]:
        response = self._client.post(
            f"{self.base_url}/pipelines/{thread_id}/confirm",
            json={"modules": modules, "revision": revision, "preset": preset}, headers=self._headers,
        )
        response.raise_for_status()
        return response.json()

    def upload_modules(self) -> list[dict[str, Any]]:
        """The server-owned slot manifest, in catalog order."""

        response = self._client.get(f"{self.base_url}/files/modules", headers=self._headers)
        response.raise_for_status()
        return [dict(item) for item in response.json().get("modules", [])]

    def list_staged(self, thread_id: str, module: str | None = None) -> list[dict[str, Any]]:
        """What is staged for one conversation. This is what the manifest shows."""

        response = self._client.get(
            f"{self.base_url}/files/{thread_id}",
            params={"module": module} if module else None,
            headers=self._headers,
        )
        if response.status_code == 404:
            # An unsent conversation has no chat row yet, which is not an error
            # to show anybody: it simply has nothing staged.
            return []
        response.raise_for_status()
        return list(response.json().get("files", []))

    def stage_file(
        self, thread_id: str, module: str, filename: str, content: bytes
    ) -> dict[str, Any]:
        """Write one input file into a module's slot.

        Raises `httpx.HTTPStatusError` on refusal; the server's 422 detail is
        written for the person who chose the file, so callers show it verbatim
        rather than substituting a generic message.
        """
        response = self._client.post(
            f"{self.base_url}/files/{thread_id}/{module}",
            files={"upload": (filename, content)},
            headers=self._headers,
        )
        response.raise_for_status()
        return dict(response.json())

    def remove_staged(self, thread_id: str, module: str, filename: str) -> None:
        """Remove one staged file, which is how a wrong slot is corrected."""

        response = self._client.delete(
            f"{self.base_url}/files/{thread_id}/{module}/{filename}",
            headers=self._headers,
        )
        response.raise_for_status()
