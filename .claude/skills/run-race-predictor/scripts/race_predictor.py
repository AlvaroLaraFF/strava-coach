#!/usr/bin/env python3
"""Race time predictor (Riegel + VDOT) from best_efforts."""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import fmt_duration, parse_iso, riegel_predict, vdot_from_5k
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_best_efforts_pr, load_token
from strava.sync import backfill_best_efforts


TARGETS = {
    "5k": 5000,
    "10k": 10000,
    "half_marathon": 21097,
    "marathon": 42195,
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--recent-days", type=int, default=60)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        token = load_token(db)
        if not token:
            output_error("No token. Run strava-setup first.")

        backfill_best_efforts(db)
        prs = get_best_efforts_pr(db, token["athlete_id"])
        if not prs:
            output_error("No best_efforts found in stored activities. Sync runs first.")

        recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=args.recent_days))
        recent = [r for r in prs if r["start_date"] and parse_iso(r["start_date"]) >= recent_cutoff]
        pool = recent or prs

        preferred = [r for r in pool if r.get("effort_name", "").upper() in ("5K", "10K")]
        if preferred:
            anchor = min(preferred, key=lambda r: r["pr_time"] / r["distance"])
        else:
            anchor = min(pool, key=lambda r: r["pr_time"] / r["distance"])

        five_k = next((r for r in pool if (r["effort_name"] or "").lower() == "5k"), None)
        vdot = vdot_from_5k(five_k["pr_time"]) if five_k else None

        predictions = {}
        for label, dist_m in TARGETS.items():
            t = riegel_predict(anchor["pr_time"], anchor["distance"], dist_m)
            predictions[label] = {
                "seconds": round(t),
                "formatted": fmt_duration(t),
            }

        output_json({
            "anchor_effort": {
                "name": anchor["effort_name"],
                "distance_m": anchor["distance"],
                "time": fmt_duration(anchor["pr_time"]),
                "date": anchor["start_date"],
            },
            "vdot": vdot,
            "predictions_riegel": predictions,
            "anchor_pool_size": len(pool),
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
