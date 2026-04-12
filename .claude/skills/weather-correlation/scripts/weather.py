#!/usr/bin/env python3
"""Weather vs pace correlation using Open-Meteo Archive API (free, no key)."""

import argparse
import json
import os
import sys

import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import fmt_pace, pace_min_per_km, parse_iso
from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_activities_range


OPEN_METEO = "https://archive-api.open-meteo.com/v1/era5"


def fetch_temp(lat: float, lng: float, when_iso: str) -> float | None:
    dt = parse_iso(when_iso)
    day = dt.strftime("%Y-%m-%d")
    try:
        r = requests.get(
            OPEN_METEO,
            params={
                "latitude": lat,
                "longitude": lng,
                "start_date": day,
                "end_date": day,
                "hourly": "temperature_2m",
                "timezone": "UTC",
            },
            timeout=15,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        temps = (data.get("hourly") or {}).get("temperature_2m") or []
        times = (data.get("hourly") or {}).get("time") or []
        target_hour = dt.strftime("%Y-%m-%dT%H:00")
        for t, v in zip(times, temps):
            if t == target_hour:
                return v
        return temps[dt.hour] if temps else None
    except Exception:
        return None


def correlation(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx * vy) ** 0.5


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--sport", default="Run")
    args = p.parse_args()

    try:
        db = get_default_db_path()
        activities = [a for a in get_activities_range(db, days=args.days)
                      if a.get("sport_type") == args.sport]
        if not activities:
            output_error(f"No {args.sport} activities in window.")

        rows = []
        temps: list[float] = []
        paces: list[float] = []
        for a in activities[:30]:
            try:
                payload = json.loads(a.get("raw_json") or "{}")
            except ValueError:
                continue
            sl = payload.get("start_latlng") or []
            if len(sl) != 2:
                continue
            temp = fetch_temp(sl[0], sl[1], a["start_date"])
            if temp is None:
                continue
            pace = pace_min_per_km(a.get("distance") or 0, a.get("moving_time") or 0)
            if not pace:
                continue
            rows.append({
                "date": (a.get("start_date") or "")[:10],
                "name": a.get("name"),
                "temp_c": round(temp, 1),
                "pace": fmt_pace(pace),
                "avg_hr": round(a.get("average_hr") or 0, 0),
            })
            temps.append(temp)
            paces.append(pace)

        if not rows:
            output_error("Could not fetch weather for any activity.")

        corr = round(correlation(temps, paces), 3)
        if abs(corr) >= 0.5:
            relation = "STRONG"
        elif abs(corr) >= 0.3:
            relation = "MODERATE"
        else:
            relation = "WEAK"
        direction = "slower" if corr > 0 else "faster"

        output_json({
            "activities": rows,
            "correlation": corr,
            "relation": relation,
            "interpretation": f"{relation} positive correlation: hotter = {direction}" if corr else "no data",
            "samples": len(rows),
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
