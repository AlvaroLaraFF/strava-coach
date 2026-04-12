#!/usr/bin/env python3
"""Cumulative distance per gear with retirement alerts."""

import json
import os
import sys
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.client import StravaClient, get_default_db_path, output_error, output_json
from strava.db import get_all_activities


def main() -> None:
    try:
        db = get_default_db_path()
        activities = get_all_activities(db)
        if not activities:
            output_error("No activities in DB.")

        per_gear: dict[str, dict] = defaultdict(lambda: {"distance_m": 0.0, "count": 0, "sport": None})
        for a in activities:
            raw = a.get("raw_json")
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            gear_id = payload.get("gear_id")
            if not gear_id:
                continue
            per_gear[gear_id]["distance_m"] += payload.get("distance", 0) or 0
            per_gear[gear_id]["count"] += 1
            per_gear[gear_id]["sport"] = a.get("sport_type")

        if not per_gear:
            output_json({"gear": [], "note": "No gear_id linked in activities."})
            return

        client = StravaClient(db)
        rows = []
        for gid, data in per_gear.items():
            try:
                gear = client.get_gear(gid)
                name = f"{gear.get('brand_name', '')} {gear.get('model_name', '') or gear.get('name', '')}".strip()
                official_distance = gear.get("distance", 0) or 0
            except Exception:
                name = gid
                official_distance = 0

            km = round(data["distance_m"] / 1000, 1)
            is_shoe = gid.startswith("g")
            status = "OK"
            if is_shoe:
                if km > 1000:
                    status = "RETIRE NOW"
                elif km > 700:
                    status = "REPLACE SOON"
            rows.append({
                "gear_id": gid,
                "name": name,
                "type": "shoes" if is_shoe else "bike",
                "sport": data["sport"],
                "activities": data["count"],
                "distance_km": km,
                "official_lifetime_km": round(official_distance / 1000, 1),
                "status": status,
            })

        rows.sort(key=lambda r: r["distance_km"], reverse=True)
        output_json({"gear": rows})
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
