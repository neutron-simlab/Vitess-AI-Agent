"""Staged input files, written to the volume the VITESS binaries read.

**This is not juena-chatbot's staged-input model, and it must not become it.**
There, an attachment is decoded to text and lives in graph state under
`/inputs/`, which is right for a model that reads it. Here the reader is
`read_in`, a compiled binary that opens a path. So an upload is a real file at

    {project}/{thread_id}/uploads/{module}/{filename}

and the same volume is mounted in the MCP container, which is what makes a path
written here meaningful there.

Two consequences follow, and both are load-bearing:

*Binary files are fine here and nowhere else.* `.h5` and `.nxs` are HDF5, and
juena's chat-attachment path decodes with `raw.decode("utf-8-sig")` -- it would
throw or mangle them into the transcript. This path never decodes; it writes
bytes. It therefore needs its own policy rather than a shared text validator: a
size ceiling, an extension allowlist and, for the binary formats, a magic number.

*The destination is asked for, not guessed.* `module` is required. A trajectory
file landing in the guide slot produces a simulation that runs, completes and is
physically wrong -- the same class of failure 03/CP1 removed from command
generation, and not one to reintroduce at the upload step.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from vitess_ai.modules.catalog import upload_modules

__all__ = [
    "MAGIC_NUMBERS",
    "StagedFile",
    "UploadRefused",
    "UploadStore",
    "upload_module_names",
]


class UploadRefused(ValueError):
    """The upload was not written, and this says why in the user's terms."""


#: What the first bytes of a format must be. Only the binary containers are
#: here: a `.dat` file is whatever a neutron scientist's tool wrote, and there
#: is no signature to check.
MAGIC_NUMBERS: dict[str, bytes] = {
    ".h5": b"\x89HDF\r\n\x1a\n",
    ".nxs": b"\x89HDF\r\n\x1a\n",
}


def upload_module_names() -> tuple[str, ...]:
    """The slots that exist, from the catalog and from nowhere else.

    The first-generation store carried `FALLBACK_MODULE_TYPES`, a second copy of
    this list used whenever the catalog import failed -- and the catalog import
    failed because loading it dragged in LangChain (03/CP2). The import cannot
    fail now, and a store that cannot name its slots is a broken install rather
    than a condition to degrade through.
    """
    return tuple(spec.name for spec in upload_modules())


@dataclass(frozen=True)
class StagedFile:
    """One file on the volume, described the way both ends need it."""

    thread_id: UUID
    module: str
    filename: str
    #: Absolute, and inside the thread's own directory. This is what goes into
    #: a parameter field, so it is the path the binary will open.
    path: Path
    size_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "thread_id": str(self.thread_id),
            "module": self.module,
            "filename": self.filename,
            "path": str(self.path),
            "size_bytes": self.size_bytes,
        }


class UploadStore:
    """Read and write one deployment's staged inputs."""

    def __init__(
        self,
        project_root: Path,
        *,
        max_bytes: int,
        allowed_extensions: tuple[str, ...],
    ) -> None:
        self._root = Path(project_root)
        self._max_bytes = max_bytes
        self._allowed = tuple(extension.lower() for extension in allowed_extensions)

    @property
    def root(self) -> Path:
        return self._root

    def directory(self, thread_id: UUID, module: str) -> Path:
        """Where this module's files for this thread live.

        `thread_id` is a `UUID` in the signature rather than a string that is
        checked, so a caller cannot pass `../..` at all: FastAPI rejects it
        before the route body runs, and no other caller can construct one.
        """
        self._require_upload_module(module)
        return self._root / str(thread_id) / "uploads" / module

    def stage(
        self, content: bytes, *, filename: str, thread_id: UUID, module: str
    ) -> StagedFile:
        """Write one file, or refuse and write nothing."""

        self._require_upload_module(module)
        name = self._safe_name(filename)
        suffix = Path(name).suffix.lower()
        if suffix not in self._allowed:
            raise UploadRefused(
                f"{suffix or 'a file with no extension'} is not an input format "
                f"this deployment accepts; it takes {', '.join(self._allowed)}"
            )
        if len(content) > self._max_bytes:
            raise UploadRefused(
                f"{name} is {len(content)} bytes, over the {self._max_bytes}-byte "
                "limit for one input file"
            )
        if not content:
            raise UploadRefused(f"{name} is empty")
        expected = MAGIC_NUMBERS.get(suffix)
        if expected is not None and not content.startswith(expected):
            raise UploadRefused(
                f"{name} is named {suffix} but does not begin with the HDF5 "
                "signature, so the VITESS reader would not recognise it"
            )

        directory = self.directory(thread_id, module)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / self._unused_name(directory, name)
        # Belt and braces: `_safe_name` already reduced the name to its last
        # component, so this cannot fail. It is here because the cost of being
        # wrong is a write outside the thread's directory.
        resolved = path.resolve()
        if not resolved.is_relative_to(directory.resolve()):
            raise UploadRefused(f"{filename!r} does not name a file in this slot")
        resolved.write_bytes(content)
        return StagedFile(
            thread_id=thread_id,
            module=module,
            filename=resolved.name,
            path=resolved,
            size_bytes=len(content),
        )

    def staged(self, thread_id: UUID, module: str | None = None) -> list[StagedFile]:
        """Everything staged for one thread, in catalog order then by name."""

        modules = (module,) if module is not None else upload_module_names()
        found: list[StagedFile] = []
        for name in modules:
            directory = self.directory(thread_id, name)
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if path.is_file():
                    found.append(
                        StagedFile(
                            thread_id=thread_id,
                            module=name,
                            filename=path.name,
                            path=path,
                            size_bytes=path.stat().st_size,
                        )
                    )
        return found

    def remove(self, thread_id: UUID, module: str, filename: str) -> bool:
        """Delete one staged file. Returns whether there was one."""

        path = self.directory(thread_id, module) / self._safe_name(filename)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def _require_upload_module(self, module: str) -> None:
        if module not in upload_module_names():
            known = ", ".join(upload_module_names())
            raise UploadRefused(
                f"{module!r} does not accept an uploaded file. The slots are: {known}"
            )

    @staticmethod
    def _safe_name(filename: str) -> str:
        name = Path(filename).name.strip()
        if not name or name in {".", ".."}:
            raise UploadRefused(f"{filename!r} is not a usable file name")
        return name

    @staticmethod
    def _unused_name(directory: Path, name: str) -> str:
        """`beam.dat`, then `beam_1.dat` -- never a UUID in front of the name.

        The person who uploaded it has to recognise it in a parameter field and
        in the sidebar, and `a3f9…-beam.dat` is not a file anyone recognises.
        """
        candidate = name
        stem, suffix = Path(name).stem, Path(name).suffix
        index = 1
        while (directory / candidate).exists():
            candidate = f"{stem}_{index}{suffix}"
            index += 1
        return candidate
