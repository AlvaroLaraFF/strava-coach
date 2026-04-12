#!/usr/bin/env python3
"""Climbing analysis for rides: VAM and W/kg."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import vam, watts_per_kg
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range


RIDE_TYPES = {"Ride", "VirtualRide", "GravelRide", "MountainBikeRide", "EBikeRide"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--weight-kg", type=float, default=70.0)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        rides = [a for a in get_activities_range(db, days=args.days)
                 if a.get("sport_type") in RIDE_TYPES]
        rides_prev = [a for a in get_activities_range(db, days=args.days * 2)
                      if a.get("sport_type") in RIDE_TYPES][len(rides):]
        if not rides:
            output_error("No rides in window.")

        rows = []
        for r in rides:
            elev = r.get("total_elevation") or 0
            duration = r.get("moving_time") or 0
            if elev < 100:
                continue
            v = vam(elev, duration)
            wkg = watts_per_kg(r.get("average_watts") or 0, args.weight_kg)
            rows.append({
                "date": (r.get("start_date") or "")[:10],
                "name": r.get("name"),
                "distance_km": round((r.get("distance") or 0) / 1000, 1),
                "elevation_m": round(elev),
                "duration_min": round(duration / 60, 1),
                "vam_m_h": v,
                "avg_watts": round(r.get("average_watts") or 0, 0),
                "w_per_kg": wkg,
            })

        if not rows:
            output_error("No climby rides (>100m elevation) in window.")

        top_vam = sorted(rows, key=lambda r: r["vam_m_h"], reverse=True)[:5]
        avg_vam = round(sum(r["vam_m_h"] for r in rows) / len(rows), 0)
        max_vam = max(r["vam_m_h"] for r in rows)

        prev_vams = [vam(r.get("total_elevation") or 0, r.get("moving_time") or 0)
                     for r in rides_prev if (r.get("total_elevation") or 0) >= 100]
        prev_avg = round(sum(prev_vams) / len(prev_vams), 0) if prev_vams else None
        if prev_avg:
            delta = avg_vam - prev_avg
            trend = "IMPROVING" if delta > 30 else ("DECLINING" if delta < -30 else "STEADY")
        else:
            trend = "INSUFFICIENT_HISTORY"

        output_json({
            "average_vam": avg_vam,
            "max_vam": max_vam,
            "trend_vs_previous_window": trend,
            "previous_window_avg_vam": prev_avg,
            "top_rides": top_vam,
            "weight_kg_used": args.weight_kg,
            "rides_analyzed": len(rows),
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
