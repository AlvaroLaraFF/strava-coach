#!/usr/bin/env python3
"""Consistency metrics: streaks, frequency, weekly CV."""

import argparse
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

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
        activities = get_activities_range(db, days=args.weeks * 7 + 7)
        if not activities:
            output_error("No activities.")

        days_with_activity: set[str] = set()
        weeks: dict[str, float] = defaultdict(float)
        for a in activities:
            sd = a.get("start_date")
            if not sd:
                continue
            day = parse_iso(sd).strftime("%Y-%m-%d")
            days_with_activity.add(day)
            weeks[iso_week(sd)] += (a.get("distance") or 0) / 1000

        today = datetime.now(timezone.utc)
        streak = 0
        for i in range(0, 365):
            day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            if day in days_with_activity:
                streak += 1
            else:
                if i == 0:
                    continue
                break

        weeks_sorted = sorted(weeks.items())[-args.weeks:]
        weekly_dist = [v for _, v in weeks_sorted]
        if weekly_dist:
            mean = sum(weekly_dist) / len(weekly_dist)
            var = sum((x - mean) ** 2 for x in weekly_dist) / len(weekly_dist)
            std = math.sqrt(var)
            cv = round((std / mean * 100), 1) if mean else 0
        else:
            mean = 0
            cv = 0

        days_per_week = round(len(days_with_activity) / max(args.weeks, 1), 1)

        if days_per_week >= 5 and cv < 25:
            verdict = "HIGHLY CONSISTENT"
        elif days_per_week >= 3 and cv < 40:
            verdict = "CONSISTENT"
        else:
            verdict = "IRREGULAR"

        output_json({
            "verdict": verdict,
            "current_streak_days": streak,
            "average_days_per_week": days_per_week,
            "weekly_volume_cv_pct": cv,
            "average_weekly_km": round(mean, 1),
            "weeks_analyzed": len(weeks_sorted),
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
