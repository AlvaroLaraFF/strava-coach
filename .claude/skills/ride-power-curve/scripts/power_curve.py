#!/usr/bin/env python3
"""All-time mean-max power curve from rides."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import estimate_ftp_from_mmp, mean_max_curve
from strava.client import StravaClient, get_default_db_path, output_error, output_json
from strava.db import get_activities_range
from strava.sync import ensure_streams


RIDE_TYPES = {"Ride", "VirtualRide", "GravelRide", "MountainBikeRide", "EBikeRide"}
WINDOWS = [1, 5, 15, 30, 60, 300, 600, 1200, 3600]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--max-rides", type=int, default=30)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        client = StravaClient(db)

        rides = [a for a in get_activities_range(db, days=args.days)
                 if a.get("sport_type") in RIDE_TYPES]
        rides = rides[:args.max_rides]
        if not rides:
            output_error("No rides in window.")

        all_time: dict[int, float] = {w: 0.0 for w in WINDOWS}
        attribution: dict[int, str] = {}

        rides_with_watts = 0
        for r in rides:
            try:
                streams = ensure_streams(client, db, r["strava_id"])
            except Exception:
                continue
            watts = (streams.get("watts") or {}).get("data", [])
            if not watts:
                continue
            rides_with_watts += 1
            curve = mean_max_curve(watts, WINDOWS)
            for w, v in curve.items():
                if v > all_time[w]:
                    all_time[w] = v
                    attribution[w] = (r.get("start_date") or "")[:10] + " " + (r.get("name") or "")

        if rides_with_watts == 0:
            output_error("None of the recent rides had a watts stream.")

        rounded = {f"{w}s": round(v, 0) for w, v in all_time.items() if v > 0}
        ftp_est = estimate_ftp_from_mmp(all_time)

        output_json({
            "mean_max_power": rounded,
            "attribution": attribution,
            "estimated_ftp_w": ftp_est,
            "rides_used": rides_with_watts,
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
