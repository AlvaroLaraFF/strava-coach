#!/usr/bin/env python3
"""Triathlon discipline balance."""

import argparse
import os
import sys
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range


SPORT_GROUP = {
    "Run": "run", "TrailRun": "run", "VirtualRun": "run",
    "Ride": "ride", "VirtualRide": "ride", "GravelRide": "ride",
    "MountainBikeRide": "ride", "EBikeRide": "ride",
    "Swim": "swim",
}

# Approximate "ideal" time-distribution for sprint/olympic distance triathlon
TARGET_PCT = {"run": 30.0, "ride": 55.0, "swim": 15.0}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        activities = [a for a in get_activities_range(db, days=args.days)
                      if SPORT_GROUP.get(a.get("sport_type") or "")]
        if not activities:
            output_error("No tri-relevant activities in window.")

        bucket: dict[str, dict] = defaultdict(lambda: {"time_min": 0.0, "distance_km": 0.0, "sessions": 0})
        for a in activities:
            sport = SPORT_GROUP[a["sport_type"]]
            bucket[sport]["time_min"] += (a.get("moving_time") or 0) / 60
            bucket[sport]["distance_km"] += (a.get("distance") or 0) / 1000
            bucket[sport]["sessions"] += 1

        total_time = sum(b["time_min"] for b in bucket.values()) or 1
        out = {}
        for sport in ("run", "ride", "swim"):
            b = bucket.get(sport, {"time_min": 0, "distance_km": 0, "sessions": 0})
            pct = round(b["time_min"] / total_time * 100, 1)
            target = TARGET_PCT[sport]
            gap = round(pct - target, 1)
            out[sport] = {
                "time_hours": round(b["time_min"] / 60, 2),
                "time_pct": pct,
                "target_pct": target,
                "gap_pct": gap,
                "distance_km": round(b["distance_km"], 1),
                "sessions": b["sessions"],
            }

        ranked = sorted(out.items(), key=lambda kv: kv[1]["gap_pct"])
        most_under = ranked[0]
        most_over = ranked[-1]
        if abs(most_under[1]["gap_pct"]) >= 10:
            advice = f"You are under-trained on {most_under[0]} (gap {most_under[1]['gap_pct']}pp). Add one session/week."
        elif abs(most_over[1]["gap_pct"]) >= 15:
            advice = f"Possibly over-weighted on {most_over[0]}. Convert one session to {most_under[0]}."
        else:
            advice = "Distribution is balanced for sprint/olympic-distance training."

        output_json({
            "discipline": out,
            "total_hours": round(total_time / 60, 2),
            "advice": advice,
            "window_days": args.days,
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
