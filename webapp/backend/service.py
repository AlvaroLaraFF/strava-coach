"""Data functions backing the web API. Each returns a plain dict/list (the
``data`` payload); server.py wraps it in the {"success":true,"data":...}
envelope. Everything here is READ-ONLY.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from strava import analytics  # noqa: E402
from strava.client import get_default_db_path  # noqa: E402
from strava.db import (  # noqa: E402
    get_activities_range,
    get_best_efforts_pr,
    get_blocks_for_sessions,
    get_latest_snapshot,
    get_recent_activities,
    get_snapshot_history,
    list_planned_sessions,
    load_laps,
    load_streams,
    load_token,
    load_user_profile,
)
from strava.fileimport import resolve_athlete_id  # noqa: E402
from webapp.backend import downsample, loads, narrative_es, shellout  # noqa: E402

DB = get_default_db_path()
_AID: dict = {}


# --------------------------------------------------------------------------- #
# Shared helpers                                                              #
# --------------------------------------------------------------------------- #
def athlete_id() -> int | None:
    if "v" not in _AID:
        tok = load_token(DB)
        _AID["v"] = (tok or {}).get("athlete_id") or resolve_athlete_id(DB)
    return _AID["v"]


def _ro_conn() -> sqlite3.Connection:
    """Read-only connection for the few direct queries not covered by db.py."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def tsb_verdict(tsb: float | None) -> str:
    """Coarse form token (frontend localizes)."""
    if tsb is None:
        return "unknown"
    if tsb > 25:
        return "detraining"
    if tsb > 5:
        return "fresh"
    if tsb >= -10:
        return "optimal"
    if tsb >= -30:
        return "fatigued"
    return "high_risk"


def _activity_brief(row: dict, with_streams: bool = False) -> dict:
    dist = row.get("distance")
    mt = row.get("moving_time")
    pace = analytics.pace_min_per_km(dist, mt)
    brief = {
        "strava_id": row.get("strava_id"),
        "name": row.get("name"),
        "sport_type": row.get("sport_type"),
        "start_date": row.get("start_date"),
        "distance_km": round(dist / 1000, 2) if dist else None,
        "moving_time_s": mt,
        "duration_str": analytics.fmt_duration(mt) if mt else None,
        "avg_pace_min_km": round(pace, 3) if pace else None,
        "avg_pace_str": analytics.fmt_pace(pace),
        "avg_hr": row.get("average_hr"),
        "max_hr": row.get("max_hr"),
        "total_elevation_m": row.get("total_elevation"),
        "imported": (row.get("strava_id") or 0) < 0,
    }
    if with_streams:
        from strava.db import has_streams
        brief["has_streams"] = has_streams(DB, row.get("strava_id"))
    return brief


def _get_activity_row(sid: int) -> dict | None:
    con = _ro_conn()
    try:
        row = con.execute(
            "SELECT * FROM activities WHERE strava_id = ?", (sid,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #
def health() -> dict:
    return {"status": "ok", "db": DB, "athlete_id": athlete_id()}


def dashboard() -> dict:
    aid = athlete_id()
    snap = get_latest_snapshot(DB, aid) or {}
    today = _today()
    horizon = (datetime.now(timezone.utc) + timedelta(days=21)).strftime("%Y-%m-%d")
    planned = list_planned_sessions(DB, aid, today, horizon) if aid else []
    next_session = next(
        (p for p in planned if p.get("status") == "planned" and p.get("plan_date") >= today),
        None,
    )
    if next_session:
        blocks = get_blocks_for_sessions(DB, [next_session["id"]]).get(next_session["id"], [])
        next_session = {**next_session, "blocks": blocks}
    recent = [_activity_brief(a) for a in get_recent_activities(DB, limit=10)]
    return {
        "snapshot": snap,
        "tsb_verdict": tsb_verdict(snap.get("tsb")),
        "next_session": next_session,
        "recent": recent,
    }


def activities(days: int = 120, sport: str | None = None, limit: int = 200) -> dict:
    rows = get_activities_range(DB, days=days)
    if sport:
        rows = [r for r in rows if (r.get("sport_type") or "").lower() == sport.lower()]
    rows = sorted(rows, key=lambda r: r.get("start_date") or "", reverse=True)[:limit]
    return {"activities": [_activity_brief(r, with_streams=True) for r in rows],
            "count": len(rows)}


def activity_detail(sid: int) -> dict:
    row = _get_activity_row(sid)
    if not row:
        raise KeyError(f"activity {sid} not found")
    raw = {}
    try:
        raw = json.loads(row.get("raw_json") or "{}")
    except (TypeError, ValueError):
        pass
    summary = _activity_brief(row, with_streams=True)
    summary.update({
        "average_watts": row.get("average_watts"),
        "kilojoules": row.get("kilojoules"),
        "start_latlng": raw.get("start_latlng"),
        "end_latlng": raw.get("end_latlng"),
        "splits_count": len(raw.get("splits_metric") or []),
    })
    return {"summary": summary, "laps": load_laps(DB, sid) or []}


def streams(sid: int, target: int = 1200) -> dict:
    st = load_streams(DB, sid) or {}
    return downsample.decimate_streams(st, target=target)


def session_analysis(date: str | None = None, strava_id: int | None = None) -> dict:
    data = shellout.session_analysis(date=date, strava_id=strava_id)
    # Localize the English narrative bullets to Spanish for the GUI; keep the
    # original for reference.
    if isinstance(data, dict) and isinstance(data.get("narrative"), list):
        data["narrative_en"] = data["narrative"]
        data["narrative"] = narrative_es.translate(data["narrative"])
    return data


def compare(a: int, b: int) -> dict:
    """Compare two sessions: summaries, per-km splits and headline deltas.

    Reuses session-analysis for each (rich splits with GAP). Read-only.
    """
    if a is None or b is None:
        raise ValueError("compare requires two activity ids: a and b")
    ra = shellout.session_analysis(strava_id=a)
    rb = shellout.session_analysis(strava_id=b)
    sa, sb = ra.get("summary") or {}, rb.get("summary") or {}

    def _delta(key):
        va, vb = sa.get(key), sb.get(key)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            return round(va - vb, 3)
        return None

    def _pace_min_km(s):
        d, t = s.get("distance_km"), s.get("moving_time_s")
        return (t / 60.0) / d if d and t else None

    pa, pb = _pace_min_km(sa), _pace_min_km(sb)
    pace_delta_sec = round((pa - pb) * 60, 0) if pa and pb else None

    return {
        "a": {"summary": sa, "splits": ra.get("splits") or []},
        "b": {"summary": sb, "splits": rb.get("splits") or []},
        "deltas": {
            "distance_km": _delta("distance_km"),
            "moving_time_s": _delta("moving_time_s"),
            "pace_delta_sec_km": pace_delta_sec,
            "avg_hr": _delta("avg_hr"),
            "total_elevation_m": _delta("total_elevation_m"),
        },
    }


def _acts_between(start: str, end: str) -> list[dict]:
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        start_dt = datetime.now(timezone.utc) - timedelta(days=42)
    span_days = max(1, (datetime.now(timezone.utc) - start_dt).days + 2)
    rows = get_activities_range(DB, days=span_days)
    out = []
    for r in rows:
        sd = r.get("start_date")
        if not sd:
            continue
        day = analytics.parse_iso(sd).strftime("%Y-%m-%d")
        if start <= day <= end:
            out.append((day, r))
    return out


def calendar(start: str, end: str) -> dict:
    aid = athlete_id()
    planned = list_planned_sessions(DB, aid, start, end) if aid else []
    block_map = get_blocks_for_sessions(DB, [p["id"] for p in planned]) if planned else {}
    for p in planned:
        p["blocks"] = block_map.get(p["id"], [])

    executed = _acts_between(start, end)
    by_day_planned: dict[str, list] = {}
    for p in planned:
        by_day_planned.setdefault(p["plan_date"], []).append(p)
    by_day_exec: dict[str, list] = {}
    for day, row in executed:
        by_day_exec.setdefault(day, []).append(_activity_brief(row))

    today = _today()
    days = []
    cur = datetime.strptime(start, "%Y-%m-%d")
    last = datetime.strptime(end, "%Y-%m-%d")
    while cur <= last:
        key = cur.strftime("%Y-%m-%d")
        p_list = by_day_planned.get(key, [])
        e_list = by_day_exec.get(key, [])
        state = _day_state(p_list, e_list, key, today)
        days.append({
            "date": key,
            "iso_week": analytics.iso_week(key + "T00:00:00Z"),
            "planned": p_list,
            "executed": e_list,
            "state": state,
        })
        cur += timedelta(days=1)
    return {"start": start, "end": end, "days": days}


def _day_state(planned: list, executed: list, day: str, today: str) -> str:
    has_real = any(p.get("sport_type", "").lower() != "rest" for p in planned)
    is_rest = bool(planned) and not has_real
    if executed and planned and has_real:
        return "matched"
    if executed and not has_real:
        return "unplanned"
    if is_rest:
        return "rest"
    if has_real and not executed:
        return "missed" if day < today else "planned"
    return "empty"


def evolution(days: int = 365) -> dict:
    aid = athlete_id()
    history = list(reversed(get_snapshot_history(DB, aid, limit=200))) if aid else []
    metric_keys = ["captured_at", "vdot", "threshold_pace_min_km", "hr_max_bpm",
                   "hr_rest_bpm", "lthr_bpm", "ctl", "atl", "tsb", "weight_kg", "ftp_w"]
    snapshot_history = [{k: h.get(k) for k in metric_keys} for h in history]
    pmc = loads.pmc_full(DB, days=days, athlete_id=aid)
    return {
        "snapshot_history": snapshot_history,
        "pmc": pmc["series"],
        "pmc_params": pmc["params"],
        "pr_progression": _pr_progression(aid),
    }


def _pr_progression(aid: int | None) -> dict:
    if aid is None:
        return {}
    con = _ro_conn()
    try:
        rows = con.execute(
            """SELECT effort_name, distance, elapsed_time, start_date
               FROM best_efforts WHERE athlete_id = ?
               ORDER BY start_date ASC""",
            (aid,),
        ).fetchall()
    finally:
        con.close()
    out: dict = {}
    best_so_far: dict = {}
    for r in rows:
        name = r["effort_name"]
        t = r["elapsed_time"]
        dist = r["distance"]
        prev = best_so_far.get(name)
        is_pr = prev is None or t < prev
        if is_pr:
            best_so_far[name] = t
        pace = analytics.pace_min_per_km(dist, t)
        out.setdefault(name, []).append({
            "date": (r["start_date"] or "")[:10],
            "distance_m": dist,
            "time_s": t,
            "time_str": analytics.fmt_duration(t),
            "pace_str": analytics.fmt_pace(pace),
            "running_best_s": best_so_far[name],
            "is_pr": is_pr,
        })
    return out


def prs() -> dict:
    aid = athlete_id()
    raw = get_best_efforts_pr(DB, aid) if aid else []
    today = datetime.now(timezone.utc)
    out = []
    anchor = None  # (dist_m, time_s) for predictions, prefer 5k
    for r in raw:
        dist = r["distance"]
        t = r["pr_time"]
        pace = analytics.pace_min_per_km(dist, t)
        age_days = None
        if r.get("start_date"):
            try:
                age_days = (today - analytics.parse_iso(r["start_date"])).days
            except Exception:
                age_days = None
        out.append({
            "effort_name": r["effort_name"],
            "distance_m": dist,
            "time_s": t,
            "time_str": analytics.fmt_duration(t),
            "pace_min_km": round(pace, 3) if pace else None,
            "pace_str": analytics.fmt_pace(pace),
            "date": (r.get("start_date") or "")[:10],
            "age_days": age_days,
            "stale": age_days is not None and age_days > 180,
        })
        if abs(dist - 5000) < 100 or (anchor is None and 3000 <= dist <= 12000):
            anchor = (dist, t)
    predictions = {}
    if anchor:
        for label, td in [("5k", 5000), ("10k", 10000), ("half", 21097), ("marathon", 42195)]:
            secs = analytics.riegel_predict(anchor[1], anchor[0], td)
            predictions[label] = {"time_s": round(secs), "time_str": analytics.fmt_duration(secs)}
    return {"prs": out, "predictions": predictions,
            "stale_count": sum(1 for p in out if p["stale"])}


def hr_zones() -> dict:
    aid = athlete_id()
    snap = get_latest_snapshot(DB, aid) or {}
    hr_max = snap.get("hr_max_bpm")
    hr_rest = snap.get("hr_rest_bpm")
    lthr = snap.get("lthr_bpm")
    result: dict = {"hr_max": hr_max, "hr_rest": hr_rest, "lthr": lthr}
    if hr_max and hr_rest and hr_max > hr_rest:
        result["karvonen"] = analytics.hr_zones_karvonen(hr_max, hr_rest)
    if lthr:
        result["friel"] = analytics.hr_zones_friel(lthr)
    return result


def weekly_log(weeks: int = 12) -> dict:
    return shellout.weekly_log(weeks=weeks)


def profile() -> dict:
    aid = athlete_id()
    return {
        "profile": load_user_profile(DB, aid),
        "snapshot": get_latest_snapshot(DB, aid) or {},
        "athlete_id": aid,
    }
