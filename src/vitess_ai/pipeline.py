"""Pipeline presets, supported topology and confirmed, thread-owned plans."""

from __future__ import annotations

import fcntl
import os
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from vitess_ai.modules.catalog import execution_order, module_spec
from vitess_ai.workspace_lock import hold_thread_workspace

BASE_MODULES = ("readin", "guide", "writeout", "monitor1d", "monitor2d")
PresetId = Literal["guide_test", "isotropic_sample_test"]
PRESETS = {
    "guide_test": {
        "label": "Guide test",
        "description": "Measure the guide output with 1D and 2D monitors and save its trajectories.",
        "defaults": BASE_MODULES,
        "required": BASE_MODULES,
    },
    "isotropic_sample_test": {
        "label": "Isotropic sample test",
        "description": "Scatter the guided beam from an isotropic sample and measure the detector image on screen. Writeout and the monitors are optional.",
        "defaults": ("readin", "guide", "sample_elasticisotr", "screen"),
        "required": ("readin", "guide", "sample_elasticisotr", "screen"),
    },
}
BUILDER_ORDER = execution_order(include_optional=True)
BUILDER_OPTIONAL = frozenset(BUILDER_ORDER) - {"readin", "guide"}
_HINTS = {
    "readin": "Read the staged neutron trajectory files before any other module.",
    "guide": "Transport and shape the incoming beam.",
    "sample_elasticisotr": "Place after guide: downstream outputs measure scattered neutrons (plus any unscattered colours).",
    "writeout": "Save trajectories after the guide and any sample for reuse or inspection. This does not change the beam; screen can run without it.",
    "monitor1d": "Measure a one-dimensional profile at the preceding module's output.",
    "monitor2d": "Measure a two-dimensional profile at the same stage.",
    "capture_flux": "Place after any monitors and before screen: evaluate capture flux at that stage without changing the beam.",
    "screen": "Place before evaluation: propagate to the detector, record its 2D intensity image, and pass on only neutrons that hit it. Separate monitors are not needed for this image.",
    "eval_elast": "Evaluate the arriving beam last. Time-of-flight evaluation requires screen before it.",
}
_LABELS = {"readin": "read_in", "monitor1d": "monitor_1d", "monitor2d": "monitor_2d"}


class PipelineIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    modules: list[str]
    message: str
    correction: str


class PipelineRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    preset: PresetId = "guide_test"
    modules: list[str]
    revision: int = Field(ge=1)
    status: Literal["confirmed", "needs_correction"] = "confirmed"
    issues: list[PipelineIssue] = Field(default_factory=list)

    @property
    def kickoff(self) -> str:
        return (
            "Please configure my confirmed pipeline with me: "
            + " → ".join(_LABELS.get(name, name) for name in self.modules)
            + ". Walk me through each selected module in that order."
        )


class PipelineInvalid(ValueError):
    def __init__(self, issues: list[PipelineIssue]):
        self.issues = issues
        super().__init__(
            "\n".join(f"{item.message} {item.correction}" for item in issues)
        )


class PipelineConflict(ValueError):
    pass


def builder_manifest() -> dict:
    return {
        "default_preset": "guide_test",
        "presets": [
            {
                "id": name,
                **preset,
                "defaults": list(preset["defaults"]),
                "required": list(preset["required"]),
            }
            for name, preset in PRESETS.items()
        ],
        "modules": [
            {
                "name": name,
                "label": _LABELS.get(name, name),
                "description": module_spec(name).description,
                "hint": _HINTS[name],
            }
            for name in BUILDER_ORDER
        ],
    }


def validate_topology(modules: Sequence[str], preset: str = "guide_test") -> None:
    if preset not in PRESETS:
        raise PipelineInvalid(
            [
                PipelineIssue(
                    code="unknown_preset",
                    modules=[],
                    message="Unsupported pipeline preset.",
                    correction="Choose Guide test or Isotropic sample test.",
                )
            ]
        )
    issues: list[PipelineIssue] = []
    unknown = sorted(set(modules) - set(BUILDER_ORDER))
    duplicates = sorted({name for name in modules if modules.count(name) > 1})
    missing = [name for name in PRESETS[preset]["required"] if name not in modules]
    for code, names, message, correction in (
        (
            "unknown_module",
            unknown,
            "Unsupported module.",
            "Remove it and choose a module from the palette.",
        ),
        (
            "duplicate_module",
            duplicates,
            "A module appears more than once.",
            "Keep one instance of each module.",
        ),
        (
            "required_module",
            missing,
            f"Required modules for {PRESETS[preset]['label']} are missing.",
            "Restore the highlighted required modules.",
        ),
    ):
        if names:
            issues.append(
                PipelineIssue(
                    code=code, modules=names, message=message, correction=correction
                )
            )
    expected = [name for name in BUILDER_ORDER if name in modules]
    if not unknown and not duplicates and list(modules) != expected:
        issues.append(
            PipelineIssue(
                code="module_order",
                modules=list(modules),
                message="This order is not supported by the pipeline builder.",
                correction="Reconnect in this order: " + " → ".join(expected),
            )
        )
    if issues:
        raise PipelineInvalid(issues)


def tof_dependency_issues(modules: Sequence[str], *, tof: bool) -> list[PipelineIssue]:
    if (
        tof
        and "eval_elast" in modules
        and (
            "screen" not in modules
            or modules.index("screen") > modules.index("eval_elast")
        )
    ):
        return [
            PipelineIssue(
                code="tof_requires_screen",
                modules=["screen", "eval_elast"],
                message="TOF (bTOF) requires screen before eval_elast, even with path correction disabled.",
                correction="Add screen before eval_elast and confirm the pipeline again; the neutron's flight time must reach the detector.",
            )
        ]
    return []


class PipelineStore:
    """Atomic plan updates, serialized separately from the workspace deletion lock."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).expanduser().resolve()

    def _path(self, thread_id: str) -> Path:
        if str(UUID(thread_id)) != thread_id:
            raise ValueError("thread_id must use canonical UUID form")
        directory = self.root / thread_id
        if directory.is_symlink():
            raise ValueError("Pipeline workspace must not be a symbolic link")
        path = directory / "pipeline.json"
        if path.is_symlink():
            raise ValueError("Pipeline must not be a symbolic link")
        return path

    @contextmanager
    def _locked(self, thread_id: str) -> Iterator[Path]:
        with hold_thread_workspace(self.root, thread_id):
            path = self._path(thread_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(
                path.parent / ".pipeline.lock",
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield path
            finally:
                os.close(fd)

    @staticmethod
    def _read(path: Path) -> PipelineRecord | None:
        return (
            PipelineRecord.model_validate_json(path.read_text())
            if path.exists()
            else None
        )

    @staticmethod
    def _write(path: Path, record: PipelineRecord) -> None:
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=path.parent, delete=False
            ) as stream:
                temporary = stream.name
                stream.write(record.model_dump_json(indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def get(self, thread_id: str) -> PipelineRecord | None:
        # Ordinary chat threads need no builder files or locks created on read.
        if not self._path(thread_id).exists():
            return None
        with self._locked(thread_id) as path:
            return self._read(path)

    def confirm(
        self,
        thread_id: str,
        modules: list[str],
        revision: int | None,
        *,
        preset: PresetId = "guide_test",
    ) -> PipelineRecord:
        validate_topology(modules, preset)
        with self._locked(thread_id) as path:
            previous = self._read(path)
            if previous and previous.status == "confirmed":
                if (
                    previous.preset == preset
                    and previous.modules == modules
                    and revision
                    in (
                        previous.revision,
                        previous.revision - 1,
                        None,
                    )
                ):
                    return previous
                raise PipelineConflict(
                    "This pipeline is confirmed and locked. Start a new design to change it."
                )
            if revision != (previous.revision if previous else None):
                raise PipelineConflict(
                    "The pipeline changed. Reload its current revision before confirming."
                )
            if previous:
                issues = tof_dependency_issues(
                    modules,
                    tof=any(
                        issue.code == "tof_requires_screen" for issue in previous.issues
                    ),
                )
                if issues:
                    raise PipelineInvalid(issues)
            record = PipelineRecord(
                preset=preset,
                modules=modules,
                revision=previous.revision + 1 if previous else 1,
            )
            self._write(path, record)
            return record

    def require_current(
        self, thread_id: str, modules: Sequence[str], revision: int | None
    ) -> PipelineRecord | None:
        record = self.get(thread_id)
        if record is None:
            if revision is not None:
                raise PipelineConflict(
                    "The confirmed pipeline is missing. Return to the canvas."
                )
            return None
        if record.status != "confirmed":
            raise PipelineInvalid(record.issues)
        if record.revision != revision or record.modules != list(modules):
            raise PipelineConflict(
                "The configuration belongs to an older pipeline. Call plan_simulation and configure every selected module again."
            )
        validate_topology(record.modules, record.preset)
        return record

    def invalidate(
        self, thread_id: str, revision: int, issues: list[PipelineIssue]
    ) -> None:
        with self._locked(thread_id) as path:
            record = self._read(path)
            if record and record.revision == revision and record.status == "confirmed":
                self._write(
                    path,
                    record.model_copy(
                        update={"status": "needs_correction", "issues": issues}
                    ),
                )

    def check_module(self, thread_id: str, module: str, parameters: dict) -> None:
        record = self.get(thread_id)
        if record is None:
            return
        if record.status != "confirmed":
            raise PipelineInvalid(record.issues)
        if module not in record.modules:
            raise PipelineConflict(
                f"{module} is not selected in the confirmed pipeline."
            )
        issues = tof_dependency_issues(
            record.modules, tof=module == "eval_elast" and bool(parameters.get("bTOF"))
        )
        if issues:
            self.invalidate(thread_id, record.revision, issues)
            raise PipelineInvalid(issues)
