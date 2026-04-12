#!/usr/bin/env python3
"""Three-level Strava sync orchestrator."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.client import StravaClient, get_default_db_path, output_error, output_json
from strava.db import init_db, load_token
from strava.sync import (
    backfill_best_efforts,
    sync_activity_details,
    sync_athlete_zones_now,
    sync_streams_bulk,
    sync_summary,
)


SPORT_GROUPS = {
    "Run": {"Run", "TrailRun", "VirtualRun"},
    "Ride": {"Ride", "VirtualRide", "GravelRide", "MountainBikeRide", "EBikeRide"},
    "Swim": {"Swim"},
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--level", choices=["summary", "details", "streams", "zones", "all"], default="summary")
    p.add_argument("--days", type=int, default=None, help="Only for summary level")
    p.add_argument("--limit", type=int, default=None, help="Only for details/streams")
    p.add_argument("--sport", default=None, help="Run, Ride, Swim — for streams level")
    p.add_argument("--full", action="store_true", help="Force full history sync (ignore incremental)")
    p.add_argument("--force", action="store_true", help="Re-fetch even if cached")
    args = p.parse_args()

    try:
        db = get_default_db_path()
        init_db(db)
        token = load_token(db)
        if not token:
            output_error("No token. Run strava-setup first.")
        athlete_id = token["athlete_id"]
        client = StravaClient(db)

        result = {"level": args.level}

        if args.level in ("summary", "all"):
            n = sync_summary(client, db, days=args.days, full=args.full)
            result["summary"] = {"upserted": n}

        if args.level in ("details", "all"):
            r = sync_activity_details(client, db, limit=args.limit, force=args.force)
            backfilled = backfill_best_efforts(db)
            r["best_efforts_total_in_db"] = backfilled
            result["details"] = r

        if args.level in ("streams", "all"):
            sport_set = SPORT_GROUPS.get(args.sport) if args.sport else None
            r = sync_streams_bulk(client, db, sport_types=sport_set, limit=args.limit)
            result["streams"] = r

        if args.level in ("zones", "all"):
            try:
                z = sync_athlete_zones_now(client, db, athlete_id)
                result["zones"] = {"saved": True, "has_hr": "heart_rate" in z, "has_power": "power" in z}
            except Exception as e:
                result["zones"] = {"saved": False, "error": str(e)[:200]}

        output_json(result)
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
