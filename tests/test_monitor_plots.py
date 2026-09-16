"""Reading and drawing monitor files, against files VITESS actually wrote.

Every fixture under ``tests/data/`` was produced by VITESS 3.8's own binaries --
see ``tests/data/README.md`` for the command. That matters more here than
anywhere else in this repository: the first-generation reader was written
against a remembered format and was wrong about every layout, and no
hand-written fixture would have shown it, because a hand-written fixture would
have been written to match the reader.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vitess_ai.plots import MonitorFileError, read_monitor_file, render_monitor_png
from vitess_ai.schema.base import VtFormat2D

DATA = Path(__file__).parent / "data"
MONITOR_1D = DATA / "monitor1D.dat"

#: One fixture per value of `Monitor2DParameters.format`, which is what decides
#: the layout. The names say which: F0 matrix, F1 xyz, F2 matrix_compact,
#: F3 xyz_compact.
MONITOR_2D = {
    format_: DATA / f"monitor2D-F{format_.value}.dat"
    for format_ in VtFormat2D
    if format_ is not VtFormat2D.NO_2D_FORMAT
}

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _data_row_count(path: Path) -> int:
    """Count rows from the file itself, so the expectation is not a copy."""
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


def test_the_1d_reader_keeps_every_bin_the_file_has() -> None:
    """The bug this reader was rewritten to remove.

    The first-generation reader started at the second data row and a second copy
    of it started at the third, so the first one or two bins of every 1D monitor
    were silently discarded -- a real measurement, missing from the plot.
    """
    data = read_monitor_file(MONITOR_1D)

    assert data.kind == "monitor1d"
    assert data.x.size == _data_row_count(MONITOR_1D)
    assert data.x[0] == pytest.approx(0.25)


def test_the_1d_columns_are_read_in_the_order_the_file_writes_them() -> None:
    """Intensity, error and trajectory count are three different columns.

    Asserted on the bins with signal: the fixture's beam covers 1.25 to 9.75 A,
    where each bin holds an intensity around 4e9 n/s, an error two orders of
    magnitude smaller, and several hundred trajectories. Swap any two columns
    and those three ranges disagree.
    """
    data = read_monitor_file(MONITOR_1D)
    assert data.error is not None and data.trajectories is not None
    lit = data.intensity > 0

    assert np.all(data.intensity[lit] > 1e9)
    assert np.all(data.error[lit] < data.intensity[lit] / 10)
    assert np.all(data.trajectories[lit] > 100)
    assert data.x[lit].min() == pytest.approx(1.25)
    assert data.x[lit].max() == pytest.approx(9.75)


def test_the_reader_covers_every_2d_layout_the_schema_can_ask_for() -> None:
    """The gap this checkpoint found.

    `Monitor2DParameters.format` offers four writable layouts and defaults to
    `matrix`, while the reader had been written for `xyz` alone -- so the
    default would have produced a named failure on a perfectly good file.
    """
    assert {format_.value for format_ in MONITOR_2D} == {0, 1, 2, 3, 4}
    for format_, path in MONITOR_2D.items():
        assert path.is_file(), f"no fixture for {format_.name}"


RATE_FORMATS = [
    VtFormat2D.MATRIX,
    VtFormat2D.XYZ,
    VtFormat2D.MATR_CMPT,
    VtFormat2D.XYZ_CMPT,
]


@pytest.mark.parametrize("format_", RATE_FORMATS, ids=lambda f: f.name)
def test_every_2d_rate_layout_reads_back_the_same_measurement(
    format_: VtFormat2D,
) -> None:
    """Four files, one simulation: the grids have to agree.

    They are written by the same run of the same binary, so a reader that gets
    one layout subtly wrong -- an off-by-one, a transposed grid -- disagrees
    with the others. `matrix_compact` rounds its numbers, hence the tolerance.
    """
    reference = read_monitor_file(MONITOR_2D[VtFormat2D.XYZ])
    data = read_monitor_file(MONITOR_2D[format_])

    assert data.kind == "monitor2d"
    assert data.y is not None
    assert data.intensity.shape == (data.y.size, data.x.size) == (12, 12)
    assert data.intensity == pytest.approx(reference.intensity, rel=1e-3)
    # The compact layouts round bin centres to one decimal, so they can sit
    # half a step (0.05) away from the full-precision ones.
    assert data.x == pytest.approx(reference.x, abs=0.06)
    assert data.y == pytest.approx(reference.y, abs=0.06)


def test_the_integer_layout_holds_counts_rather_than_a_rate() -> None:
    """`matrix_integer` multiplies by the measurement time and rounds.

    VITESS writes "n/s" in its title either way, so nothing in the file says
    so except the numbers. One constant ratio across every lit cell is what a
    measurement time looks like; anything else would mean the grids disagree.
    """
    counts = read_monitor_file(MONITOR_2D[VtFormat2D.MATR_INT])
    rate = read_monitor_file(MONITOR_2D[VtFormat2D.XYZ])
    lit = rate.intensity > 0

    ratio = counts.intensity[lit] / rate.intensity[lit]
    assert np.allclose(ratio, ratio[0], rtol=1e-3)
    assert ratio[0] > 1
    assert np.all(counts.intensity == np.round(counts.intensity))


def test_the_matrix_layouts_say_they_carry_no_error() -> None:
    """Rather than inventing zeros, which would plot as certainty."""
    matrix = read_monitor_file(MONITOR_2D[VtFormat2D.MATRIX])
    xyz = read_monitor_file(MONITOR_2D[VtFormat2D.XYZ])

    assert matrix.error is None and matrix.trajectories is None
    assert xyz.error is not None and xyz.trajectories is not None


def test_the_2d_beam_is_where_the_simulation_put_it() -> None:
    """The fixture's source is 2 cm wide and 2 cm high, centred on the axis.

    Read the grid the wrong way round and the beam is still centred -- so this
    also checks that the lit cells are the ones whose own centres are inside it.
    """
    data = read_monitor_file(MONITOR_2D[VtFormat2D.XYZ])
    assert data.y is not None
    x_grid, y_grid = np.meshgrid(data.x, data.y)
    inside = (np.abs(x_grid) < 1.0) & (np.abs(y_grid) < 1.0)

    assert np.all(data.intensity[inside] > 0)
    assert np.all(data.intensity[~inside] == 0)


def test_labels_and_title_come_from_the_file_header() -> None:
    """A monitor says what it measured; nothing here decides that for it."""
    data = read_monitor_file(MONITOR_1D)

    assert data.title == "1D Monitor"
    assert data.x_label == "lambda [Ang]"
    assert data.y_label == "intensity [n/s]"


def test_a_1d_row_of_the_wrong_width_is_named_rather_than_skipped(tmp_path: Path) -> None:
    broken = tmp_path / "monitor1D.dat"
    lines = MONITOR_1D.read_text(encoding="utf-8").splitlines()
    lines[12] = "    3.2500   1.00000e+00"
    broken.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(MonitorFileError, match="line 13: expected 4 columns"):
        read_monitor_file(broken)


def test_a_2d_matrix_row_of_the_wrong_width_is_named(tmp_path: Path) -> None:
    broken = tmp_path / "monitor2D.dat"
    lines = MONITOR_2D[VtFormat2D.MATRIX].read_text(encoding="utf-8").splitlines()
    lines[11] = "   -2.7500   0.00000e+00"
    broken.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(MonitorFileError, match="a matrix row should hold"):
        read_monitor_file(broken)


def test_an_xyz_file_missing_cells_is_named_rather_than_drawn_with_holes(
    tmp_path: Path,
) -> None:
    """A truncated file is a truncated measurement, not a plot with gaps."""
    truncated = tmp_path / "monitor2D.dat"
    lines = MONITOR_2D[VtFormat2D.XYZ].read_text(encoding="utf-8").splitlines()
    truncated.write_text("\n".join(lines[:-3]), encoding="utf-8")

    with pytest.raises(MonitorFileError, match="the file is incomplete"):
        read_monitor_file(truncated)


def test_duplicate_xyz_coordinates_cannot_hide_a_missing_cell(tmp_path: Path) -> None:
    """The row count alone is insufficient when one cell is repeated."""
    broken = tmp_path / "monitor2D.dat"
    lines = MONITOR_2D[VtFormat2D.XYZ].read_text(encoding="utf-8").splitlines()
    data_rows = [
        index
        for index, line in enumerate(lines)
        if line.strip() and not line.strip().startswith("#")
    ]
    lines[data_rows[-1]] = lines[data_rows[0]]
    broken.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(MonitorFileError, match="duplicate x/y coordinates"):
        read_monitor_file(broken)


def test_a_2d_file_in_neither_layout_is_named(tmp_path: Path) -> None:
    odd = tmp_path / "monitor2D.dat"
    odd.write_text(
        "# title : 2D Monitor:\n1 2 3\n4 5 6 7 8 9\n2 3\n", encoding="utf-8"
    )

    with pytest.raises(MonitorFileError, match="neither the 5-column xyz layout"):
        read_monitor_file(odd)


def test_a_file_that_is_not_a_monitor_file_raises(tmp_path: Path) -> None:
    not_a_monitor = tmp_path / "output.dat"
    not_a_monitor.write_text("# VITESS output\n1 2 3 4\n", encoding="utf-8")

    with pytest.raises(MonitorFileError, match="neither a 1D nor a 2D monitor"):
        read_monitor_file(not_a_monitor)


def test_a_missing_file_raises_the_readers_own_error(tmp_path: Path) -> None:
    with pytest.raises(MonitorFileError, match="Cannot read"):
        read_monitor_file(tmp_path / "absent.dat")


@pytest.mark.parametrize(
    "source", [MONITOR_1D, *sorted(MONITOR_2D.values(), key=str)], ids=lambda p: p.stem
)
def test_rendering_writes_a_png(tmp_path: Path, source: Path) -> None:
    destination = tmp_path / f"{source.stem}.png"

    written = render_monitor_png(read_monitor_file(source), destination)

    assert written == destination
    assert destination.read_bytes()[: len(PNG_MAGIC)] == PNG_MAGIC
    assert destination.stat().st_size > 1000
