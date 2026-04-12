#!/usr/bin/env python3
"""Fetch global athlete statistics from Strava.

Usage:
    python3 .claude/skills/strava-coach/scripts/get_stats.py [--refresh]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))
from strava.client import StravaClient, StravaAuthError, StravaAPIError, get_default_db_path, output_json, output_error
from strava.db import init_db, load_token, save_athlete_stats, get_latest_stats, get_activities_range


def _format_distance(meters: float) -> str:
    if meters >= 1000:
        return f"{meters / 1000:.1f} km"
    return f"{meters:.0f} m"


def _compute_derived(db_path: str) -> dict:
    """Derived metrics from activities in the database."""
    recent = get_activities_range(db_path, days=30)
    if not recent:
        return {"message": "No activities in the last 30 days"}

    total_distance = sum(a.get("distance") or 0 for a in recent)
    total_time = sum(a.get("moving_time") or 0 for a in recent)
    sport_counts: dict[str, int] = {}
    for a in recent:
        sport = a.get("sport_type") or "Other"
        sport_counts[sport] = sport_counts.get(sport, 0) + 1

    weeks = max(1, 30 / 7)
    return {
        "last_30_days": {
            "activities": len(recent),
            "total_distance": _format_distance(total_distance),
            "total_time_hours": round(total_time / 3600, 1),
            "activities_per_week": round(len(recent) / weeks, 1),
            "by_sport": sport_counts,
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Strava athlete statistics")
    parser.add_argument("--refresh", action="store_true", help="Download fresh stats from Strava")
    args = parser.parse_args()

    try:
        db_path = get_default_db_path()
        init_db(db_path)

        token = load_token(db_path)
        if not token:
            output_error("No token found. Run strava-setup first.")

        athlete_id = token["athlete_id"]

        if args.refresh:
            client = StravaClient(db_path)
            raw_stats = client.get_athlete_stats(athlete_id)
            save_athlete_stats(db_path, athlete_id, raw_stats)

        stats = get_latest_stats(db_path, athlete_id)
        if not stats:
            output_error("No stats stored yet. Use --refresh to download them.")

        result = {
            "ytd": {
                "running": _format_distance(stats.get("ytd_run_m") or 0),
                "cycling": _format_distance(stats.get("ytd_ride_m") or 0),
                "swimming": _format_distance(stats.get("ytd_swim_m") or 0),
            },
            "all_time": {
                "running": _format_distance(stats.get("all_run_m") or 0),
                "cycling": _format_distance(stats.get("all_ride_m") or 0),
                "swimming": _format_distance(stats.get("all_swim_m") or 0),
            },
            "derived": _compute_derived(db_path),
            "fetched_at": stats.get("fetched_at"),
        }

        output_json(result)

    except StravaAuthError as e:
        output_error(str(e))
    except StravaAPIError as e:
        output_error(str(e))
    except Exception as e:
        output_error(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
