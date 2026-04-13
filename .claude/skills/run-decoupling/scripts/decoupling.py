#!/usr/bin/env python3
"""Aerobic decoupling on recent long runs."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import aerobic_decoupling
from strava.client import StravaClient, get_default_db_path, output_error, output_json
from strava.db import get_activities_range
from strava.sync import ensure_streams


RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--min-minutes", type=int, default=60)
    p.add_argument("--max-runs", type=int, default=5)
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--hr-max", type=float, default=190.0)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        client = StravaClient(db)

        activities = [a for a in get_activities_range(db, days=args.days)
                      if a.get("sport_type") in RUN_TYPES
                      and (a.get("moving_time") or 0) >= args.min_minutes * 60
                      and (
                          not a.get("average_hr")
                          or a["average_hr"] <= args.hr_max * 0.85
                      )]
        if not activities:
            output_error(f"No runs >{args.min_minutes} minutes in the last {args.days} days.")

        activities = activities[:args.max_runs]
        results = []
        for a in activities:
            try:
                streams = ensure_streams(client, db, a["strava_id"])
            except Exception as e:
                results.append({
                    "strava_id": a["strava_id"],
                    "date": (a.get("start_date") or "")[:10],
                    "error": str(e)[:200],
                })
                continue

            speed = (streams.get("velocity_smooth") or {}).get("data", [])
            hr = (streams.get("heartrate") or {}).get("data", [])
            if not speed or not hr:
                continue

            dec = aerobic_decoupling(speed, hr)
            verdict = "GOOD" if abs(dec) < 5 else ("OK" if abs(dec) < 8 else "POOR base")
            results.append({
                "date": (a.get("start_date") or "")[:10],
                "name": a.get("name"),
                "duration_min": round((a.get("moving_time") or 0) / 60, 1),
                "decoupling_pct": dec,
                "verdict": verdict,
            })

        if not results:
            output_error("Long runs found but no usable speed+HR streams.")

        valid = [r for r in results if "decoupling_pct" in r]
        avg = round(sum(r["decoupling_pct"] for r in valid) / len(valid), 2) if valid else None
        output_json({
            "runs": results,
            "average_decoupling_pct": avg,
            "min_minutes": args.min_minutes,
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
