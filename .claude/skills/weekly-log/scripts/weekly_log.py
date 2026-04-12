#!/usr/bin/env python3
"""Group activities by ISO week."""

import argparse
import os
import sys
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import iso_week
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range


SPORT_BUCKET = {
    "Run": "run", "TrailRun": "run", "VirtualRun": "run",
    "Ride": "ride", "VirtualRide": "ride", "GravelRide": "ride",
    "MountainBikeRide": "ride", "EBikeRide": "ride",
    "Swim": "swim",
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--weeks", type=int, default=8)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        activities = get_activities_range(db, days=args.weeks * 7 + 7)
        if not activities:
            output_error("No activities in the local DB.")

        weeks: dict[str, dict] = defaultdict(lambda: {
            "activities": 0, "run_km": 0.0, "ride_km": 0.0,
            "swim_km": 0.0, "other_km": 0.0,
            "time_min": 0.0, "elev_m": 0.0,
        })
        for a in activities:
            sd = a.get("start_date")
            if not sd:
                continue
            w = iso_week(sd)
            bucket = weeks[w]
            bucket["activities"] += 1
            dist_km = (a.get("distance") or 0) / 1000
            bucket_key = SPORT_BUCKET.get(a.get("sport_type") or "", "other")
            bucket[f"{bucket_key}_km"] += round(dist_km, 2)
            bucket["time_min"] += round((a.get("moving_time") or 0) / 60, 1)
            bucket["elev_m"] += a.get("total_elevation") or 0

        sorted_weeks = sorted(weeks.items(), reverse=True)[:args.weeks]
        rows = [{"week": w, **{k: round(v, 1) if isinstance(v, float) else v for k, v in d.items()}} for w, d in sorted_weeks]

        total_dist_per_week = [r["run_km"] + r["ride_km"] + r["swim_km"] + r["other_km"] for r in rows]
        avg = sum(total_dist_per_week) / len(total_dist_per_week) if total_dist_per_week else 0

        output_json({"weeks": rows, "average_total_km": round(avg, 1)})
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
