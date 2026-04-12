#!/usr/bin/env python3
"""Group activities by route similarity and show pace progression."""

import argparse
import json
import math
import os
import sys
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import fmt_pace, pace_min_per_km, parse_iso
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range


def signature(payload: dict, distance_m: float) -> tuple | None:
    sl = payload.get("start_latlng") or []
    el = payload.get("end_latlng") or []
    if len(sl) != 2 or len(el) != 2:
        return None
    # Round coordinates to ~100m, distance to nearest 200m
    return (
        round(sl[0], 3),
        round(sl[1], 3),
        round(el[0], 3),
        round(el[1], 3),
        round(distance_m / 200) * 200,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--sport", default="Run")
    p.add_argument("--min-occurrences", type=int, default=3)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        activities = [a for a in get_activities_range(db, days=args.days)
                      if a.get("sport_type") == args.sport]
        if not activities:
            output_error(f"No {args.sport} activities in window.")

        groups: dict[tuple, list[dict]] = defaultdict(list)
        for a in activities:
            try:
                payload = json.loads(a.get("raw_json") or "{}")
            except ValueError:
                continue
            sig = signature(payload, a.get("distance") or 0)
            if not sig:
                continue
            pace = pace_min_per_km(a.get("distance") or 0, a.get("moving_time") or 0)
            if not pace:
                continue
            groups[sig].append({
                "date": (a.get("start_date") or "")[:10],
                "pace": pace,
                "pace_str": fmt_pace(pace),
                "name": a.get("name"),
            })

        result = []
        for sig, runs in groups.items():
            if len(runs) < args.min_occurrences:
                continue
            runs.sort(key=lambda r: r["date"])
            first = runs[0]
            last = runs[-1]
            d1 = parse_iso(first["date"]).timestamp()
            d2 = parse_iso(last["date"]).timestamp()
            months = max((d2 - d1) / (86400 * 30), 0.5)
            slope_s_per_km_per_month = round((last["pace"] - first["pace"]) * 60 / months, 1)
            improvement_direction = "FASTER" if slope_s_per_km_per_month < -2 else (
                "SLOWER" if slope_s_per_km_per_month > 2 else "STABLE"
            )
            result.append({
                "signature": {
                    "start_lat": sig[0],
                    "start_lng": sig[1],
                    "end_lat": sig[2],
                    "end_lng": sig[3],
                    "distance_m": sig[4],
                },
                "occurrences": len(runs),
                "first": first["date"],
                "last": last["date"],
                "first_pace": first["pace_str"],
                "last_pace": last["pace_str"],
                "trend_s_per_km_per_month": slope_s_per_km_per_month,
                "trend": improvement_direction,
                "runs": runs,
            })

        result.sort(key=lambda r: r["occurrences"], reverse=True)
        output_json({"groups": result, "total_groups": len(result)})
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
