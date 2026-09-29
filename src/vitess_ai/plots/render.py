"""Draw a monitor file as a PNG image.

A PNG, not an interactive Plotly chart: the image is registered with the same
store for generated files that already delivers pictures into the chat, so a
plot arrives like every other generated file -- with a download button and a
record of who may see it. The first version sent a Plotly chart as JSON inside
the tool result, which only its own page could draw.

Matplotlib is used directly, drawing into memory with its Agg canvas, rather
than through ``pyplot``. ``pyplot`` keeps a global list of open figures that
leaks between requests in a server that runs for a long time, and it expects a
screen to draw on.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from vitess_ai.plots.monitor_file import MonitorData

__all__ = ["render_monitor_png"]

FIGURE_SIZE = (8.0, 5.0)
FIGURE_DPI = 120


def _draw_1d(figure: Figure, data: MonitorData) -> None:
    axes = figure.subplots()
    width = float(data.x[1] - data.x[0]) if data.x.size > 1 else 1.0
    axes.bar(data.x, data.intensity, width=width, color="black", alpha=0.3)
    axes.errorbar(
        data.x,
        data.intensity,
        yerr=None if data.error is None else np.abs(data.error),
        linestyle="none",
        capsize=2,
        alpha=0.6,
        color="black",
    )
    axes.set_xlabel(data.x_label)
    # The file's own header, not a hardcoded "Intensity [n/s]": a monitor says
    # what it measured, and monitor1D can be configured to measure polarisation.
    axes.set_ylabel(data.y_label)
    axes.set_title(data.title)
    axes.grid(alpha=0.3)


def _draw_2d(figure: Figure, data: MonitorData) -> None:
    assert data.y is not None  # guaranteed by the parser for a 2D monitor
    axes = figure.subplots()
    # `shading="nearest"` because the file gives bin *centres*, not edges. With
    # the default the grid is offset by half a bin and everything looks shifted.
    mesh = axes.pcolormesh(data.x, data.y, data.intensity, shading="nearest")
    figure.colorbar(mesh, ax=axes, label="Intensity")
    axes.set_xlabel(data.x_label)
    axes.set_ylabel(data.y_label)
    axes.set_title(data.title)


def render_monitor_png(data: MonitorData, destination: str | Path) -> Path:
    """Write ``data`` to ``destination`` as a PNG and return the path."""
    figure = Figure(figsize=FIGURE_SIZE, dpi=FIGURE_DPI, layout="tight")
    FigureCanvasAgg(figure)
    if data.kind == "monitor1d":
        _draw_1d(figure, data)
    else:
        _draw_2d(figure, data)

    target = Path(destination)
    figure.savefig(target, format="png")
    return target
