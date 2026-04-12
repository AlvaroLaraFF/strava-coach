#!/usr/bin/env python3
"""Running cadence + stride length trend."""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import parse_iso
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range


RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=90)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        runs = [a for a in get_activities_range(db, days=args.days)
                if a.get("sport_type") in RUN_TYPES]
        if not runs:
            output_error("No runs in window.")

        by_month: dict[str, list[float]] = defaultdict(list)
        cadences: list[float] = []
        strides: list[float] = []
        for r in runs:
            try:
                payload = json.loads(r.get("raw_json") or "{}")
            except ValueError:
                continue
            cad = payload.get("average_cadence")
            if cad is None:
                continue
            spm = cad * 2
            cadences.append(spm)
            month = parse_iso(r["start_date"]).strftime("%Y-%m")
            by_month[month].append(spm)

            distance = r.get("distance") or 0
            duration = r.get("moving_time") or 0
            if distance and duration and spm:
                steps = (spm / 60.0) * duration
                if steps:
                    strides.append(distance / steps)

        if not cadences:
            output_error("No cadence data in any of the runs.")

        avg = round(sum(cadences) / len(cadences), 1)
        avg_stride = round(sum(strides) / len(strides), 2) if strides else None

        months_sorted = sorted(by_month.items())
        first = months_sorted[0]
        last = months_sorted[-1]
        delta = round(sum(last[1]) / len(last[1]) - sum(first[1]) / len(first[1]), 1)

        if 170 <= avg <= 185:
            range_verdict = "OPTIMAL (170-185 spm)"
        elif avg < 170:
            range_verdict = "LOW (<170 spm) — try shorter, faster steps"
        else:
            range_verdict = "HIGH (>185 spm) — uncommon, check sensor"

        output_json({
            "average_cadence_spm": avg,
            "average_stride_length_m": avg_stride,
            "first_month": first[0],
            "last_month": last[0],
            "trend_delta_spm": delta,
            "range_verdict": range_verdict,
            "runs_analyzed": len(cadences),
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
