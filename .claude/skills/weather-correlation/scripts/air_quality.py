#!/usr/bin/env python3
"""Air quality / pollen vs performance correlation.

Pulls hourly pollen (grass, olive, birch, alder, mugwort, ragweed) plus
PM2.5, PM10, ozone, NO2 and ambient temperature from Open-Meteo (free,
no key) at each activity's start location and timestamp, caches results
locally, then runs a per-sport residual-HR regression against the
environmental signals.

The intent is to answer "does pollen / poor air make my HR drift higher
for the same effort?" — separately from heat — using clinical-grade
threshold buckets (CAMS Europe pollen scale, WHO PM2.5, WHO ozone).
"""

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import fmt_pace, pace_min_per_km, parse_iso  # noqa: E402
from strava.client import get_default_db_path, output_error, output_json  # noqa: E402
from strava.db import get_activities_range  # noqa: E402


AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/era5"

AIR_VARS = [
    "pm10", "pm2_5", "ozone", "nitrogen_dioxide", "sulphur_dioxide",
    "european_aqi",
    "alder_pollen", "birch_pollen", "grass_pollen",
    "mugwort_pollen", "olive_pollen", "ragweed_pollen",
]

# Clinical / regulatory thresholds.
# Pollen: CAMS Europe scale, grains/m^3.
# PM2.5: WHO 24h interim targets, μg/m^3.
# PM10:  WHO 24h interim targets, μg/m^3.
# Ozone: WHO 8h average / EU air quality bands, μg/m^3.
THRESHOLDS = {
    "grass_pollen":   [("low", 20), ("moderate", 50), ("high", 200), ("very_high", float("inf"))],
    "olive_pollen":   [("low", 10), ("moderate", 50), ("high", 200), ("very_high", float("inf"))],
    "birch_pollen":   [("low", 10), ("moderate", 50), ("high", 200), ("very_high", float("inf"))],
    "alder_pollen":   [("low", 10), ("moderate", 50), ("high", 200), ("very_high", float("inf"))],
    "mugwort_pollen": [("low", 10), ("moderate", 50), ("high", 200), ("very_high", float("inf"))],
    "ragweed_pollen": [("low", 10), ("moderate", 50), ("high", 200), ("very_high", float("inf"))],
    "pm2_5":          [("good", 15), ("moderate", 25), ("unhealthy", 50), ("very_unhealthy", float("inf"))],
    "pm10":           [("good", 45), ("moderate", 100), ("unhealthy", 150), ("very_unhealthy", float("inf"))],
    "ozone":          [("good", 100), ("moderate", 160), ("high", 240), ("very_high", float("inf"))],
}


# ---------------------------------------------------------------------------
# Cache table
# ---------------------------------------------------------------------------

def _ensure_cache(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS env_hourly (
                lat_grid       REAL    NOT NULL,
                lng_grid       REAL    NOT NULL,
                hour_utc       TEXT    NOT NULL,
                pm10           REAL,
                pm2_5          REAL,
                ozone          REAL,
                nitrogen_dioxide REAL,
                sulphur_dioxide  REAL,
                european_aqi   REAL,
                alder_pollen   REAL,
                birch_pollen   REAL,
                grass_pollen   REAL,
                mugwort_pollen REAL,
                olive_pollen   REAL,
                ragweed_pollen REAL,
                temp_c         REAL,
                fetched_at     TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (lat_grid, lng_grid, hour_utc)
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def _grid_key(lat: float, lng: float) -> tuple[float, float]:
    """Round to 2 decimals (~1.1 km cell). Pollen and PM are regional —
    a single cell stands in for everyone running in the same area."""
    return (round(lat, 2), round(lng, 2))


def _cache_load(
    db_path: str, lat_g: float, lng_g: float, start_iso: str, end_iso: str
) -> dict[str, dict]:
    """Return cached rows for the grid in [start_iso, end_iso] keyed by hour_utc."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT * FROM env_hourly
               WHERE lat_grid = ? AND lng_grid = ?
                 AND hour_utc BETWEEN ? AND ?""",
            (lat_g, lng_g, start_iso, end_iso),
        ).fetchall()
        return {r["hour_utc"]: dict(r) for r in rows}
    finally:
        conn.close()


def _cache_upsert(db_path: str, lat_g: float, lng_g: float, hourly: dict[str, dict]) -> None:
    if not hourly:
        return
    conn = sqlite3.connect(db_path)
    try:
        for hour_iso, values in hourly.items():
            conn.execute(
                """INSERT OR REPLACE INTO env_hourly
                   (lat_grid, lng_grid, hour_utc,
                    pm10, pm2_5, ozone, nitrogen_dioxide, sulphur_dioxide, european_aqi,
                    alder_pollen, birch_pollen, grass_pollen,
                    mugwort_pollen, olive_pollen, ragweed_pollen,
                    temp_c, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    lat_g, lng_g, hour_iso,
                    values.get("pm10"), values.get("pm2_5"), values.get("ozone"),
                    values.get("nitrogen_dioxide"), values.get("sulphur_dioxide"),
                    values.get("european_aqi"),
                    values.get("alder_pollen"), values.get("birch_pollen"),
                    values.get("grass_pollen"), values.get("mugwort_pollen"),
                    values.get("olive_pollen"), values.get("ragweed_pollen"),
                    values.get("temp_c"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Open-Meteo fetchers
# ---------------------------------------------------------------------------

def _fetch_air_quality(lat: float, lng: float, start_day: str, end_day: str) -> dict[str, dict]:
    """Hit the air-quality endpoint for [start_day, end_day]. Returns
    {hour_utc_iso: {var: value, ...}, ...}. Missing hours are skipped."""
    try:
        r = requests.get(
            AIR_QUALITY_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "start_date": start_day,
                "end_date": end_day,
                "hourly": ",".join(AIR_VARS),
                "timezone": "UTC",
            },
            timeout=30,
        )
    except requests.RequestException:
        return {}
    if r.status_code != 200:
        return {}
    data = r.json()
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    out: dict[str, dict] = {}
    for i, t in enumerate(times):
        row = {}
        for v in AIR_VARS:
            arr = hourly.get(v) or []
            row[v] = arr[i] if i < len(arr) else None
        out[t] = row
    return out


def _fetch_temperature(lat: float, lng: float, start_day: str, end_day: str) -> dict[str, float]:
    """Pull ambient temperature for the window from the ERA5 archive."""
    try:
        r = requests.get(
            ARCHIVE_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "start_date": start_day,
                "end_date": end_day,
                "hourly": "temperature_2m",
                "timezone": "UTC",
            },
            timeout=30,
        )
    except requests.RequestException:
        return {}
    if r.status_code != 200:
        return {}
    data = r.json()
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    return {t: temps[i] for i, t in enumerate(times) if i < len(temps) and temps[i] is not None}


def _activity_hour_iso(start_date: str) -> str:
    """Round the activity start to its UTC hour bucket — that's the cache key."""
    dt = parse_iso(start_date).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:00")


def _env_for_activities(
    db_path: str, activities: list[dict]
) -> dict[int, dict]:
    """Get environmental snapshot at activity start hour for each activity.
    Batches by grid cell to minimise API calls. Returns {strava_id: env_dict}."""
    # Group activity hours by grid cell.
    by_grid: dict[tuple[float, float], list[tuple[int, str]]] = defaultdict(list)
    for a in activities:
        try:
            payload = json.loads(a.get("raw_json") or "{}")
        except ValueError:
            continue
        sl = payload.get("start_latlng") or []
        if len(sl) != 2:
            continue
        hour = _activity_hour_iso(a["start_date"])
        by_grid[_grid_key(sl[0], sl[1])].append((a["strava_id"], hour))

    out: dict[int, dict] = {}
    for (lat_g, lng_g), entries in by_grid.items():
        hours = sorted({h for _, h in entries})
        if not hours:
            continue
        start_day = hours[0][:10]
        end_day = hours[-1][:10]

        cached = _cache_load(db_path, lat_g, lng_g, hours[0], hours[-1])
        missing = [h for h in hours if h not in cached]

        if missing:
            air = _fetch_air_quality(lat_g, lng_g, start_day, end_day)
            time.sleep(0.4)  # be polite to Open-Meteo
            temp = _fetch_temperature(lat_g, lng_g, start_day, end_day)
            merged: dict[str, dict] = {}
            keys = set(air) | set(temp)
            for k in keys:
                row = dict(air.get(k) or {})
                if k in temp:
                    row["temp_c"] = temp[k]
                merged[k] = row
            _cache_upsert(db_path, lat_g, lng_g, merged)
            cached.update(merged)

        for sid, hour in entries:
            if hour in cached:
                row = cached[hour]
                # Strip cache-only keys.
                out[sid] = {k: row.get(k) for k in (*AIR_VARS, "temp_c")}
    return out


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def _linreg(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """Ordinary least squares y = a + b·x. Returns (a, b) or None if degenerate."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return None
    b = sxy / sxx
    a = my - b * mx
    return a, b


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _bucket(value: float | None, var: str) -> str | None:
    if value is None:
        return None
    for label, ceiling in THRESHOLDS.get(var, []):
        if value < ceiling:
            return label
    return None


def _strength(r: float) -> str:
    a = abs(r)
    if a >= 0.5:
        return "STRONG"
    if a >= 0.3:
        return "MODERATE"
    if a >= 0.15:
        return "WEAK"
    return "NONE"


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def _effort_metric(act: dict) -> float | None:
    """Pace in min/km for foot sports, otherwise inverse speed (sec/m)."""
    dist = act.get("distance") or 0
    mt = act.get("moving_time") or 0
    return pace_min_per_km(dist, mt)


def analyse(days: int) -> dict:
    db = get_default_db_path()
    _ensure_cache(db)

    activities = get_activities_range(db, days=days)
    # Need HR + distance + moving_time to do anything useful.
    usable = [
        a for a in activities
        if a.get("average_hr") and a.get("distance") and a.get("moving_time")
    ]
    if not usable:
        output_error("No activities with HR + distance + duration in window.")

    env_by_id = _env_for_activities(db, usable)
    if not env_by_id:
        output_error(
            "No activity had usable GPS start coordinates. Sync details first."
        )

    # Build per-activity rows + per-sport HR residual via OLS HR ~ pace.
    by_sport: dict[str, list[dict]] = defaultdict(list)
    rows: list[dict] = []
    for a in usable:
        env = env_by_id.get(a["strava_id"])
        if not env:
            continue
        pace = _effort_metric(a)
        if not pace:
            continue
        by_sport[a["sport_type"]].append({
            "act": a, "env": env, "pace": pace, "hr": a["average_hr"],
        })

    # OLS per sport.
    sport_models: dict[str, tuple[float, float]] = {}
    for sport, entries in by_sport.items():
        if len(entries) < 3:
            continue
        xs = [e["pace"] for e in entries]
        ys = [e["hr"] for e in entries]
        model = _linreg(xs, ys)
        if model:
            sport_models[sport] = model

    # Final per-activity rows with residual.
    for sport, entries in by_sport.items():
        model = sport_models.get(sport)
        for e in entries:
            a, env = e["act"], e["env"]
            predicted = (model[0] + model[1] * e["pace"]) if model else None
            residual = (e["hr"] - predicted) if predicted is not None else None
            row = {
                "strava_id": a["strava_id"],
                "date": (a["start_date"] or "")[:10],
                "name": a.get("name"),
                "sport": sport,
                "distance_km": round((a["distance"] or 0) / 1000.0, 2),
                "duration_min": round((a["moving_time"] or 0) / 60.0, 1),
                "pace": fmt_pace(e["pace"]) if sport in ("Run", "Walk", "TrailRun") else None,
                "pace_min_km": round(e["pace"], 3),
                "avg_hr": round(e["hr"], 0),
                "max_hr": round(a.get("max_hr") or 0, 0) or None,
                "hr_residual_bpm": round(residual, 1) if residual is not None else None,
                "temp_c": round(env["temp_c"], 1) if env.get("temp_c") is not None else None,
            }
            day_flags = []
            for var in (
                "grass_pollen", "olive_pollen", "birch_pollen", "alder_pollen",
                "mugwort_pollen", "ragweed_pollen", "pm2_5", "pm10", "ozone",
            ):
                v = env.get(var)
                row[var] = round(v, 1) if isinstance(v, (int, float)) else None
                b = _bucket(v, var)
                if b and b in ("high", "very_high", "unhealthy", "very_unhealthy"):
                    day_flags.append(f"{var}:{b}")
            row["env_flags"] = day_flags
            rows.append(row)

    if not rows:
        output_error("Could not assemble any activity row with environmental data.")

    rows.sort(key=lambda r: r["date"], reverse=True)

    # Correlations per sport (residual vs each env variable).
    env_keys = list(THRESHOLDS.keys()) + ["temp_c"]
    correlations: dict[str, dict] = {}
    for sport in sport_models:
        sport_rows = [r for r in rows if r["sport"] == sport and r["hr_residual_bpm"] is not None]
        if len(sport_rows) < 5:
            continue
        ys = [r["hr_residual_bpm"] for r in sport_rows]
        per_var: dict[str, dict] = {}
        for var in env_keys:
            xs_pairs = [
                (r[var], r["hr_residual_bpm"])
                for r in sport_rows
                if r.get(var) is not None
            ]
            if len(xs_pairs) < 5:
                continue
            xs = [p[0] for p in xs_pairs]
            ys_local = [p[1] for p in xs_pairs]
            r_value = _pearson(xs, ys_local)
            if r_value is None:
                continue
            per_var[var] = {
                "pearson_r": round(r_value, 3),
                "strength": _strength(r_value),
                "direction": "higher_hr_when_higher" if r_value > 0 else "higher_hr_when_lower",
                "n": len(xs_pairs),
            }
        correlations[sport] = {
            "n_sessions": len(sport_rows),
            "model_hr_intercept": round(sport_models[sport][0], 2),
            "model_hr_slope_per_min_km": round(sport_models[sport][1], 2),
            "per_variable": per_var,
        }

    # Threshold buckets: mean HR residual per bucket per variable per sport.
    threshold_buckets: dict[str, dict] = {}
    for sport in sport_models:
        sport_rows = [r for r in rows if r["sport"] == sport and r["hr_residual_bpm"] is not None]
        if len(sport_rows) < 5:
            continue
        per_var_buckets: dict[str, dict] = {}
        for var in THRESHOLDS:
            buckets: dict[str, list[float]] = defaultdict(list)
            for r in sport_rows:
                b = _bucket(r.get(var), var)
                if b:
                    buckets[b].append(r["hr_residual_bpm"])
            if buckets:
                per_var_buckets[var] = {
                    label: {
                        "n": len(vals),
                        "mean_residual_bpm": round(sum(vals) / len(vals), 1),
                    }
                    for label, vals in buckets.items()
                }
        threshold_buckets[sport] = per_var_buckets

    # Top flagged days — activities that hit ≥2 high/unhealthy env thresholds.
    top_flagged = sorted(
        [r for r in rows if len(r["env_flags"]) >= 2],
        key=lambda r: (len(r["env_flags"]), r["hr_residual_bpm"] or 0),
        reverse=True,
    )[:10]

    return {
        "window_days": days,
        "n_activities": len(rows),
        "sports": sorted(by_sport.keys()),
        "rows": rows,
        "correlations": correlations,
        "threshold_buckets": threshold_buckets,
        "top_flagged_days": top_flagged,
        "clinical_thresholds": {
            var: [{"label": lbl, "ceiling": (None if math.isinf(c) else c)}
                  for lbl, c in bands]
            for var, bands in THRESHOLDS.items()
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=90)
    args = p.parse_args()

    try:
        data = analyse(args.days)
        output_json(data)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
