#!/usr/bin/env python3
"""Run pace zones (Daniels-style) and current distribution."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import fmt_pace, pace_min_per_km, vdot_from_5k, vdot_to_threshold_pace
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range, get_best_efforts_pr, load_token
from strava.snapshot import ensure_snapshot


RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def parse_pace(s: str) -> float:
    m, sec = s.split(":")
    return int(m) + int(sec) / 60.0


def _detect_threshold_from_best_efforts(db: str, hr_max: float, days: int) -> float | None:
    """Try to detect threshold pace from best efforts or HR data.

    Priority:
    1. 5K best effort -> VDOT -> T-pace (most reliable)
    2. Activity with avg HR at 85-90% HRmax and >=20min (HR-based proxy)
    """
    token = load_token(db)
    if token:
        prs = get_best_efforts_pr(db, token["athlete_id"])
        five_k = next((p for p in prs if p["effort_name"] in ("5K", "5k")), None)
        if five_k and five_k["pr_time"]:
            vdot = vdot_from_5k(five_k["pr_time"])
            if vdot > 0:
                tp = vdot_to_threshold_pace(vdot)
                if tp > 0:
                    return tp

    # Fallback: find a tempo-effort run (avg HR 85-90% HRmax, >=20 min)
    activities = [a for a in get_activities_range(db, days=max(days, 180))
                  if a.get("sport_type") in RUN_TYPES]
    hr_low = hr_max * 0.85
    hr_high = hr_max * 0.90
    tempo_runs = [
        a for a in activities
        if (a.get("average_hr") or 0) >= hr_low
        and (a.get("average_hr") or 0) <= hr_high
        and (a.get("moving_time") or 0) >= 1200  # >=20 min
    ]
    if tempo_runs:
        best = min(tempo_runs, key=lambda a: pace_min_per_km(
            a.get("distance") or 0, a.get("moving_time") or 0) or 999)
        tp = pace_min_per_km(best.get("distance") or 0, best.get("moving_time") or 0)
        if tp:
            return tp

    return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--threshold-pace", type=str, default=None,
                   help="threshold pace as M:SS per km")
    p.add_argument("--hr-max", type=float, default=None,
                   help="max heart rate (used for HR-based threshold fallback)")
    args = p.parse_args()

    try:
        db = get_default_db_path()

        snap = ensure_snapshot(db, required_fields=["hr_max_bpm", "threshold_pace_min_km"])
        hr_max = args.hr_max or snap.get("hr_max_bpm") or 190.0

        activities = [a for a in get_activities_range(db, days=args.days)
                      if a.get("sport_type") in RUN_TYPES]
        if not activities:
            output_error("No recent runs found.")

        if args.threshold_pace:
            threshold = parse_pace(args.threshold_pace)
        elif snap.get("threshold_pace_min_km"):
            threshold = snap["threshold_pace_min_km"]
        else:
            threshold = _detect_threshold_from_best_efforts(db, hr_max, args.days)
            if not threshold:
                output_error(
                    "Could not auto-detect threshold pace. "
                    "No 5K best effort found and no tempo run (85-90% HRmax, >=20min) available. "
                    "Use --threshold-pace M:SS to set manually.")

        zones = {
            "Z1_recovery": {"low": threshold * 1.30, "high": None},
            "Z2_easy":     {"low": threshold * 1.15, "high": threshold * 1.30},
            "Z3_marathon": {"low": threshold * 1.05, "high": threshold * 1.15},
            "Z4_threshold":{"low": threshold * 0.97, "high": threshold * 1.05},
            "Z5_vo2max":   {"low": None,             "high": threshold * 0.97},
        }

        for z in zones.values():
            z["low_str"] = fmt_pace(z["low"]) if z["low"] else "-"
            z["high_str"] = fmt_pace(z["high"]) if z["high"] else "-"

        distribution = {k: 0 for k in zones}
        for a in activities:
            pace = pace_min_per_km(a.get("distance") or 0, a.get("moving_time") or 0)
            if not pace:
                continue
            placed = False
            if pace >= (zones["Z1_recovery"]["low"] or 0):
                distribution["Z1_recovery"] += 1
                placed = True
            elif zones["Z5_vo2max"]["high"] and pace <= zones["Z5_vo2max"]["high"]:
                distribution["Z5_vo2max"] += 1
                placed = True
            if not placed:
                for name, z in zones.items():
                    low = z["low"] or 0
                    high = z["high"] or float("inf")
                    if high >= pace >= low:
                        distribution[name] += 1
                        break

        easy_count = distribution["Z1_recovery"] + distribution["Z2_easy"]
        total = sum(distribution.values())
        easy_pct = round(easy_count / total * 100, 1) if total else 0

        if easy_pct >= 75:
            verdict = "GOOD: enough easy running"
        elif easy_pct >= 60:
            verdict = "OK but could be more easy"
        else:
            verdict = "TOO MUCH HARD RUNNING — slow down easy days"

        output_json({
            "threshold_pace": fmt_pace(threshold),
            "zones": zones,
            "recent_distribution": distribution,
            "easy_pct": easy_pct,
            "verdict": verdict,
            "runs_analyzed": len(activities),
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
