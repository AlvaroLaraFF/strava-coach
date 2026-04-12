#!/usr/bin/env python3
"""80/20 polarization check from HR zones."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import classify_polarization
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--hr-max", type=float, default=190.0)
    args = p.parse_args()

    try:
        easy_threshold = args.hr_max * 0.78
        hard_threshold = args.hr_max * 0.88

        db = get_default_db_path()
        activities = get_activities_range(db, days=args.days)
        if not activities:
            output_error("No activities found.")

        result = classify_polarization(activities, easy_threshold, hard_threshold)

        easy = result["easy_pct"]
        mod = result["moderate_pct"]
        hard = result["hard_pct"]

        if easy >= 75 and mod <= 15:
            verdict = "POLARIZED"
            advice = "Distribution matches the 80/20 model — keep it."
        elif easy >= 60 and mod >= hard:
            verdict = "PYRAMIDAL"
            advice = "Reduce moderate-intensity time and convert it to easy."
        elif mod > easy:
            verdict = "THRESHOLD-HEAVY"
            advice = "Too much grey-zone training. Slow down easy sessions."
        else:
            verdict = "UNDEFINED"
            advice = "Mixed pattern. Aim for ~80% easy, ≤15% moderate, ~5-10% hard."

        output_json({
            "verdict": verdict,
            "advice": advice,
            "thresholds_bpm": {"easy_below": round(easy_threshold), "hard_above": round(hard_threshold)},
            "distribution": result,
            "window_days": args.days,
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
