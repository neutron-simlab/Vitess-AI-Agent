"""Read a VITESS monitor data file, in any layout the schema can ask for.

A monitor file is what a simulation is *for*: the 1D and 2D monitors write the
intensity they recorded, and everything a scientist looks at afterwards comes
from here.

Every layout below was measured against files written by VITESS 3.8's own
``monitor1D`` and ``monitor2D`` -- the fixtures under ``tests/data/`` are those
files. That matters, because the format is not one format:

- **1D** is always four columns: bin centre, intensity, error, trajectories.
- **2D** has five, chosen by ``Monitor2DParameters.format`` (``-F``).
  ``matrix``, ``matrix_compact`` and ``matrix_integer`` write a row of x bin
  centres and then one row per y bin -- **intensity only, no error and no
  trajectory count**. ``xyz`` and ``xyz_compact`` write one row per cell, five
  columns wide, keeping all three. The schema's default is ``matrix``.

  ``matrix_integer`` differs again: its numbers are detector *counts* over the
  source's measurement time, not a count rate in n/s, even though VITESS writes
  the same "n/s" in the title. This reader returns what the file holds; a
  caller that mixes the two is comparing counts with rates.

Which is why this is not a port of the first-generation reader. That reader
assumed the matrix layout, so an ``xyz`` file made it build a ragged array; and
it was off by one in *both* layouts, taking the first row of data as an axis in
2D and starting at the second bin in 1D. A dropped first bin is a real
measurement missing from a plot, and nothing said so.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

__all__ = ["MonitorData", "MonitorFileError", "MonitorKind", "read_monitor_file"]

MonitorKind = Literal["monitor1d", "monitor2d"]

#: Columns in a 1D row: bin centre, intensity, error, trajectories.
COLUMNS_1D = 4
#: Columns in a 2D ``xyz`` row: x centre, y centre, intensity, error, trajectories.
COLUMNS_2D_XYZ = 5


class MonitorFileError(ValueError):
    """The file is not a monitor file, or not one this reader understands.

    Raised rather than returned. A monitor file that cannot be read means the
    plot the user asked for does not exist, and a caller that carried on would
    be drawing something else.
    """


@dataclass(frozen=True)
class MonitorData:
    """One monitor file, parsed into bin centres and a grid of intensities.

    ``intensity`` is one value per bin for a 1D monitor, and one value per cell
    -- indexed ``[y, x]`` -- for a 2D one. ``error`` and ``trajectories`` have
    the same shape, or are ``None`` for the 2D matrix layouts, which do not
    write them.
    """

    kind: MonitorKind
    title: str
    x_label: str
    y_label: str
    x: np.ndarray
    y: np.ndarray | None
    intensity: np.ndarray
    error: np.ndarray | None
    trajectories: np.ndarray | None


def _header_value(header_lines: list[str], key: str) -> str | None:
    """Return the value of ``# <key> : <value>``, or None.

    Matched on the key before the first colon rather than by searching the whole
    line, so a value that happens to contain the word is not mistaken for a
    label.
    """
    for line in header_lines:
        body = line.lstrip("#").strip()
        name, separator, value = body.partition(":")
        if separator and name.strip() == key:
            # Titles end in a colon of their own ("1D Monitor:").
            return value.strip().rstrip(":").strip()
    return None


def _detect_kind(header_lines: list[str]) -> MonitorKind:
    title = header_lines[0]
    if "2D" in title:
        return "monitor2d"
    if "1D" in title:
        return "monitor1d"
    raise MonitorFileError(
        f"First header line names neither a 1D nor a 2D monitor: {title!r}"
    )


def _numbers(source: Path, number: int, line: str) -> list[float]:
    try:
        return [float(field) for field in line.split()]
    except ValueError as exc:
        raise MonitorFileError(
            f"{source} line {number} is not numeric: {line!r}"
        ) from exc


def _read_1d(source: Path, rows: list[tuple[int, list[float]]]) -> dict[str, np.ndarray]:
    for number, values in rows:
        if len(values) != COLUMNS_1D:
            raise MonitorFileError(
                f"{source} line {number}: expected {COLUMNS_1D} columns for a "
                f"1D monitor, found {len(values)}"
            )
    table = np.array([values for _, values in rows], dtype=float)
    return {
        "x": table[:, 0],
        "y": None,
        "intensity": table[:, 1],
        "error": table[:, 2],
        "trajectories": table[:, 3],
    }


def _read_2d_matrix(
    source: Path, rows: list[tuple[int, list[float]]]
) -> dict[str, np.ndarray]:
    """First row is the x bin centres; each later row is a y centre then its bins."""
    x = np.array(rows[0][1], dtype=float)
    expected = x.size + 1
    for number, values in rows[1:]:
        if len(values) != expected:
            raise MonitorFileError(
                f"{source} line {number}: a matrix row should hold a y centre and "
                f"{x.size} intensities, found {len(values)} values"
            )
    table = np.array([values for _, values in rows[1:]], dtype=float)
    return {
        "x": x,
        "y": table[:, 0],
        "intensity": table[:, 1:],
        # The matrix layouts write intensity alone. Saying so beats inventing
        # zeros that would plot as certainty.
        "error": None,
        "trajectories": None,
    }


def _read_2d_xyz(
    source: Path, rows: list[tuple[int, list[float]]]
) -> dict[str, np.ndarray]:
    """One row per cell; pivoted here so callers see a grid either way."""
    table = np.array([values for _, values in rows], dtype=float)
    x = np.unique(table[:, 0])
    y = np.unique(table[:, 1])
    if x.size * y.size != table.shape[0]:
        raise MonitorFileError(
            f"{source}: {x.size} x {y.size} cells expected, {table.shape[0]} rows "
            "present; the file is incomplete"
        )
    column = np.searchsorted(x, table[:, 0])
    row = np.searchsorted(y, table[:, 1])

    def grid(values: np.ndarray) -> np.ndarray:
        placed = np.zeros((y.size, x.size), dtype=float)
        placed[row, column] = values
        return placed

    return {
        "x": x,
        "y": y,
        "intensity": grid(table[:, 2]),
        "error": grid(table[:, 3]),
        "trajectories": grid(table[:, 4]),
    }


def _read_2d(source: Path, rows: list[tuple[int, list[float]]]) -> dict[str, np.ndarray]:
    """Decide the layout from the first two rows, then let that reader check.

    A matrix file opens with the x bin centres and every later row is one value
    wider, for the y centre it starts with; an xyz file is five columns
    throughout. Deciding on the first two rows rather than on every width means
    a corrupt row *inside* a matrix file is reported as a bad row, at its line
    number, instead of as an unrecognisable file.
    """
    widths = [len(values) for _, values in rows]
    if len(widths) > 1 and widths[0] + 1 == widths[1]:
        return _read_2d_matrix(source, rows)
    if set(widths) == {COLUMNS_2D_XYZ}:
        return _read_2d_xyz(source, rows)
    raise MonitorFileError(
        f"{source}: rows are {sorted(set(widths))} values wide, which is neither "
        f"the {COLUMNS_2D_XYZ}-column xyz layout nor a matrix whose first row is "
        "the x bin centres"
    )


def read_monitor_file(path: str | Path) -> MonitorData:
    """Parse a monitor file, or raise :class:`MonitorFileError`."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise MonitorFileError(f"Cannot read {source}: {exc}") from exc

    header_lines: list[str] = []
    data_lines: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            header_lines.append(stripped)
        else:
            data_lines.append((number, stripped))

    if not header_lines:
        raise MonitorFileError(f"{source} has no header; it is not a monitor file")
    if not data_lines:
        raise MonitorFileError(f"{source} has a header but no data rows")

    kind = _detect_kind(header_lines)
    # Collected, not written into an array sized from the line count: such an
    # array keeps its shape even if a row is dropped, and "every row is here" is
    # exactly what this reader has to guarantee.
    rows = [(number, _numbers(source, number, line)) for number, line in data_lines]
    arrays = _read_1d(source, rows) if kind == "monitor1d" else _read_2d(source, rows)

    return MonitorData(
        kind=kind,
        title=_header_value(header_lines, "title") or source.name,
        x_label=_header_value(header_lines, "x_label") or "x",
        y_label=_header_value(header_lines, "y_label") or "intensity",
        **arrays,
    )
