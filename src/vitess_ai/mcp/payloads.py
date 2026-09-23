"""What the MCP server returns, as models rather than loose dictionaries.

These are the payloads that cross a container boundary, so they are the one
place in this package where pydantic earns its keep: the server builds them and
the application validates what arrives (03/CP3a). A shared volume shares files,
not Python objects -- everything the application learns about an execution it
learns from here.

Every model sets ``extra="forbid"``. The two sides ship in one image, so they
cannot legitimately disagree about the fields; if they ever do, a loud
validation error is the failure worth having.

Paths are **relative to the run directory**. The application resolves them under
its own mount rather than trusting an absolute path from another container, and
the two containers agree on ``/data/projects`` precisely because nothing relies
on that agreement.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CaptureFluxReading",
    "FileKind",
    "FlatnessReading",
    "ModuleExecution",
    "RunFile",
    "SimulationResult",
    "PlotResult",
    "UploadedFile",
    "ModuleUploads",
    "RunFolder",
    "ThreadInspection",
]

#: A delivery hint for the application, decided by file extension and one known
#: name. Deliberately not a physics claim: which file holds monitor data is
#: known from the parameters that asked for it, not from guessing at a name the
#: user chose.
FileKind = Literal["plot", "log", "data"]


class _Payload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModuleExecution(_Payload):
    """One VITESS process, as the server observed it.

    This is the evidence behind ``<verified_by_server>``: an exit code the
    server read from a process it started, not a sentence a model wrote.
    """

    name: str
    #: The resolved absolute path, e.g. ``/vitess/MODULES/read_in`` -- never
    #: ``$V/read_in``, which is a shell variable that expands to nothing.
    executable: str
    #: ``None`` only if a process could not be reaped, which is a failure.
    exit_code: int | None
    started_at: str
    ended_at: str
    #: Bounded. A failing module can produce megabytes, and none of it should
    #: reach a model's context.
    stdout_tail: str
    stderr_tail: str


class RunFile(_Payload):
    """A file the run produced, named relative to the run directory."""

    path: str
    kind: FileKind
    size_bytes: int = Field(ge=0)


class CaptureFluxReading(_Payload):
    """What capture_flux printed to the simulation log, read back by the server.

    The numbers are capture_flux's own (capture_flux.c:166,172-173), not a
    recomputation: the application reports them, it does not derive them.
    """

    #: n/s, weighted by lambda / lambda_ref unless the reference wavelength is 0.
    captured_intensity: float
    captured_intensity_error: float
    #: How many trajectories hit the foil and the wavelength window.
    trajectories: int = Field(ge=0)
    #: n/(s*cm^2): the captured intensity over the foil area (1 cm^2 with no foil).
    capture_flux: float
    capture_flux_error: float
    #: Angstrom; 0 means no reference wavelength was used.
    reference_wavelength: float


class FlatnessReading(_Payload):
    """Whether the horizontal 1D profile is flat across the sample.

    Judged by the server from the run's monitor1D file; the criterion and the
    noise rule are in :mod:`vitess_ai.mcp.profile_flatness`.
    """

    #: ``wrong_binning``: the file's bins do not tile the window in 0.1 cm
    #: bins, so nothing was judged and the numbers below are ``None``.
    verdict: Literal["pass", "fail", "inconclusive", "wrong_binning"]
    #: cm, as read from the file.
    bin_width_cm: float
    #: Bins inside the window that received no intensity: a hole in the beam.
    empty_bins: int = Field(default=0, ge=0)
    #: (I - mean) / mean of the bin furthest from the window mean, signed.
    worst_deviation: float | None = None
    #: cm, the centre of that bin.
    worst_position_cm: float | None = None
    #: Median of error / intensity over the window's non-empty bins.
    median_relative_error: float | None = None


class SimulationResult(_Payload):
    """The result of one VITESS pipeline, successful or not.

    A failure is reported here, with its evidence, rather than raised: a
    simulation that ran and failed is information the model needs. Malformed
    *arguments* raise instead -- those come from trusted application code, so
    they are a bug rather than an outcome.
    """

    success: bool
    timed_out: bool
    thread_id: str
    simulation_run_id: str
    #: Empty when command generation refused: nothing was started.
    modules: tuple[ModuleExecution, ...] = ()
    files: tuple[RunFile, ...] = ()
    message: str
    #: ``None`` when the log holds no capture_flux result, e.g. the module failed
    #: before printing one.
    capture_flux: CaptureFluxReading | None = None
    #: ``None`` unless the run succeeded and its 1D monitor recorded pos_y.
    flatness: FlatnessReading | None = None


class PlotResult(_Payload):
    """A PNG rendered from a monitor data file.

    PNG rather than Plotly JSON because the application registers it with the
    same artifact store that already delivers images into the chat. Interactive
    plots are a separate contract, if they are ever wanted.
    """

    kind: Literal["monitor1d", "monitor2d"]
    #: The monitor data file that was read, relative to the run directory.
    source: str
    #: The PNG that was written, relative to the run directory.
    path: str
    size_bytes: int = Field(ge=0)
    title: str
    x_label: str
    y_label: str
    message: str


class UploadedFile(_Payload):
    """One staged input file, named relative to the thread directory."""

    path: str
    size_bytes: int = Field(ge=0)
    modified_at: str


class ModuleUploads(_Payload):
    """What is staged for one module that accepts uploads."""

    module: str
    files: tuple[UploadedFile, ...] = ()


class RunFolder(_Payload):
    """One ``outputs/<simulation_run_id>/`` directory."""

    simulation_run_id: str
    files: tuple[UploadedFile, ...] = ()


class ThreadInspection(_Payload):
    """Everything on the volume for one conversation.

    ``exists`` false with empty lists is a normal state -- a conversation that
    has not uploaded anything yet -- and not an error.
    """

    thread_id: str
    exists: bool
    uploads: tuple[ModuleUploads, ...] = ()
    runs: tuple[RunFolder, ...] = ()
    message: str
