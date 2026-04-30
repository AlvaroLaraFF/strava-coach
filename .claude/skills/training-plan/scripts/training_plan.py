#!/usr/bin/env python3
"""CRUD and adherence review for the planned_sessions table."""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import parse_iso
from strava.client import StravaClient, get_default_db_path, output_error, output_json
from strava.db import (
    delete_planned_range,
    delete_planned_session,
    get_activities_range,
    get_blocks_for_sessions,
    get_planned_blocks,
    link_planned_to_activity,
    list_planned_sessions,
    load_token,
    replace_planned_blocks,
    update_planned_session,
    upsert_planned_session,
)
from strava.sync import sync_summary


REQUIRED_FIELDS = (
    "plan_date",
    "sport_type",
    "session_type",
    "hr_min_bpm",
    "hr_max_bpm",
    "pace_fast_min_km",
    "pace_slow_min_km",
)


def _coerce_pace(value, field_name: str):
    """Accept either decimal min/km (5.50) or 'M:SS' string — store as float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and ":" in value:
        try:
            m, s = value.split(":")
            return round(int(m) + int(s) / 60.0, 3)
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"{field_name} has invalid M:SS format: {value!r}"
            ) from e
    try:
        return float(value)
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"{field_name} must be a number or 'M:SS' string, got {value!r}"
        ) from e

VALID_BLOCK_TYPES = {"warmup", "work", "recovery", "cooldown", "steady", "rest"}

REQUIRED_BLOCK_FIELDS = (
    "block_type",
    "hr_min_bpm",
    "hr_max_bpm",
    "pace_fast_min_km",
    "pace_slow_min_km",
)


def validate_block(block: dict, idx: int) -> None:
    missing = [k for k in REQUIRED_BLOCK_FIELDS if block.get(k) is None]
    if missing:
        raise ValueError(
            f"block {idx} missing required fields: {', '.join(missing)}"
        )
    if block["block_type"] not in VALID_BLOCK_TYPES:
        raise ValueError(
            f"block {idx} has invalid block_type '{block['block_type']}'; "
            f"allowed: {sorted(VALID_BLOCK_TYPES)}"
        )
    repeat = block.get("repeat_count", 1)
    if not isinstance(repeat, int) or repeat < 1:
        raise ValueError(
            f"block {idx} repeat_count must be a positive integer"
        )
    if block["block_type"] == "rest":
        return
    if block["hr_min_bpm"] >= block["hr_max_bpm"]:
        raise ValueError(
            f"block {idx} hr_min_bpm ({block['hr_min_bpm']}) must be lower "
            f"than hr_max_bpm ({block['hr_max_bpm']})"
        )
    if block["pace_fast_min_km"] >= block["pace_slow_min_km"]:
        raise ValueError(
            f"block {idx} pace_fast_min_km ({block['pace_fast_min_km']}) "
            f"must be lower than pace_slow_min_km "
            f"({block['pace_slow_min_km']}); lower number = faster"
        )
    if (
        block.get("duration_min") is None
        and block.get("distance_km") is None
    ):
        raise ValueError(
            f"block {idx} must carry at least one of duration_min / distance_km"
        )


def validate_session(session: dict) -> None:
    missing = [k for k in REQUIRED_FIELDS if session.get(k) is None]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    session["pace_fast_min_km"] = _coerce_pace(
        session["pace_fast_min_km"], "pace_fast_min_km"
    )
    session["pace_slow_min_km"] = _coerce_pace(
        session["pace_slow_min_km"], "pace_slow_min_km"
    )
    if session["hr_min_bpm"] >= session["hr_max_bpm"]:
        raise ValueError(
            f"hr_min_bpm ({session['hr_min_bpm']}) must be lower than "
            f"hr_max_bpm ({session['hr_max_bpm']})"
        )
    if session["pace_fast_min_km"] >= session["pace_slow_min_km"]:
        raise ValueError(
            f"pace_fast_min_km ({session['pace_fast_min_km']}) must be lower "
            f"than pace_slow_min_km ({session['pace_slow_min_km']}); "
            "lower number = faster"
        )
    try:
        datetime.strptime(session["plan_date"], "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"plan_date must be YYYY-MM-DD: {e}") from None

    blocks = session.get("blocks")
    if blocks is not None:
        if not isinstance(blocks, list) or not blocks:
            raise ValueError("blocks must be a non-empty list when provided")
        for i, block in enumerate(blocks):
            if not isinstance(block, dict):
                raise ValueError(f"block {i} is not an object")
            validate_block(block, i)


def session_from_add_args(args: argparse.Namespace) -> dict:
    return {
        "plan_date": args.date,
        "sport_type": args.sport,
        "session_type": args.session_type,
        "phase": args.phase,
        "duration_min": args.duration,
        "distance_km": args.distance,
        "hr_min_bpm": args.hr_min,
        "hr_max_bpm": args.hr_max,
        "pace_fast_min_km": args.pace_fast,
        "pace_slow_min_km": args.pace_slow,
        "description": args.description,
        "notes": args.notes,
    }


def current_iso_week_range() -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def pace_min_km_from_speed(avg_speed_m_s: float | None) -> float | None:
    if not avg_speed_m_s or avg_speed_m_s <= 0:
        return None
    return round((1000.0 / avg_speed_m_s) / 60.0, 3)


def avg_vs_range(value: float | None, low: float, high: float) -> str:
    if value is None:
        return "unknown"
    if value < low:
        return "below"
    if value > high:
        return "above"
    return "inside"


def auto_match(db_path: str, athlete_id: int, sessions: list[dict]) -> list[dict]:
    """Mutate session dicts in place with status + actual_strava_id.

    Past-dated planned rows get linked to the closest same-day activity of
    the same sport (closest by distance_km). Unmatched past rows become
    skipped. Future rows stay as-is.
    """
    today = date.today().isoformat()
    earliest = min(
        (s["plan_date"] for s in sessions if s.get("plan_date")), default=today
    )
    try:
        earliest_dt = datetime.strptime(earliest, "%Y-%m-%d").date()
    except ValueError:
        earliest_dt = date.today()
    span_days = max((date.today() - earliest_dt).days + 2, 2)
    acts = get_activities_range(db_path, days=span_days)

    by_day: dict[tuple[str, str], list[dict]] = {}
    for a in acts:
        sd = a.get("start_date")
        if not sd:
            continue
        try:
            day = parse_iso(sd).date().isoformat()
        except ValueError:
            continue
        key = (day, a.get("sport_type") or "")
        by_day.setdefault(key, []).append(a)

    for p in sessions:
        if p.get("actual_strava_id") is not None:
            continue
        if p.get("status") not in ("planned", "skipped"):
            continue
        if not p.get("plan_date") or p["plan_date"] > today:
            continue
        candidates = by_day.get((p["plan_date"], p["sport_type"]), [])
        if candidates:
            target_km = p.get("distance_km") or 0
            best = min(
                candidates,
                key=lambda a: abs((a.get("distance") or 0) / 1000.0 - target_km),
            )
            link_planned_to_activity(
                db_path, p["id"], best["strava_id"], "completed"
            )
            p["status"] = "completed"
            p["actual_strava_id"] = best["strava_id"]
            p["_actual"] = best
        else:
            link_planned_to_activity(db_path, p["id"], None, "skipped")
            p["status"] = "skipped"
    return sessions


def compute_session_deltas(p: dict) -> dict:
    """Return adherence deltas for a matched session. Expects p['_actual']."""
    actual = p.get("_actual") or {}
    actual_duration_min = (actual.get("moving_time") or 0) / 60.0
    actual_distance_km = (actual.get("distance") or 0) / 1000.0
    actual_hr = actual.get("average_hr")
    actual_pace = pace_min_km_from_speed(actual.get("average_speed"))

    return {
        "duration_delta_min": round(
            actual_duration_min - (p.get("duration_min") or 0), 1
        ),
        "distance_delta_km": round(
            actual_distance_km - (p.get("distance_km") or 0), 2
        ),
        "actual_hr_avg": round(actual_hr, 1) if actual_hr is not None else None,
        "hr_avg_vs_range": avg_vs_range(
            actual_hr, p.get("hr_min_bpm") or 0, p.get("hr_max_bpm") or 9999
        ),
        "actual_pace_min_km": actual_pace,
        "pace_avg_vs_range": avg_vs_range(
            actual_pace,
            p.get("pace_fast_min_km") or 0,
            p.get("pace_slow_min_km") or 99,
        ),
        "actual_strava_id": actual.get("strava_id"),
        "actual_name": actual.get("name"),
    }


def strip_internal(rows: list[dict]) -> list[dict]:
    for r in rows:
        r.pop("_actual", None)
    return rows


def cmd_add(db_path: str, athlete_id: int, args: argparse.Namespace) -> None:
    session = session_from_add_args(args)
    if args.blocks:
        try:
            session["blocks"] = json.loads(args.blocks)
        except json.JSONDecodeError as e:
            output_error(f"--blocks is not valid JSON: {e}")
    validate_session(session)
    sid = upsert_planned_session(db_path, athlete_id, session)
    if session.get("blocks"):
        replace_planned_blocks(db_path, sid, session["blocks"])
    output_json(
        {
            "created": True,
            "session_id": sid,
            "block_count": len(session.get("blocks") or []),
        }
    )


def cmd_add_bulk(db_path: str, athlete_id: int, args: argparse.Namespace) -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        output_error("add-bulk expects a JSON array on stdin")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        output_error(f"invalid JSON on stdin: {e}")
    if not isinstance(payload, list) or not payload:
        output_error("add-bulk payload must be a non-empty JSON array")

    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            output_error(f"item {i} is not an object")
        try:
            validate_session(item)
        except ValueError as e:
            output_error(f"item {i} invalid: {e}")

    if args.replace_range:
        start, end = args.replace_range
        delete_planned_range(db_path, athlete_id, start, end)

    ids = []
    for item in payload:
        sid = upsert_planned_session(db_path, athlete_id, item)
        if item.get("blocks"):
            replace_planned_blocks(db_path, sid, item["blocks"])
        ids.append(sid)
    output_json({"created": len(ids), "ids": ids})


def maybe_sync(db_path: str, sync: bool) -> None:
    """Run a lightweight summary sync if --sync was passed."""
    if not sync:
        return
    try:
        client = StravaClient(db_path)
        sync_summary(client, db_path, days=14)
    except Exception:
        pass  # non-fatal: proceed with whatever the DB already has


def cmd_list(db_path: str, athlete_id: int, args: argparse.Namespace) -> None:
    start, end = args.start, args.end
    if not start or not end:
        start, end = current_iso_week_range()
    maybe_sync(db_path, getattr(args, "sync", False))
    sessions = list_planned_sessions(db_path, athlete_id, start, end)
    auto_match(db_path, athlete_id, sessions)
    blocks_by_sid = get_blocks_for_sessions(
        db_path, [s["id"] for s in sessions]
    )
    for p in sessions:
        p["blocks"] = blocks_by_sid.get(p["id"], [])
        if p.get("status") == "completed" and p.get("_actual"):
            p.update(compute_session_deltas(p))
    output_json(
        {
            "start": start,
            "end": end,
            "count": len(sessions),
            "sessions": strip_internal(sessions),
        }
    )


def cmd_review(db_path: str, athlete_id: int, args: argparse.Namespace) -> None:
    start, end = args.start, args.end
    maybe_sync(db_path, getattr(args, "sync", False))
    sessions = list_planned_sessions(db_path, athlete_id, start, end)
    if not sessions:
        output_json(
            {
                "start": start,
                "end": end,
                "summary": {
                    "planned_count": 0,
                    "completed_count": 0,
                    "skipped_count": 0,
                    "completion_pct": 0.0,
                },
                "per_session": [],
                "breakdown": {"by_phase": {}, "by_session_type": {}},
            }
        )
        return

    auto_match(db_path, athlete_id, sessions)

    completed = [s for s in sessions if s["status"] == "completed"]
    skipped = [s for s in sessions if s["status"] == "skipped"]
    planned_future = [s for s in sessions if s["status"] == "planned"]

    per_session = []
    for p in sessions:
        entry = {
            "id": p["id"],
            "plan_date": p["plan_date"],
            "sport_type": p["sport_type"],
            "session_type": p["session_type"],
            "phase": p.get("phase"),
            "status": p["status"],
            "duration_min": p.get("duration_min"),
            "distance_km": p.get("distance_km"),
            "hr_range": [p.get("hr_min_bpm"), p.get("hr_max_bpm")],
            "pace_range": [p.get("pace_fast_min_km"), p.get("pace_slow_min_km")],
        }
        if p["status"] == "completed" and p.get("_actual"):
            entry.update(compute_session_deltas(p))
        per_session.append(entry)

    def agg_group(rows: list[dict]) -> dict:
        if not rows:
            return {
                "planned": 0,
                "completed": 0,
                "skipped": 0,
                "completion_pct": 0.0,
                "avg_duration_delta_min": None,
                "hr_inside": 0,
                "hr_below": 0,
                "hr_above": 0,
                "pace_inside": 0,
                "pace_below": 0,
                "pace_above": 0,
            }
        comp = [r for r in rows if r["status"] == "completed"]
        deltas = [
            compute_session_deltas(r)
            for r in comp
            if r.get("_actual")
        ]
        avg_dur = (
            round(sum(d["duration_delta_min"] for d in deltas) / len(deltas), 1)
            if deltas
            else None
        )
        hr_counts = {"inside": 0, "below": 0, "above": 0}
        pace_counts = {"inside": 0, "below": 0, "above": 0}
        for d in deltas:
            if d["hr_avg_vs_range"] in hr_counts:
                hr_counts[d["hr_avg_vs_range"]] += 1
            if d["pace_avg_vs_range"] in pace_counts:
                pace_counts[d["pace_avg_vs_range"]] += 1
        return {
            "planned": len(rows),
            "completed": len(comp),
            "skipped": sum(1 for r in rows if r["status"] == "skipped"),
            "completion_pct": round(100.0 * len(comp) / len(rows), 1),
            "avg_duration_delta_min": avg_dur,
            "hr_inside": hr_counts["inside"],
            "hr_below": hr_counts["below"],
            "hr_above": hr_counts["above"],
            "pace_inside": pace_counts["inside"],
            "pace_below": pace_counts["below"],
            "pace_above": pace_counts["above"],
        }

    by_phase: dict[str, list[dict]] = {}
    by_type: dict[str, list[dict]] = {}
    for s in sessions:
        by_phase.setdefault(s.get("phase") or "(none)", []).append(s)
        by_type.setdefault(s.get("session_type") or "(none)", []).append(s)

    summary = {
        "planned_count": len(sessions),
        "completed_count": len(completed),
        "skipped_count": len(skipped),
        "future_count": len(planned_future),
        "completion_pct": round(
            100.0 * len(completed) / max(len(sessions) - len(planned_future), 1),
            1,
        ),
    }

    output_json(
        {
            "start": start,
            "end": end,
            "summary": summary,
            "per_session": per_session,
            "breakdown": {
                "by_phase": {k: agg_group(v) for k, v in by_phase.items()},
                "by_session_type": {k: agg_group(v) for k, v in by_type.items()},
            },
        }
    )


def cmd_update(db_path: str, _athlete_id: int, args: argparse.Namespace) -> None:
    mapping = {
        "plan_date": args.date,
        "sport_type": args.sport,
        "session_type": args.session_type,
        "phase": args.phase,
        "duration_min": args.duration,
        "distance_km": args.distance,
        "hr_min_bpm": args.hr_min,
        "hr_max_bpm": args.hr_max,
        "pace_fast_min_km": args.pace_fast,
        "pace_slow_min_km": args.pace_slow,
        "description": args.description,
        "notes": args.notes,
        "status": args.status,
    }
    fields = {k: v for k, v in mapping.items() if v is not None}
    if not fields:
        output_error("update requires at least one field to change")
    update_planned_session(db_path, args.id, **fields)
    output_json({"updated": True, "session_id": args.id, "fields": list(fields)})


def cmd_delete(db_path: str, _athlete_id: int, args: argparse.Namespace) -> None:
    delete_planned_session(db_path, args.id)
    output_json({"deleted": True, "session_id": args.id})


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Persist training plans and measure adherence")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Add a single planned session")
    p_add.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_add.add_argument("--sport", required=True)
    p_add.add_argument("--session-type", required=True)
    p_add.add_argument("--phase", default=None)
    p_add.add_argument("--duration", type=float, default=None, help="minutes")
    p_add.add_argument("--distance", type=float, default=None, help="km")
    p_add.add_argument("--hr-min", type=int, required=True)
    p_add.add_argument("--hr-max", type=int, required=True)
    p_add.add_argument("--pace-fast", type=float, required=True, help="min/km decimal (e.g. 5.25 = 5:15)")
    p_add.add_argument("--pace-slow", type=float, required=True)
    p_add.add_argument("--description", default=None)
    p_add.add_argument("--notes", default=None)
    p_add.add_argument(
        "--blocks",
        default=None,
        help="Optional JSON array of block dicts (warmup/work/recovery/cooldown)",
    )

    p_bulk = sub.add_parser("add-bulk", help="Bulk insert sessions from stdin JSON array")
    p_bulk.add_argument(
        "--replace-range",
        nargs=2,
        metavar=("START", "END"),
        default=None,
        help="Delete existing sessions in [START, END] before inserting",
    )

    p_list = sub.add_parser("list", help="List sessions in a window (auto-matches past-dated rows)")
    p_list.add_argument("--start", default=None, help="YYYY-MM-DD (default: current ISO week Monday)")
    p_list.add_argument("--end", default=None, help="YYYY-MM-DD (default: current ISO week Sunday)")
    p_list.add_argument("--sync", action="store_true", help="Sync from Strava before matching")

    p_review = sub.add_parser("review", help="Adherence report for a closed window")
    p_review.add_argument("--start", required=True, help="YYYY-MM-DD")
    p_review.add_argument("--end", required=True, help="YYYY-MM-DD")
    p_review.add_argument("--sync", action="store_true", help="Sync from Strava before matching")

    p_upd = sub.add_parser("update", help="Update fields on a planned session")
    p_upd.add_argument("--id", type=int, required=True)
    p_upd.add_argument("--date", default=None)
    p_upd.add_argument("--sport", default=None)
    p_upd.add_argument("--session-type", default=None)
    p_upd.add_argument("--phase", default=None)
    p_upd.add_argument("--duration", type=float, default=None)
    p_upd.add_argument("--distance", type=float, default=None)
    p_upd.add_argument("--hr-min", type=int, default=None)
    p_upd.add_argument("--hr-max", type=int, default=None)
    p_upd.add_argument("--pace-fast", type=float, default=None)
    p_upd.add_argument("--pace-slow", type=float, default=None)
    p_upd.add_argument("--description", default=None)
    p_upd.add_argument("--notes", default=None)
    p_upd.add_argument("--status", default=None, choices=["planned", "completed", "skipped", "modified"])

    p_del = sub.add_parser("delete", help="Delete a planned session")
    p_del.add_argument("--id", type=int, required=True)

    return p


DISPATCH = {
    "add": cmd_add,
    "add-bulk": cmd_add_bulk,
    "list": cmd_list,
    "review": cmd_review,
    "update": cmd_update,
    "delete": cmd_delete,
}


def main() -> None:
    args = build_parser().parse_args()
    try:
        db = get_default_db_path()
        token = load_token(db)
        if not token:
            output_error("No token. Run strava-setup first.")
        athlete_id = token["athlete_id"]
        DISPATCH[args.cmd](db, athlete_id, args)
    except ValueError as e:
        output_error(str(e))
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
