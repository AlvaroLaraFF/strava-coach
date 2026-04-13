#!/usr/bin/env python3
"""Group activities by route similarity and show pace progression."""

import argparse
import json
import math
import os
import sys
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import fmt_pace, pace_min_per_km, parse_iso
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range


def _decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode a Google encoded polyline string into a list of (lat, lng) tuples."""
    coords = []
    index = 0
    lat = 0
    lng = 0
    while index < len(encoded):
        # Decode latitude
        result = 0
        shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if result & 1 else result >> 1
        lat += dlat

        # Decode longitude
        result = 0
        shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if result & 1 else result >> 1
        lng += dlng

        coords.append((lat / 1e5, lng / 1e5))
    return coords


def _hausdorff(poly_a: list[tuple[float, float]], poly_b: list[tuple[float, float]], step: int = 5) -> float:
    """Compute simplified symmetric Hausdorff distance (metres) between two polylines.

    Subsamples every `step` points for performance. Uses equirectangular
    distance approximation (not haversine) — accurate enough for route matching.
    """
    def _dist_m(p1: tuple[float, float], p2: tuple[float, float]) -> float:
        lat1, lng1 = p1
        lat2, lng2 = p2
        lat_m = math.radians(lat2 - lat1) * 6_371_000
        lng_m = math.radians(lng2 - lng1) * 6_371_000 * math.cos(math.radians((lat1 + lat2) / 2))
        return math.sqrt(lat_m ** 2 + lng_m ** 2)

    sub_a = poly_a[::step] or poly_a
    sub_b = poly_b[::step] or poly_b

    def _directed(src: list, tgt: list) -> float:
        max_min = 0.0
        for p in src:
            min_d = min(_dist_m(p, q) for q in tgt)
            if min_d > max_min:
                max_min = min_d
        return max_min

    return max(_directed(sub_a, sub_b), _directed(sub_b, sub_a))


def signature(payload: dict, distance_m: float) -> tuple | None:
    """Fallback signature when no polyline is available."""
    sl = payload.get("start_latlng") or []
    el = payload.get("end_latlng") or []
    if len(sl) != 2 or len(el) != 2:
        return None
    # Round coordinates to ~100m, distance to nearest 200m
    return (
        round(sl[0], 3),
        round(sl[1], 3),
        round(el[0], 3),
        round(el[1], 3),
        round(distance_m / 200) * 200,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--sport", default="Run")
    p.add_argument("--min-occurrences", type=int, default=3)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        activities = [a for a in get_activities_range(db, days=args.days)
                      if a.get("sport_type") == args.sport]
        if not activities:
            output_error(f"No {args.sport} activities in window.")

        # Build per-activity records with polyline + pace
        records = []
        for a in activities:
            try:
                payload = json.loads(a.get("raw_json") or "{}")
            except ValueError:
                payload = {}
            pace = pace_min_per_km(a.get("distance") or 0, a.get("moving_time") or 0)
            if not pace:
                continue
            encoded = (payload.get("map") or {}).get("summary_polyline") or payload.get("summary_polyline")
            records.append({
                "activity": a,
                "payload": payload,
                "pace": pace,
                "polyline": encoded,
            })

        # Group by polyline similarity when available, fallback to signature
        poly_groups: list[list[dict]] = []   # list of groups; each group is a list of records
        fallback_groups: dict[tuple, list[dict]] = defaultdict(list)

        poly_records = [r for r in records if r["polyline"]]
        no_poly_records = [r for r in records if not r["polyline"]]

        # Decode polylines once
        decoded: dict[int, list[tuple[float, float]]] = {}
        for r in poly_records:
            aid = r["activity"]["strava_id"]
            try:
                decoded[aid] = _decode_polyline(r["polyline"])
            except Exception:
                # If decoding fails, treat as no polyline
                no_poly_records.append(r)

        valid_poly = [r for r in poly_records if r["activity"]["strava_id"] in decoded]

        # Assign each activity to a group (greedy: compare against first member of each group)
        HAUSDORFF_THRESHOLD = 200  # metres
        for r in valid_poly:
            aid = r["activity"]["strava_id"]
            poly = decoded[aid]
            matched = False
            for group in poly_groups:
                rep_id = group[0]["activity"]["strava_id"]
                rep_poly = decoded.get(rep_id)
                if rep_poly and _hausdorff(poly, rep_poly) < HAUSDORFF_THRESHOLD:
                    group.append(r)
                    matched = True
                    break
            if not matched:
                poly_groups.append([r])

        # Fallback: distance+start/end coordinate bucket
        for r in no_poly_records:
            sig = signature(r["payload"], r["activity"].get("distance") or 0)
            if sig:
                fallback_groups[sig].append(r)

        # Merge poly_groups and fallback_groups into a unified result
        all_groups: list[list[dict]] = [g for g in poly_groups] + list(fallback_groups.values())

        result = []
        for group_records in all_groups:
            if len(group_records) < args.min_occurrences:
                continue
            runs = []
            for r in group_records:
                a = r["activity"]
                runs.append({
                    "date": (a.get("start_date") or "")[:10],
                    "pace": r["pace"],
                    "pace_str": fmt_pace(r["pace"]),
                    "name": a.get("name"),
                })
            runs.sort(key=lambda x: x["date"])
            first = runs[0]
            last = runs[-1]
            d1 = parse_iso(first["date"]).timestamp()
            d2 = parse_iso(last["date"]).timestamp()
            months = max((d2 - d1) / (86400 * 30), 0.5)
            slope_s_per_km_per_month = round((last["pace"] - first["pace"]) * 60 / months, 1)
            improvement_direction = "FASTER" if slope_s_per_km_per_month < -2 else (
                "SLOWER" if slope_s_per_km_per_month > 2 else "STABLE"
            )

            # Build a signature summary for output
            rep = group_records[0]
            rep_payload = rep["payload"]
            sl = rep_payload.get("start_latlng") or []
            el = rep_payload.get("end_latlng") or []
            sig_out = {
                "start_lat": sl[0] if len(sl) == 2 else None,
                "start_lng": sl[1] if len(sl) == 2 else None,
                "end_lat": el[0] if len(el) == 2 else None,
                "end_lng": el[1] if len(el) == 2 else None,
                "distance_m": round(rep["activity"].get("distance") or 0, 0),
                "matched_by": "polyline" if rep["polyline"] else "coordinates",
            }

            result.append({
                "signature": sig_out,
                "occurrences": len(runs),
                "first": first["date"],
                "last": last["date"],
                "first_pace": first["pace_str"],
                "last_pace": last["pace_str"],
                "trend_s_per_km_per_month": slope_s_per_km_per_month,
                "trend": improvement_direction,
                "runs": runs,
            })

        result.sort(key=lambda r: r["occurrences"], reverse=True)
        output_json({"groups": result, "total_groups": len(result)})
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
