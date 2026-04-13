#!/usr/bin/env python3
"""Compute CTL/ATL/TSB from the local activity history."""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import (
    banister_trimp,
    fmt_duration,
    normalized_power,
    parse_iso,
    pmc_series,
    tss,
)
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range, load_user_profile


def daily_load_from_activity(act: dict, ftp: float, hr_max: float, hr_rest: float, sex: str = "M") -> float:
    """Single number representing today's training stress for one activity."""
    avg_w = act.get("average_watts") or 0
    duration_s = act.get("moving_time") or 0
    if avg_w and ftp and duration_s:
        intensity = avg_w / ftp
        return tss(duration_s, avg_w, intensity, ftp)
    avg_hr = act.get("average_hr") or 0
    if avg_hr and duration_s:
        return banister_trimp(duration_s / 60, avg_hr, hr_rest, hr_max, sex)
    return 0.0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=120)
    p.add_argument("--ftp", type=float, default=200.0)
    p.add_argument("--hr-max", type=float, default=190.0)
    p.add_argument("--hr-rest", type=float, default=55.0)
    p.add_argument("--gender", type=str, default=None, help="M or F (loaded from profile if not set)")
    args = p.parse_args()

    try:
        db = get_default_db_path()

        profile = load_user_profile(db)
        sex = args.gender or (profile.get("gender") if profile else None) or "M"

        activities = get_activities_range(db, days=args.days)
        if not activities:
            output_error("No activities found in the local DB. Sync first.")

        per_day: dict[str, float] = defaultdict(float)
        for a in activities:
            sd = a.get("start_date")
            if not sd:
                continue
            day = parse_iso(sd).strftime("%Y-%m-%d")
            per_day[day] += daily_load_from_activity(a, args.ftp, args.hr_max, args.hr_rest, sex)

        if not per_day:
            output_error("No usable HR or power data in the activities.")

        sorted_days = sorted(per_day.items())
        first = sorted_days[0][0]
        last_dt = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        full_range = []
        cur = datetime.strptime(first, "%Y-%m-%d")
        end = datetime.strptime(last_dt, "%Y-%m-%d")
        d = cur
        while d <= end:
            key = d.strftime("%Y-%m-%d")
            full_range.append((key, per_day.get(key, 0.0)))
            d += timedelta(days=1)

        series = pmc_series(full_range)
        if not series:
            output_error("PMC series is empty.")

        today = series[-1]
        seven_days_ago = series[-8] if len(series) > 7 else series[0]
        peak_ctl = max(series, key=lambda r: r["ctl"])
        lowest_tsb = min(series, key=lambda r: r["tsb"])

        output_json({
            "today": today,
            "delta_7d": {
                "ctl": round(today["ctl"] - seven_days_ago["ctl"], 1),
                "atl": round(today["atl"] - seven_days_ago["atl"], 1),
                "tsb": round(today["tsb"] - seven_days_ago["tsb"], 1),
            },
            "peak_ctl": peak_ctl,
            "lowest_tsb": lowest_tsb,
            "series": series[-30:],
            "params": {
                "ftp": args.ftp,
                "hr_max": args.hr_max,
                "hr_rest": args.hr_rest,
                "window_days": args.days,
                "activities_used": len(activities),
            },
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
