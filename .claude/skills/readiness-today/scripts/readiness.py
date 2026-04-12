#!/usr/bin/env python3
"""Compute today's training readiness verdict."""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import (
    acute_chronic_ratio,
    banister_trimp,
    normalized_power,
    parse_iso,
    pmc_series,
    tss,
)
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range, load_streams, load_user_profile
from strava.snapshot import ensure_snapshot


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--ftp", type=float, default=None)
    p.add_argument("--hr-max", type=float, default=None)
    p.add_argument("--hr-rest", type=float, default=None)
    p.add_argument("--gender", type=str, default=None, help="M or F (loaded from profile if not set)")
    args = p.parse_args()

    try:
        db = get_default_db_path()

        snap = ensure_snapshot(db, required_fields=["hr_max_bpm", "hr_rest_bpm"])
        ftp = args.ftp or snap.get("ftp_w") or 200.0
        hr_max = args.hr_max or snap.get("hr_max_bpm") or 190.0
        hr_rest = args.hr_rest or snap.get("hr_rest_bpm") or 55.0

        profile = load_user_profile(db)
        sex = args.gender or (profile.get("gender") if profile else None) or "M"

        activities = get_activities_range(db, days=args.days)
        if not activities:
            output_error("No activities found. Sync first.")

        per_day: dict[str, float] = defaultdict(float)
        for a in activities:
            sd = a.get("start_date")
            if not sd:
                continue
            day = parse_iso(sd).strftime("%Y-%m-%d")
            duration_s = a.get("moving_time") or 0
            avg_w = a.get("average_watts") or 0
            if avg_w and ftp and duration_s:
                np_val = avg_w
                streams = load_streams(db, a.get("strava_id"))
                if streams and "watts" in streams:
                    watts_data = streams["watts"]
                    if isinstance(watts_data, dict):
                        watts_data = watts_data.get("data", [])
                    np_calc = normalized_power(watts_data)
                    if np_calc > 0:
                        np_val = np_calc
                i_f = np_val / ftp
                per_day[day] += tss(duration_s, np_val, i_f, ftp)
                continue
            avg_hr = a.get("average_hr") or 0
            if avg_hr and duration_s:
                per_day[day] += banister_trimp(duration_s / 60, avg_hr, hr_rest, hr_max, sex)

        sorted_days = sorted(per_day.items())
        first = sorted_days[0][0] if sorted_days else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        d = datetime.strptime(first, "%Y-%m-%d")
        end_d = datetime.strptime(end, "%Y-%m-%d")
        full = []
        while d <= end_d:
            key = d.strftime("%Y-%m-%d")
            full.append((key, per_day.get(key, 0.0)))
            d += timedelta(days=1)

        series = pmc_series(full)
        today = series[-1] if series else {"ctl": 0, "atl": 0, "tsb": 0}
        loads_only = [r["load"] for r in series]
        acwr = acute_chronic_ratio(loads_only)

        last_48h_load = sum(per_day.get((datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d"), 0.0) for i in range(2))

        tsb = today["tsb"]
        if tsb < -10 or acwr > 1.5:
            verdict = "REST"
            why = "Acute load is spiking (ACWR>1.5) or form is deeply negative."
        elif tsb < 0 or acwr > 1.3:
            verdict = "EASY"
            why = "Cumulative fatigue is high — recovery / Z2 only."
        elif tsb > 10 and acwr < 1.3:
            verdict = "GO HARD"
            why = "Form is positive and acute load is sustainable — intensity OK."
        else:
            verdict = "MODERATE"
            why = "Steady state — keep planned training, no extras."

        output_json({
            "verdict": verdict,
            "why": why,
            "ctl": today["ctl"],
            "atl": today["atl"],
            "tsb": tsb,
            "acwr": acwr,
            "last_48h_load": round(last_48h_load, 1),
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
