#!/usr/bin/env python3
"""FTP estimator combining MMP-20 and weighted_average_watts percentile."""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import mean_max_curve
from strava.client import StravaClient, get_default_db_path, output_error, output_json
from strava.db import get_activities_range
from strava.sync import ensure_streams


RIDE_TYPES = {"Ride", "VirtualRide", "GravelRide", "MountainBikeRide", "EBikeRide"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=90)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        client = StravaClient(db)
        rides = [a for a in get_activities_range(db, days=args.days)
                 if a.get("sport_type") in RIDE_TYPES
                 and (a.get("moving_time") or 0) >= 40 * 60]
        if not rides:
            output_error("No rides ≥40min in window.")

        # Method A: 20-min from MMP curve
        best_20 = 0.0
        attribution_a = ""
        for r in rides[:25]:
            try:
                streams = ensure_streams(client, db, r["strava_id"])
            except Exception:
                continue
            watts = (streams.get("watts") or {}).get("data", [])
            if not watts:
                continue
            curve = mean_max_curve(watts, [1200])
            v = curve.get(1200, 0)
            if v > best_20:
                best_20 = v
                attribution_a = (r.get("start_date") or "")[:10] + " " + (r.get("name") or "")
        method_a = round(best_20 * 0.95, 0) if best_20 else 0

        # Method B: 95th percentile of weighted_average_watts
        nps = []
        for r in rides:
            try:
                payload = json.loads(r.get("raw_json") or "{}")
            except ValueError:
                continue
            wap = payload.get("weighted_average_watts")
            if wap:
                nps.append(wap)
        if nps:
            nps.sort()
            idx = int(len(nps) * 0.95)
            method_b = round(nps[min(idx, len(nps) - 1)], 0)
        else:
            method_b = 0

        chosen = max(method_a, method_b)
        warning = None
        if method_a and method_b and abs(method_a - method_b) > 15:
            warning = f"Methods disagree by {abs(method_a - method_b):.0f}W — verify with a real test."

        output_json({
            "ftp_estimate": chosen,
            "method_a_20min_x_095": method_a,
            "method_a_attribution": attribution_a,
            "method_b_wap_p95": method_b,
            "warning": warning,
            "rides_analyzed": len(rides),
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
