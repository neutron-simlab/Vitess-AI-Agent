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

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from vitess_ai.modules.catalog import UploadSchema, module_spec, upload_modules

__all__ = [
    "MAGIC_NUMBERS",
    "StagedFile",
    "UploadRefused",
    "UploadStore",
    "upload_module_manifest",
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


def upload_module_manifest() -> tuple[dict[str, Any], ...]:
    """The sidebar contract, projected directly from the catalog rows."""

    return tuple(
        {
            "name": spec.name,
            "label": spec.accepts_upload.label,
            "help": spec.accepts_upload.help,
            "extensions": list(spec.accepts_upload.extensions),
            "max_files": spec.accepts_upload.max_files,
        }
        for spec in upload_modules()
        if spec.accepts_upload is not None
    )


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
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        self._max_bytes = max_bytes
        self._allowed = tuple(
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in allowed_extensions
        )
        if not self._allowed:
            raise ValueError("allowed_extensions must not be empty")

    @property
    def root(self) -> Path:
        return self._root

    @property
    def max_bytes(self) -> int:
        """The largest body the HTTP layer should read for this store."""

        return self._max_bytes

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

        schema = self._require_upload_module(module)
        name = self._safe_name(filename)
        suffix = Path(name).suffix.lower()
        module_extensions = {f".{extension.lower().lstrip('.')}" for extension in schema.extensions}
        accepted = tuple(
            extension for extension in self._allowed if extension in module_extensions
        )
        if suffix not in accepted:
            raise UploadRefused(
                f"{module} does not accept {suffix or 'a file with no extension'}; "
                f"this deployment allows {', '.join(accepted) or 'no file formats'} "
                "in that slot"
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
        existing = [path for path in directory.iterdir() if self._visible_file(path)]
        if len(existing) >= schema.max_files:
            raise UploadRefused(
                f"{module} accepts at most {schema.max_files} staged "
                f"file{'s' if schema.max_files != 1 else ''}; remove one before uploading another"
            )
        resolved = self._write_unused(directory, name, content, original=filename)
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
                if self._visible_file(path):
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

    def delete_thread(self, thread_id: str) -> None:
        """Delete this thread's uploads and simulation outputs."""

        try:
            canonical_thread_id = str(UUID(thread_id))
        except (TypeError, ValueError, AttributeError):
            return
        # Every VITESS writer requires canonical UUIDs. Normalising here would
        # let a legacy/noncanonical chat id delete another chat's workspace.
        if thread_id != canonical_thread_id:
            return

        root = self._root.resolve()
        directory = root / canonical_thread_id
        if directory.is_symlink():
            raise ValueError("Thread workspace must not be a symbolic link")
        if directory.exists():
            shutil.rmtree(directory)

    def _require_upload_module(self, module: str) -> UploadSchema:
        try:
            upload = module_spec(module).accepts_upload
        except KeyError:
            upload = None
        if upload is None:
            known = ", ".join(upload_module_names())
            raise UploadRefused(
                f"{module!r} does not accept an uploaded file. The slots are: {known}"
            )
        return upload

    @staticmethod
    def _visible_file(path: Path) -> bool:
        """A staged input, excluding an interrupted atomic-upload temporary."""

        return path.is_file() and not (
            path.name.startswith(".upload-") and path.name.endswith(".tmp")
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

    def _write_unused(
        self, directory: Path, name: str, content: bytes, *, original: str
    ) -> Path:
        """Publish a complete file under a name no concurrent upload owns.

        Choosing an unused name and then calling ``write_bytes`` is a race: two
        requests can both choose ``beam.dat`` and the second silently replaces
        the first. Write to a hidden file first, then create the visible name
        with an exclusive hard link. A competing request either wins that one
        name or retries with ``beam_1.dat``; neither can overwrite the other.
        """

        temporary = directory / f".upload-{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()

            while True:
                candidate = directory / self._unused_name(directory, name)
                resolved = candidate.resolve()
                if not resolved.is_relative_to(directory.resolve()):
                    raise UploadRefused(
                        f"{original!r} does not name a file in this slot"
                    )
                try:
                    candidate.hardlink_to(temporary)
                except FileExistsError:
                    continue
                return resolved
        finally:
            temporary.unlink(missing_ok=True)
