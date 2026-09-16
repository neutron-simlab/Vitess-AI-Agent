"""Print one collected node id per line, whatever a parametrised id contains.

Used by plan 02, steps 1 and 3, to compare the tests that exist before the
cutover with the tests that exist afterwards across two repositories.

Two properties the plan's original
``pytest --collect-only -q | grep '::' | sed 's|^.*/||'`` recipe does not have:

**One line per test.** Several parametrised ids in this suite embed prompt text
containing real newlines, so pytest prints one node id across several lines.
Fragments carrying a ``::`` are then counted as extra tests and fragments
without one disappear — measured at 465 matching lines against 457 collected
tests, right in total only because the two errors cancelled.

**No test payload in the output.** The baseline list is versioned beside the
plan, which lives in a different repository from the tests. A parametrised id
carrying a specialist prompt would copy that prompt into that repository's
history, where nothing would ever remove it. Any parameter that is long or
multi-line is replaced by a digest of itself, which is stable across the move
and still makes a changed parameter visible as a diff.
"""

from __future__ import annotations

import hashlib

#: Long enough for a real parametrisation (`provider-model`, a filename, a
#: flag), short enough that prose cannot hide under it.
MAX_PARAM_CHARS = 80


def _safe_nodeid(nodeid: str) -> str:
    head, bracket, rest = nodeid.partition("[")
    if not bracket:
        return nodeid
    param = rest[:-1] if rest.endswith("]") else rest
    if "\n" in param or "\r" in param or len(param) > MAX_PARAM_CHARS:
        digest = hashlib.sha256(param.encode("utf-8")).hexdigest()[:12]
        return f"{head}[sha256:{digest}]"
    return nodeid


def pytest_collection_finish(session) -> None:
    for item in session.items:
        print(f"NODEID\t{_safe_nodeid(item.nodeid)}")
