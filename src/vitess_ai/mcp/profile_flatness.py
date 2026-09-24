"""Judge whether a run's horizontal 1D profile is flat across the sample.

Guide shapes are compared on two numbers: the capture flux on a 1 x 1 cm^2
sample, and whether the beam is flat across it. This is the second. The
criterion is fixed, and every constant below is part of it:

- the central 1 cm of ``pos_y``, centred on the beam axis;
- recorded from -2 to 2 cm in 40 bins, so the sample is ten whole 0.1 cm bins
  away from the monitor boundary. VITESS folds the interval immediately below
  a monitor range into its first bin, so the sample must not start there;
- judged in 0.1 cm bins. The bin width belongs to the criterion because "10 %"
  means something different per width: a narrower bin is noisier and resolves
  finer structure, so the same beam can pass in one binning and fail in another;
- no bin further than 10 % from the window's mean intensity.

VITESS is a Monte Carlo simulation, and every bin carries a statistical error
(the monitor file's third column). A flat beam run with too few trajectories
has bins 10 % off by noise alone -- at the schema's default 0.04 cm bins and
10^4 trajectories, the flat fixture's worst bin is 15.6 % off. So the verdict
allows for each bin's error, two standard deviations either way:

    pass          every bin is inside 10 % even at the far end of its error
    fail          some bin is outside 10 % even at the near end of its error
    inconclusive  neither; more trajectories would decide it

An empty bin inside the window is a hole in the beam. It needs no rule of its
own: its deviation is -100 % with no error, so it fails like any other bin.

The fixtures ``tests/data/monitor1D-flatness-*.dat`` are real VITESS 3.8
output; ``tests/data/README.md`` records how each was made.
"""

from __future__ import annotations

import math

import numpy as np

from vitess_ai.mcp.payloads import FlatnessReading
from vitess_ai.plots import MonitorData

__all__ = [
    "BIN_WIDTH_CM",
    "MONITOR_BIN_COUNT",
    "MONITOR_MAX_CM",
    "MONITOR_MIN_CM",
    "NOISE_SIGMAS",
    "TOLERANCE",
    "WINDOW_WIDTH_CM",
    "read_flatness",
]

#: How monitor1D labels its x axis for ``-X1``, the horizontal position.
AXIS_LABEL = "pos_y [cm]"
WINDOW_CENTRE_CM = 0.0
WINDOW_WIDTH_CM = 1.0
BIN_WIDTH_CM = 0.1
MONITOR_MIN_CM = -2.0
MONITOR_MAX_CM = 2.0
MONITOR_BIN_COUNT = 40
TOLERANCE = 0.10
NOISE_SIGMAS = 2.0

#: Tolerance for comparing positions read from the file.
_POSITION_SLACK_CM = 1e-3


def read_flatness(data: MonitorData) -> FlatnessReading | None:
    """Return the verdict for a horizontal profile, or ``None`` for any other file.

    ``None`` means "not a flatness measurement" -- a wavelength spectrum, say --
    and is not a failure.
    """
    if data.kind != "monitor1d" or data.x_label != AXIS_LABEL or data.x.size < 2:
        return None

    # Rounded to the four decimals monitor1D prints its bin centres with.
    bin_width = round(float(data.x[1] - data.x[0]), 4)
    expected_centres = np.linspace(
        MONITOR_MIN_CM + BIN_WIDTH_CM / 2,
        MONITOR_MAX_CM - BIN_WIDTH_CM / 2,
        MONITOR_BIN_COUNT,
    )
    if data.x.size != MONITOR_BIN_COUNT or not np.allclose(
        data.x, expected_centres, rtol=0, atol=_POSITION_SLACK_CM
    ):
        return FlatnessReading(verdict="wrong_binning", bin_width_cm=bin_width)

    low = WINDOW_CENTRE_CM - WINDOW_WIDTH_CM / 2
    high = WINDOW_CENTRE_CM + WINDOW_WIDTH_CM / 2
    # Whole bins only. A bin straddling the window edge would measure some
    # beam from outside the sample.
    inside = (data.x - bin_width / 2 > low - _POSITION_SLACK_CM) & (
        data.x + bin_width / 2 < high + _POSITION_SLACK_CM
    )
    # Ten whole 0.1 cm bins exist only if the window's edges are bin edges.
    if not math.isclose(bin_width, BIN_WIDTH_CM, abs_tol=_POSITION_SLACK_CM) or (
        np.count_nonzero(inside) != round(WINDOW_WIDTH_CM / BIN_WIDTH_CM)
    ):
        return FlatnessReading(verdict="wrong_binning", bin_width_cm=bin_width)

    assert data.error is not None  # a 1D monitor file always has the column
    intensity = data.intensity[inside]
    error = data.error[inside]
    position = data.x[inside]
    filled = intensity > 0
    empty = int(np.count_nonzero(~filled))
    mean = float(intensity.mean())
    if mean <= 0:
        return FlatnessReading(verdict="fail", bin_width_cm=bin_width, empty_bins=empty)

    deviation = (intensity - mean) / mean
    relative_error = np.zeros_like(intensity)
    relative_error[filled] = error[filled] / intensity[filled]
    band = NOISE_SIGMAS * relative_error

    if np.any(np.abs(deviation) - band > TOLERANCE):
        verdict = "fail"
    elif np.all(np.abs(deviation) + band <= TOLERANCE):
        verdict = "pass"
    else:
        verdict = "inconclusive"

    worst = int(np.argmax(np.abs(deviation)))
    return FlatnessReading(
        verdict=verdict,
        bin_width_cm=bin_width,
        empty_bins=empty,
        worst_deviation=float(deviation[worst]),
        worst_position_cm=float(position[worst]),
        median_relative_error=float(np.median(relative_error[filled])),
    )
