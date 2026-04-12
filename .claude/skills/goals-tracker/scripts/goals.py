#!/usr/bin/env python3
"""Goal CRUD and progress tracker."""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import parse_iso
from strava.client import get_default_db_path, output_error, output_json
from strava.db import add_goal, get_activities_range, list_goals, load_token


def period_range(period: str) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    if period == "week":
        start = now - timedelta(days=now.weekday())
        end = start + timedelta(days=7)
    elif period == "month":
        start = now.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)
    elif period == "year":
        start = now.replace(month=1, day=1)
        end = start.replace(year=start.year + 1)
    else:
        raise ValueError(f"unknown period: {period}")
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def metric_value(activity: dict, metric: str) -> float:
    if metric == "distance":
        return (activity.get("distance") or 0) / 1000
    if metric == "time":
        return (activity.get("moving_time") or 0) / 60
    if metric == "elevation":
        return activity.get("total_elevation") or 0
    return 0.0


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("--metric", choices=["distance", "time", "elevation"], required=True)
    p_add.add_argument("--period", choices=["week", "month", "year"], required=True)
    p_add.add_argument("--sport", default=None)
    p_add.add_argument("--target", type=float, required=True)

    sub.add_parser("list")

    args = p.parse_args()

    try:
        db = get_default_db_path()
        token = load_token(db)
        if not token:
            output_error("No token. Run strava-setup first.")
        athlete_id = token["athlete_id"]

        if args.cmd == "add":
            start, end = period_range(args.period)
            gid = add_goal(db, athlete_id, args.metric, args.period, args.sport, args.target, start, end)
            output_json({"created": True, "goal_id": gid, "start": start, "end": end})
            return

        goals = list_goals(db, athlete_id)
        if not goals:
            output_json({"goals": []})
            return

        out = []
        now = datetime.now(timezone.utc)
        for g in goals:
            start = datetime.strptime(g["start_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end = datetime.strptime(g["end_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            elapsed_days = max((now - start).days, 1)
            total_days = max((end - start).days, 1)
            window_days = min(total_days, max(elapsed_days, 1))
            acts = get_activities_range(db, days=window_days + 1)
            current = 0.0
            for a in acts:
                sd = a.get("start_date")
                if not sd:
                    continue
                d = parse_iso(sd)
                if d < start or d >= end:
                    continue
                if g["sport_type"] and a.get("sport_type") != g["sport_type"]:
                    continue
                current += metric_value(a, g["metric"])
            pct = round(current / g["target"] * 100, 1) if g["target"] else 0
            time_pct = round(elapsed_days / total_days * 100, 1)
            on_pace = pct >= time_pct - 5
            if pct >= 100:
                status = "DONE"
            elif on_pace:
                status = "ON_TRACK"
            else:
                status = "BEHIND"
            projection = round(current / max(elapsed_days, 1) * total_days, 1)
            out.append({
                "id": g["id"],
                "metric": g["metric"],
                "period": g["period"],
                "sport": g["sport_type"],
                "target": g["target"],
                "current": round(current, 1),
                "percent": pct,
                "time_percent": time_pct,
                "projection_at_end": projection,
                "status": status,
            })
        output_json({"goals": out})
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
