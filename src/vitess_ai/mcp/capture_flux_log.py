"""Read capture_flux's result out of the simulation log.

capture_flux writes no file of its own. Its whole result is three lines in its
log (capture_flux.c:166,172-173), which `postprocess_logs` concatenates into
``result.txt`` with every other module's log:

    Reference wavelength:        1.798 A
    Captured intensity  :    2.485e+11 +/-    2.744e+09 n/s       by      10000 trajectories
    Capture flux        :    2.485e+11 +/-    2.744e+09 n/(s*cm^2)

The server reads them here, where the file is, and returns them typed, so the
number reaches the conversation without the model reading a log. The fixtures
in ``tests/data/capture_flux-*.log`` are real VITESS 3.8 output.
"""

from __future__ import annotations

import math
import re

from vitess_ai.mcp.payloads import CaptureFluxReading

__all__ = ["read_capture_flux"]

_REFERENCE = re.compile(r"^Reference wavelength:\s*(\S+)\s+A\b", re.MULTILINE)
_INTENSITY = re.compile(
    r"^Captured intensity\s*:\s*(\S+)\s+\+/-\s+(\S+)\s+n/s\s+by\s+(\d+)\s+trajectories",
    re.MULTILINE,
)
_FLUX = re.compile(
    r"^Capture flux\s*:\s*(\S+)\s+\+/-\s+(\S+)\s+n/\(s\*cm\^2\)", re.MULTILINE
)


def read_capture_flux(log_text: str) -> CaptureFluxReading | None:
    """Return the reading, or ``None`` if the log holds no complete one.

    ``None`` is the answer for a run whose capture_flux failed before printing,
    and for a value that is not a finite number: the payload crosses a JSON
    boundary, where an infinity has no spelling.
    """
    reference = _REFERENCE.search(log_text)
    intensity = _INTENSITY.search(log_text)
    flux = _FLUX.search(log_text)
    if reference is None or intensity is None or flux is None:
        return None

    try:
        numbers = [
            float(reference.group(1)),
            float(intensity.group(1)),
            float(intensity.group(2)),
            float(flux.group(1)),
            float(flux.group(2)),
        ]
    except ValueError:
        return None
    if not all(math.isfinite(number) for number in numbers):
        return None

    reference_wavelength, captured, captured_error, capture_flux, flux_error = numbers
    return CaptureFluxReading(
        captured_intensity=captured,
        captured_intensity_error=captured_error,
        trajectories=int(intensity.group(3)),
        capture_flux=capture_flux,
        capture_flux_error=flux_error,
        reference_wavelength=reference_wavelength,
    )
