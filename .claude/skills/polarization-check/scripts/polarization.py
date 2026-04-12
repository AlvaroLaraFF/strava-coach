#!/usr/bin/env python3
"""80/20 polarization check from HR zones (Seiler model)."""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import classify_polarization
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range, load_streams
from strava.snapshot import ensure_snapshot


def _enrich_with_stream_zones(activities: list[dict], db: str,
                               easy_hr: float, hard_hr: float) -> list[dict]:
    """Try to add per-second time-in-zone data from HR streams."""
    for a in activities:
        sid = a.get("strava_id")
        if not sid:
            continue
        streams = load_streams(db, sid)
        if not streams or "heartrate" not in streams:
            continue
        hr_data = streams["heartrate"]
        if isinstance(hr_data, dict):
            hr_data = hr_data.get("data", [])
        if not hr_data or not isinstance(hr_data, list):
            continue
        easy_s = mod_s = hard_s = 0
        for hr in hr_data:
            if not hr:
                continue
            if hr < easy_hr:
                easy_s += 1
            elif hr < hard_hr:
                mod_s += 1
            else:
                hard_s += 1
        if easy_s + mod_s + hard_s > 0:
            a["time_in_zones_s"] = [float(easy_s), float(mod_s), float(hard_s)]
    return activities


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--hr-max", type=float, default=None)
    p.add_argument("--hr-rest", type=float, default=None)
    args = p.parse_args()

    try:
        db = get_default_db_path()

        snap = ensure_snapshot(db, required_fields=["hr_max_bpm", "hr_rest_bpm"])
        hr_max = args.hr_max or snap.get("hr_max_bpm") or 190.0
        hr_rest = args.hr_rest or snap.get("hr_rest_bpm") or 55.0

        # VT1/VT2 proxies via Karvonen (HRreserve) — Seiler model
        hr_reserve = hr_max - hr_rest
        easy_threshold = hr_rest + 0.75 * hr_reserve   # VT1 proxy
        hard_threshold = hr_rest + 0.88 * hr_reserve   # VT2 proxy
        activities = list(get_activities_range(db, days=args.days))
        if not activities:
            output_error("No activities found.")

        # Enrich with per-second HR stream data when available
        activities = _enrich_with_stream_zones(activities, db, easy_threshold, hard_threshold)

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
            "thresholds_bpm": {
                "easy_below": round(easy_threshold),
                "hard_above": round(hard_threshold),
                "hr_rest_used": hr_rest,
                "method": "karvonen_hrreserve",
            },
            "distribution": result,
            "window_days": args.days,
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
