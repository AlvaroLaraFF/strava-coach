#!/usr/bin/env python3
"""List recent Strava activities.

Usage:
    python3 scripts/list_activities.py [--sync] [--limit 20] [--sport-type Run] [--days 30]
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strava.client import StravaClient, StravaAuthError, StravaAPIError, get_default_db_path, output_json, output_error
from strava.db import init_db, upsert_activities, get_recent_activities


def _format_activity(act: dict) -> dict:
    """Convert a DB activity row to a human-readable format."""
    distance_km = (act.get("distance") or 0) / 1000
    moving_secs = act.get("moving_time") or 0
    hours, rem = divmod(moving_secs, 3600)
    mins, secs = divmod(rem, 60)
    duration = f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins}:{secs:02d}"

    result = {
        "date": (act.get("start_date") or "")[:10],
        "type": act.get("sport_type", ""),
        "name": act.get("name", ""),
        "distance_km": round(distance_km, 2),
        "duration": duration,
        "elevation_m": round(act.get("total_elevation") or 0, 0),
    }

    if act.get("sport_type") in ("Run", "TrailRun", "Walk") and distance_km > 0:
        pace_secs = moving_secs / distance_km
        p_min, p_sec = divmod(int(pace_secs), 60)
        result["pace_min_km"] = f"{p_min}:{p_sec:02d}"
    elif distance_km > 0:
        result["speed_kmh"] = round(distance_km / (moving_secs / 3600), 1) if moving_secs else 0

    if act.get("average_hr"):
        result["avg_hr"] = round(act["average_hr"])
    if act.get("max_hr"):
        result["max_hr"] = round(act["max_hr"])

    return result


def main():
    parser = argparse.ArgumentParser(description="List Strava activities")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--sport-type", default=None, help="e.g. Run, Ride, Swim")
    parser.add_argument("--sync", action="store_true", help="Download from Strava before showing")
    parser.add_argument("--days", type=int, default=None, help="Filter last N days")
    args = parser.parse_args()

    try:
        db_path = get_default_db_path()
        init_db(db_path)

        if args.sync:
            client = StravaClient(db_path)
            params = {"per_page": min(args.limit * 2, 100)}
            if args.days:
                after = int((datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp())
                params["after"] = after
            raw = client.get_activities(**params)
            upsert_activities(db_path, raw)

        activities = get_recent_activities(db_path, limit=args.limit, sport_type=args.sport_type)
        formatted = [_format_activity(a) for a in activities]
        output_json({"activities": formatted, "count": len(formatted)})

    except StravaAuthError as e:
        output_error(str(e))
    except StravaAPIError as e:
        output_error(str(e))
    except Exception as e:
        output_error(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
