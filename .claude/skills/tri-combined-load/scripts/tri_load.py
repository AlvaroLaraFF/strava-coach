#!/usr/bin/env python3
"""Combined triathlon PMC across the three disciplines."""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import (
    banister_trimp,
    normalized_power,
    parse_iso,
    pmc_series,
    tss,
)
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range, load_streams, load_user_profile


SPORT_GROUP = {
    "Run": "run", "TrailRun": "run", "VirtualRun": "run",
    "Ride": "ride", "VirtualRide": "ride", "GravelRide": "ride",
    "MountainBikeRide": "ride", "EBikeRide": "ride",
    "Swim": "swim",
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--ftp", type=float, default=200.0)
    p.add_argument("--hr-max", type=float, default=190.0)
    p.add_argument("--hr-rest", type=float, default=55.0)
    p.add_argument("--gender", type=str, default=None, help="M or F (loaded from profile if not set)")
    args = p.parse_args()

    try:
        db = get_default_db_path()

        profile = load_user_profile(db)
        sex = args.gender or (profile.get("gender") if profile else None) or "M"

        activities = [a for a in get_activities_range(db, days=args.days)
                      if SPORT_GROUP.get(a.get("sport_type") or "")]
        if not activities:
            output_error("No tri-relevant activities in window.")

        per_day_total: dict[str, float] = defaultdict(float)
        per_day_sport: dict[str, dict[str, float]] = defaultdict(lambda: {"run": 0, "ride": 0, "swim": 0})

        for a in activities:
            sd = a.get("start_date")
            if not sd:
                continue
            day = parse_iso(sd).strftime("%Y-%m-%d")
            sport = SPORT_GROUP[a["sport_type"]]
            duration_s = a.get("moving_time") or 0
            avg_w = a.get("average_watts") or 0
            avg_hr = a.get("average_hr") or 0

            if sport == "ride" and avg_w and args.ftp and duration_s:
                np_val = avg_w
                streams = load_streams(db, a.get("strava_id"))
                if streams and "watts" in streams:
                    watts_data = streams["watts"]
                    if isinstance(watts_data, dict):
                        watts_data = watts_data.get("data", [])
                    np_calc = normalized_power(watts_data)
                    if np_calc > 0:
                        np_val = np_calc
                i_f = np_val / args.ftp
                load = tss(duration_s, np_val, i_f, args.ftp)
            elif avg_hr and duration_s:
                load = banister_trimp(duration_s / 60, avg_hr, args.hr_rest, args.hr_max, sex)
            else:
                load = 0.0

            per_day_total[day] += load
            per_day_sport[day][sport] += load

        sorted_days = sorted(per_day_total.items())
        first = sorted_days[0][0]
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        d = datetime.strptime(first, "%Y-%m-%d")
        end_d = datetime.strptime(end, "%Y-%m-%d")
        full = []
        while d <= end_d:
            key = d.strftime("%Y-%m-%d")
            full.append((key, per_day_total.get(key, 0.0)))
            d += timedelta(days=1)

        series = pmc_series(full)
        today = series[-1] if series else {"ctl": 0, "atl": 0, "tsb": 0}

        last_7d_sport = {"run": 0.0, "ride": 0.0, "swim": 0.0}
        for i in range(7):
            day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            for sp, v in per_day_sport.get(day, {}).items():
                last_7d_sport[sp] += v
        dominant = max(last_7d_sport, key=last_7d_sport.get)

        output_json({
            "today": today,
            "last_7d_load_per_sport": {k: round(v, 1) for k, v in last_7d_sport.items()},
            "dominant_sport_7d": dominant,
            "series_last_30d": series[-30:],
            "params": {"ftp": args.ftp, "hr_max": args.hr_max, "hr_rest": args.hr_rest},
            "load_note": "TRIMP (HR) and TSS (power) combined without scaling — interpret with caution",
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
