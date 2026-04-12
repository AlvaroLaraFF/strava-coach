#!/usr/bin/env python3
"""Recompute ALL variable physiological metrics and write a full snapshot.

Thin CLI wrapper around ``strava.snapshot.compute_full_snapshot()``.
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_latest_snapshot, init_db, load_token, upsert_athlete_snapshot
from strava.snapshot import compute_full_snapshot

# Import alert generation from update_snapshot (same directory)
from update_snapshot import generate_alerts


def main() -> None:
    p = argparse.ArgumentParser(description="Full refresh of athlete snapshot")
    p.add_argument("--days", type=int, default=90, help="Window for activity analysis")
    args = p.parse_args()

    db = get_default_db_path()
    init_db(db)

    token = load_token(db)
    if not token:
        output_error("No token found. Run strava-setup first.")
    athlete_id = token["athlete_id"]

    previous = get_latest_snapshot(db, athlete_id)

    metrics = compute_full_snapshot(db, days=args.days)
    if not metrics:
        output_error("No activities found. Run strava-sync first.")

    alerts = generate_alerts(previous, metrics)
    row_id = upsert_athlete_snapshot(db, athlete_id, "full-refresh", metrics)
    snapshot = get_latest_snapshot(db, athlete_id)

    output_json({
        "snapshot": {k: snapshot[k] for k in snapshot if k not in ("id", "athlete_id")},
        "alerts": alerts,
        "previous_captured_at": previous.get("captured_at") if previous else None,
        "row_id": row_id,
    })


if __name__ == "__main__":
    main()
