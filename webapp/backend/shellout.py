"""Subprocess wrappers around read-only skill CLIs.

Only used where the skill already encapsulates non-trivial, tested logic we
don't want to duplicate (session-analysis, weekly-log). We invoke them exactly
as a user would, with the SAME interpreter (sys.executable) so the stale
python2.7 venv is never touched, and NEVER with --sync (which would import from
Downloads and delete files).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_SESSION_ANALYSIS = os.path.join(
    _ROOT, ".claude", "skills", "session-analysis", "scripts", "session_analysis.py"
)
_WEEKLY_LOG = os.path.join(
    _ROOT, ".claude", "skills", "weekly-log", "scripts", "weekly_log.py"
)


def _run(script: str, argv: list[str], timeout: int = 120) -> dict:
    proc = subprocess.run(
        [sys.executable, script, *argv],
        capture_output=True, text=True, cwd=_ROOT, timeout=timeout,
    )
    # Skills print a single JSON envelope line; take the last JSON-looking line.
    for line in reversed(proc.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            payload = json.loads(line)
            if not payload.get("success"):
                raise RuntimeError(payload.get("error") or "skill returned an error")
            return payload.get("data")
    raise RuntimeError(proc.stderr.strip() or "skill produced no JSON output")


def session_analysis(date: str | None = None, strava_id: int | None = None) -> dict:
    if date:
        argv = ["--date", date]
    elif strava_id is not None:
        # Equals-form so argparse never treats a negative synthetic id as a flag.
        argv = [f"--strava-id={strava_id}"]
    else:
        raise ValueError("session_analysis requires date or strava_id")
    return _run(_SESSION_ANALYSIS, argv)


def weekly_log(weeks: int = 12) -> dict:
    return _run(_WEEKLY_LOG, ["--weeks", str(weeks)])
