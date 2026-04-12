#!/usr/bin/env python3
"""Per-ride power-based TSS / NP / IF / VI."""

import argparse
import os
import sys
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import (
    intensity_factor,
    iso_week,
    normalized_power,
    tss,
    variability_index,
)
from strava.client import StravaClient, get_default_db_path, output_error, output_json
from strava.db import get_activities_range
from strava.sync import ensure_streams


RIDE_TYPES = {"Ride", "VirtualRide", "GravelRide", "MountainBikeRide", "EBikeRide"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--ftp", type=float, required=True)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        client = StravaClient(db)
        rides = [a for a in get_activities_range(db, days=args.days)
                 if a.get("sport_type") in RIDE_TYPES]
        if not rides:
            output_error("No rides in window.")

        rows = []
        weekly: dict[str, float] = defaultdict(float)
        for r in rides:
            try:
                streams = ensure_streams(client, db, r["strava_id"])
            except Exception:
                continue
            watts = (streams.get("watts") or {}).get("data", [])
            if not watts:
                continue
            np_val = normalized_power(watts)
            if not np_val:
                continue
            duration_s = r.get("moving_time") or 0
            i_f = intensity_factor(np_val, args.ftp)
            tss_val = tss(duration_s, np_val, i_f, args.ftp)
            vi = variability_index(np_val, r.get("average_watts") or 0)
            week = iso_week(r["start_date"])
            weekly[week] += tss_val
            rows.append({
                "date": (r.get("start_date") or "")[:10],
                "name": r.get("name"),
                "duration_min": round(duration_s / 60, 1),
                "np_w": round(np_val, 0),
                "if": round(i_f, 2),
                "tss": round(tss_val, 0),
                "vi": round(vi, 2),
            })

        if not rows:
            output_error("No rides with usable watts streams.")

        weekly_rows = [{"week": w, "tss": round(t, 0)} for w, t in sorted(weekly.items(), reverse=True)]

        output_json({
            "rides": rows,
            "weekly_tss": weekly_rows,
            "ftp_used": args.ftp,
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
