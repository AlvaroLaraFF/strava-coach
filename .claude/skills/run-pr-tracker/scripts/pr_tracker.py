#!/usr/bin/env python3
"""Personal records over standard run distances with stale-PR detection."""

import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import fmt_duration, fmt_pace, parse_iso, pace_min_per_km
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_best_efforts_pr, load_token
from strava.sync import backfill_best_efforts


def main() -> None:
    try:
        db = get_default_db_path()
        token = load_token(db)
        if not token:
            output_error("No token. Run strava-setup.")

        backfill_best_efforts(db)
        prs = get_best_efforts_pr(db, token["athlete_id"])
        if not prs:
            output_error("No best efforts in stored runs. Sync first.")

        now = datetime.now(timezone.utc)
        out = []
        for pr in prs:
            pace = pace_min_per_km(pr["distance"], pr["pr_time"])
            age_days = (now - parse_iso(pr["start_date"])).days if pr["start_date"] else None
            out.append({
                "distance_name": pr["effort_name"],
                "distance_m": round(pr["distance"], 0),
                "time": fmt_duration(pr["pr_time"]),
                "pace_min_km": fmt_pace(pace) if pace else "-",
                "date": (pr["start_date"] or "")[:10],
                "age_days": age_days,
                "stale": (age_days or 0) > 180,
            })

        stale_count = sum(1 for r in out if r["stale"])
        output_json({"prs": out, "stale_count": stale_count})
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
