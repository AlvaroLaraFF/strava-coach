#!/usr/bin/env python3
"""SWOLF trend per pool swim."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import swolf
from strava.client import StravaClient, get_default_db_path, output_error, output_json
from strava.db import get_activities_range
from strava.sync import ensure_laps


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=60)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        client = StravaClient(db)
        swims = [a for a in get_activities_range(db, days=args.days)
                 if a.get("sport_type") == "Swim"]
        if not swims:
            output_error("No swims in window.")

        sessions = []
        for s in swims:
            try:
                laps = ensure_laps(client, db, s["strava_id"])
            except Exception:
                continue
            swolfs = []
            for lap in laps or []:
                t = lap.get("elapsed_time")
                # Strava swim laps don't expose stroke count directly via API,
                # we use the proxy: average_cadence * (elapsed_time/60) ≈ strokes
                cad = lap.get("average_cadence") or 0
                if not t or not cad:
                    continue
                strokes = round(cad * (t / 60.0))
                swolfs.append(swolf(t, strokes))
            if not swolfs:
                continue
            avg = sum(swolfs) / len(swolfs)
            sessions.append({
                "date": (s.get("start_date") or "")[:10],
                "name": s.get("name"),
                "distance_m": s.get("distance"),
                "average_swolf": round(avg, 1),
                "laps_used": len(swolfs),
            })

        if not sessions:
            output_error("No swims with usable lap data.")

        sessions.sort(key=lambda r: r["date"])
        first = sessions[0]["average_swolf"]
        last = sessions[-1]["average_swolf"]
        trend = "IMPROVING" if last < first - 1 else ("DECLINING" if last > first + 1 else "STEADY")

        avg_all = round(sum(s["average_swolf"] for s in sessions) / len(sessions), 1)
        if avg_all < 30:
            level = "ELITE"
        elif avg_all < 40:
            level = "TRAINED"
        elif avg_all < 50:
            level = "RECREATIONAL"
        else:
            level = "BEGINNER"

        output_json({
            "average_swolf": avg_all,
            "level": level,
            "trend": trend,
            "first_session": first,
            "last_session": last,
            "sessions": sessions,
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
