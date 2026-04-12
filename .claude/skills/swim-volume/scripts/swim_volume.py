#!/usr/bin/env python3
"""Swim volume per week / month."""

import argparse
import os
import sys
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import iso_week, parse_iso
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--weeks", type=int, default=12)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        swims = [a for a in get_activities_range(db, days=args.weeks * 7 + 7)
                 if a.get("sport_type") == "Swim"]
        if not swims:
            output_error("No swims in window.")

        weekly: dict[str, dict] = defaultdict(lambda: {"distance_m": 0, "time_min": 0, "sessions": 0})
        monthly: dict[str, dict] = defaultdict(lambda: {"distance_m": 0, "time_min": 0, "sessions": 0})

        for s in swims:
            sd = s.get("start_date")
            if not sd:
                continue
            w = iso_week(sd)
            m = parse_iso(sd).strftime("%Y-%m")
            d = s.get("distance") or 0
            t = (s.get("moving_time") or 0) / 60
            for bucket in (weekly[w], monthly[m]):
                bucket["distance_m"] += d
                bucket["time_min"] += t
                bucket["sessions"] += 1

        weekly_rows = sorted(weekly.items(), reverse=True)[:args.weeks]
        monthly_rows = sorted(monthly.items(), reverse=True)[:6]

        weekly_dist = [v["distance_m"] for _, v in weekly_rows]
        if len(weekly_dist) >= 4:
            first_avg = sum(weekly_dist[-4:]) / 4
            last_avg = sum(weekly_dist[:4]) / 4
            if last_avg > first_avg * 1.1:
                trend = "INCREASING"
            elif last_avg < first_avg * 0.9:
                trend = "DECREASING"
            else:
                trend = "STEADY"
        else:
            trend = "INSUFFICIENT_HISTORY"

        output_json({
            "weekly": [{"week": w, "distance_m": round(v["distance_m"]),
                        "time_min": round(v["time_min"], 1),
                        "sessions": v["sessions"]} for w, v in weekly_rows],
            "monthly": [{"month": m, "distance_m": round(v["distance_m"]),
                         "time_min": round(v["time_min"], 1),
                         "sessions": v["sessions"]} for m, v in monthly_rows],
            "trend": trend,
            "total_swims": len(swims),
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
