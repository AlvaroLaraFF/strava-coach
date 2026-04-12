#!/usr/bin/env python3
"""Read the latest athlete snapshot from the local database."""

import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_latest_snapshot, init_db, load_token


def main() -> None:
    db = get_default_db_path()
    init_db(db)

    token = load_token(db)
    if not token:
        output_error("No token found. Run strava-setup first.")
    athlete_id = token["athlete_id"]

    snap = get_latest_snapshot(db, athlete_id)
    if not snap:
        output_json({"snapshot": None, "message": "No snapshot yet. Run athlete-snapshot to create one."})
        return

    captured = snap.get("captured_at", "")
    age_hours = None
    if captured:
        try:
            dt = datetime.fromisoformat(captured).replace(tzinfo=timezone.utc)
            age_hours = round((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 1)
        except (ValueError, TypeError):
            pass

    output_json({
        "snapshot": {k: snap[k] for k in snap if k not in ("id", "athlete_id")},
        "captured_at": captured,
        "source": snap.get("source"),
        "age_hours": age_hours,
    })


if __name__ == "__main__":
    main()
