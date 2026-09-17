"""Core's client, plus the four upload routes that are this application's.

`BaseAgentClient` already covers chats, streaming, resume, artifacts and
interrupts -- the whole SSE contract. What it cannot know is `/files`, because
staged input files are a VITESS idea: a real path on a shared volume that a
compiled binary opens. `client_class` is the seam core provides for exactly
this, and using it keeps the common constructor in one place without teaching
core which extra endpoints a subclass owns.

The UI never touches the volume directly. It is a separate process from the
API -- in production a separate container -- and the only reason a path works
at all is that both containers mount the same volume at the same place. Going
through the route is what keeps one definition of which module a file belongs
to, what may be uploaded, and how big it may be.
"""

from __future__ import annotations

from typing import Any

from juena_core.clients.base import BaseAgentClient

__all__ = ["VitessClient"]


class VitessClient(BaseAgentClient):
    """Everything core's client does, and the staged-file routes."""

    def upload_modules(self) -> list[str]:
        """The slots the server will accept a file for, in catalog order."""

        response = self._client.get(f"{self.base_url}/files/modules", headers=self._headers())
        response.raise_for_status()
        return list(response.json().get("modules", []))

    def list_staged(self, thread_id: str, module: str | None = None) -> list[dict[str, Any]]:
        """What is staged for one conversation. This is what the manifest shows."""

        response = self._client.get(
            f"{self.base_url}/files/{thread_id}",
            params={"module": module} if module else None,
            headers=self._headers(),
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
            headers=self._headers(),
        )
        response.raise_for_status()
        return dict(response.json())

    def remove_staged(self, thread_id: str, module: str, filename: str) -> None:
        """Remove one staged file, which is how a wrong slot is corrected."""

        response = self._client.delete(
            f"{self.base_url}/files/{thread_id}/{module}/{filename}",
            headers=self._headers(),
        )
        response.raise_for_status()
