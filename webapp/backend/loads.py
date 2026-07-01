"""Full-length PMC (CTL/ATL/TSB) series for the Evolution view.

Mirrors the per-activity daily-load logic of the training-load skill, but
returns the FULL dated series (the skill truncates to 30 days at its CLI) and
is strictly read-only (uses get_latest_snapshot / compute_full_snapshot, never
ensure_snapshot which would persist).
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from strava import analytics  # noqa: E402
from strava.db import get_activities_range, get_latest_snapshot, load_user_profile  # noqa: E402


def _daily_load(act: dict, ftp: float, hr_max: float, hr_rest: float, sex: str) -> float:
    avg_w = act.get("average_watts") or 0
    dur = act.get("moving_time") or 0
    if avg_w and ftp and dur:
        return analytics.tss(dur, avg_w, avg_w / ftp, ftp)
    avg_hr = act.get("average_hr") or 0
    if avg_hr and dur:
        return analytics.banister_trimp(dur / 60.0, avg_hr, hr_rest, hr_max, sex)
    return 0.0


def _resolve_params(db: str, athlete_id: int | None) -> tuple[float, float, float, str]:
    snap = get_latest_snapshot(db, athlete_id) if athlete_id is not None else None
    if snap is None:
        try:  # compute_full_snapshot does NOT persist
            from strava.snapshot import compute_full_snapshot
            snap = compute_full_snapshot(db, days=90)
        except Exception:
            snap = {}
    ftp = (snap or {}).get("ftp_w") or 200.0
    hr_max = (snap or {}).get("hr_max_bpm") or 190.0
    hr_rest = (snap or {}).get("hr_rest_bpm") or 55.0
    profile = load_user_profile(db)
    sex = (profile.get("gender") if profile else None) or "M"
    return ftp, hr_max, hr_rest, sex


def pmc_full(db: str, days: int = 365, athlete_id: int | None = None) -> dict:
    """Return the full dated CTL/ATL/TSB series over the window."""
    ftp, hr_max, hr_rest, sex = _resolve_params(db, athlete_id)
    activities = get_activities_range(db, days=days)

    per_day: dict[str, float] = defaultdict(float)
    for a in activities:
        sd = a.get("start_date")
        if not sd:
            continue
        day = analytics.parse_iso(sd).strftime("%Y-%m-%d")
        per_day[day] += _daily_load(a, ftp, hr_max, hr_rest, sex)

    if not per_day:
        return {"series": [], "params": {"ftp": ftp, "hr_max": hr_max,
                                          "hr_rest": hr_rest, "activities_used": len(activities)}}

    first = min(per_day)
    last = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    full: list[tuple[str, float]] = []
    cur = datetime.strptime(first, "%Y-%m-%d")
    end = datetime.strptime(last, "%Y-%m-%d")
    while cur <= end:
        key = cur.strftime("%Y-%m-%d")
        full.append((key, per_day.get(key, 0.0)))
        cur += timedelta(days=1)

    return {
        "series": analytics.pmc_series(full),
        "params": {"ftp": ftp, "hr_max": hr_max, "hr_rest": hr_rest,
                   "activities_used": len(activities)},
    }
