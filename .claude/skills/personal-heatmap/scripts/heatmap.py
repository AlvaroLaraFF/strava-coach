#!/usr/bin/env python3
"""Render a personal heatmap from activity polylines into a standalone HTML file."""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Google encoded polyline → list of (lat, lng)."""
    if not encoded:
        return []
    coords = []
    index = lat = lng = 0
    while index < len(encoded):
        for unit in ("lat", "lng"):
            shift = result = 0
            while True:
                if index >= len(encoded):
                    return coords
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if unit == "lat":
                lat += delta
            else:
                lng += delta
        coords.append((lat / 1e5, lng / 1e5))
    return coords


HTML_TEMPLATE = """<!doctype html>
<html><head>
<meta charset="utf-8">
<title>Strava heatmap</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>html,body,#map{height:100%;margin:0}</style>
</head><body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<script>
const points = __POINTS__;
const map = L.map('map').setView([__CLAT__, __CLNG__], 11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {attribution: '© OSM'}).addTo(map);
L.heatLayer(points, {radius: 4, blur: 6, minOpacity: 0.4}).addTo(map);
if (points.length) {
  const bounds = L.latLngBounds(points.map(p => [p[0], p[1]]));
  map.fitBounds(bounds);
}
</script></body></html>"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default=os.path.expanduser("~/strava_heatmap.html"))
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--sport", default=None)
    args = p.parse_args()

    try:
        db = get_default_db_path()
        activities = get_activities_range(db, days=args.days)
        if args.sport:
            activities = [a for a in activities if a.get("sport_type") == args.sport]
        if not activities:
            output_error("No activities in window.")

        all_points: list[list[float]] = []
        for a in activities:
            try:
                payload = json.loads(a.get("raw_json") or "{}")
            except ValueError:
                continue
            poly = (payload.get("map") or {}).get("summary_polyline")
            for lat, lng in decode_polyline(poly):
                all_points.append([lat, lng, 0.5])

        if not all_points:
            output_error("No GPS data in selected activities.")

        avg_lat = sum(p[0] for p in all_points) / len(all_points)
        avg_lng = sum(p[1] for p in all_points) / len(all_points)
        html = (HTML_TEMPLATE
                .replace("__POINTS__", json.dumps(all_points))
                .replace("__CLAT__", str(avg_lat))
                .replace("__CLNG__", str(avg_lng)))

        out_path = os.path.abspath(args.output)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(html)

        output_json({
            "html_path": out_path,
            "activities_used": len(activities),
            "points_plotted": len(all_points),
            "center": [avg_lat, avg_lng],
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
