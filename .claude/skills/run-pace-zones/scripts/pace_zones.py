#!/usr/bin/env python3
"""Run pace zones (Daniels-style) and current distribution."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import fmt_pace, pace_min_per_km
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range


RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def parse_pace(s: str) -> float:
    m, sec = s.split(":")
    return int(m) + int(sec) / 60.0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--threshold-pace", type=str, default=None,
                   help="threshold pace as M:SS per km")
    args = p.parse_args()

    try:
        db = get_default_db_path()
        activities = [a for a in get_activities_range(db, days=args.days)
                      if a.get("sport_type") in RUN_TYPES]
        if not activities:
            output_error("No recent runs found.")

        if args.threshold_pace:
            threshold = parse_pace(args.threshold_pace)
        else:
            longest = max(activities, key=lambda a: a.get("moving_time") or 0)
            tp = pace_min_per_km(longest.get("distance") or 0, longest.get("moving_time") or 0)
            if not tp:
                output_error("Could not auto-detect threshold pace.")
            threshold = tp * 0.97

        zones = {
            "Z1_recovery": {"low": threshold * 1.30, "high": threshold * 1.50},
            "Z2_easy":     {"low": threshold * 1.15, "high": threshold * 1.30},
            "Z3_marathon": {"low": threshold * 1.05, "high": threshold * 1.15},
            "Z4_threshold":{"low": threshold * 0.97, "high": threshold * 1.05},
            "Z5_vo2max":   {"low": threshold * 0.85, "high": threshold * 0.97},
        }

        for z in zones.values():
            z["low_str"] = fmt_pace(z["low"])
            z["high_str"] = fmt_pace(z["high"])

        distribution = {k: 0 for k in zones}
        for a in activities:
            pace = pace_min_per_km(a.get("distance") or 0, a.get("moving_time") or 0)
            if not pace:
                continue
            for name, z in zones.items():
                if z["high"] >= pace >= z["low"]:
                    distribution[name] += 1
                    break

        easy_count = distribution["Z1_recovery"] + distribution["Z2_easy"]
        total = sum(distribution.values())
        easy_pct = round(easy_count / total * 100, 1) if total else 0

        if easy_pct >= 75:
            verdict = "GOOD: enough easy running"
        elif easy_pct >= 60:
            verdict = "OK but could be more easy"
        else:
            verdict = "TOO MUCH HARD RUNNING — slow down easy days"

        output_json({
            "threshold_pace": fmt_pace(threshold),
            "zones": zones,
            "recent_distribution": distribution,
            "easy_pct": easy_pct,
            "verdict": verdict,
            "runs_analyzed": len(activities),
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
