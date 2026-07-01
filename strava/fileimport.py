"""Import manually-exported activity files (TCX / GPX) into the local DB.

The athlete exports their own activity from Strava or Garmin *by hand*; this
module parses that local file and populates the same tables the API sync used
to fill:

  - activities         (summary row + raw_json, incl. a synthesized
                        ``splits_metric`` so session-analysis produces per-km)
  - activity_streams   (per-point time series in Strava's stream shape)
  - activity_laps      (watch laps -- powers interval/fartlek detection; TCX only)

There is NO network access here: no Strava/Garmin API, no login, no scraping.
It only reads a file the user already downloaded. Automated *access to* the
services is what their Terms prohibit; parsing a file you exported yourself is
not that.

Supported inputs: ``.tcx`` and ``.gpx`` (and their ``.gz`` variants). FIT is
intentionally not handled here -- it needs a third-party parser which must be
vetted before adding.
"""
from __future__ import annotations

import glob
import gzip
import math
import os
import sqlite3
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from strava.db import save_laps, save_streams, upsert_activities

_MOVING_SPEED_MS = 0.8  # below this a point is considered stopped


# --------------------------------------------------------------------------- #
# XML helpers (namespace-agnostic: match on local tag name)                   #
# --------------------------------------------------------------------------- #
def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kids(el, name: str) -> list:
    if el is None:
        return []
    return [c for c in el if _localname(c.tag) == name]


def _kid(el, name: str):
    if el is None:
        return None
    for c in el:
        if _localname(c.tag) == name:
            return c
    return None


def _deep(el, name: str) -> list:
    if el is None:
        return []
    return [e for e in el.iter() if _localname(e.tag) == name]


def _ftext(el):
    """Float text of an element, or None."""
    if el is None or el.text is None or not el.text.strip():
        return None
    try:
        return float(el.text.strip())
    except ValueError:
        return None


def _parse_time(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1] + "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _read_xml_root(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rb") as fh:
        return ET.parse(fh).getroot()


# --------------------------------------------------------------------------- #
# Geometry / signal helpers                                                   #
# --------------------------------------------------------------------------- #
def _haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _forward_fill(vals: list):
    out, last = [], None
    for v in vals:
        if v is not None:
            last = v
        out.append(last)
    # back-fill any leading Nones from the first known value
    first = next((v for v in out if v is not None), None)
    return [v if v is not None else first for v in out]


def _moving_average(vals: list, window: int = 5) -> list:
    if not vals:
        return []
    half = window // 2
    out = []
    for i in range(len(vals)):
        lo, hi = max(0, i - half), min(len(vals), i + half + 1)
        chunk = [v for v in vals[lo:hi] if v is not None]
        out.append(sum(chunk) / len(chunk) if chunk else None)
    return out


def _stream(data: list) -> dict:
    return {
        "data": data,
        "series_type": "distance",
        "original_size": len(data),
        "resolution": "high",
    }


# --------------------------------------------------------------------------- #
# Format parsers -> list of raw point dicts + raw laps                        #
# --------------------------------------------------------------------------- #
def _parse_tcx_point(tp) -> dict | None:
    t = _parse_time(_kid(tp, "Time").text if _kid(tp, "Time") is not None else "")
    if t is None:
        return None
    pos = _kid(tp, "Position")
    lat = _ftext(_kid(pos, "LatitudeDegrees")) if pos is not None else None
    lon = _ftext(_kid(pos, "LongitudeDegrees")) if pos is not None else None
    hr_el = _kid(_kid(tp, "HeartRateBpm"), "Value")
    run_cad = _deep(tp, "RunCadence")
    cad = _ftext(run_cad[0]) if run_cad else _ftext(_kid(tp, "Cadence"))
    speed = _deep(tp, "Speed")
    watts = _deep(tp, "Watts")
    return {
        "t": t,
        "lat": lat,
        "lon": lon,
        "ele": _ftext(_kid(tp, "AltitudeMeters")),
        "dist": _ftext(_kid(tp, "DistanceMeters")),
        "hr": _ftext(hr_el),
        "cad": cad,
        "speed": _ftext(speed[0]) if speed else None,
        "watts": _ftext(watts[0]) if watts else None,
    }


def parse_tcx(root) -> tuple[list, list, str | None, str | None]:
    activity = (_deep(root, "Activity") or [None])[0]
    sport = activity.get("Sport") if activity is not None else None
    name = None
    points: list = []
    laps: list = []
    for li, lap_el in enumerate(_kids(activity, "Lap")):
        start_idx = len(points)
        for track in _kids(lap_el, "Track"):
            for tp in _kids(track, "Trackpoint"):
                p = _parse_tcx_point(tp)
                if p:
                    points.append(p)
        end_idx = len(points) - 1
        if end_idx < start_idx:
            continue  # empty lap
        laps.append({
            "_start_idx": start_idx,
            "_end_idx": end_idx,
            "lap_index": li + 1,
            "total_time_s": _ftext(_kid(lap_el, "TotalTimeSeconds")),
        })
    return points, laps, sport, name


def parse_gpx(root) -> tuple[list, list, str | None, str | None]:
    trk = (_deep(root, "trk") or [None])[0]
    name_el = _kid(trk, "name")
    name = name_el.text.strip() if name_el is not None and name_el.text else None
    type_el = _kid(trk, "type")
    sport = type_el.text.strip() if type_el is not None and type_el.text else None
    points: list = []
    for tp in _deep(root, "trkpt"):
        t = _parse_time(_kid(tp, "time").text if _kid(tp, "time") is not None else "")
        if t is None:
            continue
        hr = next((_ftext(e) for e in tp.iter() if _localname(e.tag) == "hr"), None)
        cad = next((_ftext(e) for e in tp.iter() if _localname(e.tag) == "cad"), None)
        try:
            lat = float(tp.get("lat"))
            lon = float(tp.get("lon"))
        except (TypeError, ValueError):
            lat = lon = None
        points.append({
            "t": t, "lat": lat, "lon": lon,
            "ele": _ftext(_kid(tp, "ele")),
            "dist": None, "hr": hr, "cad": cad, "speed": None, "watts": None,
        })
    return points, [], sport, name


# --------------------------------------------------------------------------- #
# Sport mapping                                                               #
# --------------------------------------------------------------------------- #
_SPORT_MAP = {
    "running": "Run", "run": "Run",
    "biking": "Ride", "cycling": "Ride", "ride": "Ride", "virtualride": "VirtualRide",
    "swimming": "Swim", "swim": "Swim",
    "walking": "Walk", "hiking": "Hike",
}


def _map_sport(raw: str | None) -> str:
    if not raw:
        return "Run"
    return _SPORT_MAP.get(raw.strip().lower(), "Run")


# --------------------------------------------------------------------------- #
# Bundle builder: raw points -> activity dict + streams + laps                #
# --------------------------------------------------------------------------- #
def build_bundle(points: list, raw_laps: list, sport_raw: str | None,
                 name: str | None, athlete_id: int | None,
                 source_name: str) -> dict:
    points = [p for p in points if p.get("t") is not None]
    if len(points) < 2:
        raise ValueError("file has fewer than 2 track points with a timestamp")

    t0 = points[0]["t"]
    times = [int((p["t"] - t0).total_seconds()) for p in points]

    # Distance stream: prefer device cumulative distance, else haversine cumsum.
    if any(p["dist"] is not None for p in points):
        dist = _forward_fill([p["dist"] for p in points])
        dist = [d if d is not None else 0.0 for d in dist]
        for i in range(1, len(dist)):  # enforce monotonic non-decreasing
            if dist[i] < dist[i - 1]:
                dist[i] = dist[i - 1]
    else:
        dist = [0.0]
        for i in range(1, len(points)):
            a, b = points[i - 1], points[i]
            if None not in (a["lat"], a["lon"], b["lat"], b["lon"]):
                dist.append(dist[-1] + _haversine(a["lat"], a["lon"], b["lat"], b["lon"]))
            else:
                dist.append(dist[-1])

    ele = _forward_fill([p["ele"] for p in points])
    lat = _forward_fill([p["lat"] for p in points])
    lon = _forward_fill([p["lon"] for p in points])
    hr = _forward_fill([p["hr"] for p in points])
    cad = _forward_fill([p["cad"] for p in points])
    watts = [p["watts"] for p in points]

    # Instantaneous speed (m/s) from distance/time deltas, then smoothed.
    inst_v = [0.0]
    for i in range(1, len(points)):
        dt = times[i] - times[i - 1]
        dd = dist[i] - dist[i - 1]
        inst_v.append(dd / dt if dt > 0 else 0.0)
    velocity = _moving_average(inst_v, 5)

    # Grade (%) from altitude/distance deltas, smoothed and clipped.
    ele_s = _moving_average(ele, 5) if any(e is not None for e in ele) else None
    grade = None
    if ele_s and all(e is not None for e in ele_s):
        raw_g = [0.0]
        for i in range(1, len(points)):
            dd = dist[i] - dist[i - 1]
            raw_g.append(max(-45.0, min(45.0, (ele_s[i] - ele_s[i - 1]) / dd * 100)) if dd > 0.3 else raw_g[-1])
        grade = _moving_average(raw_g, 5)

    moving = [v > _MOVING_SPEED_MS for v in velocity]

    # ---- summary ----
    elapsed = times[-1]
    moving_time = sum(
        (times[i] - times[i - 1]) for i in range(1, len(points)) if velocity[i] > _MOVING_SPEED_MS
    ) or elapsed
    total_dist = dist[-1]
    hr_vals = [p["hr"] for p in points if p["hr"] is not None]
    gain = 0.0
    if ele_s and all(e is not None for e in ele_s):
        for i in range(1, len(ele_s)):
            d = ele_s[i] - ele_s[i - 1]
            if d > 0:
                gain += d

    start_iso = t0.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    synth_id = -int(t0.timestamp())  # stable, negative -> never collides w/ Strava ids
    sport = _map_sport(sport_raw)

    # ---- per-km splits_metric (what session-analysis reads) ----
    splits = _build_splits(points, times, dist, hr, ele)

    # ---- streams (Strava shape) ----
    streams: dict = {
        "time": _stream(times),
        "distance": _stream([round(d, 1) for d in dist]),
        "velocity_smooth": _stream([round(v, 3) for v in velocity]),
        "moving": _stream(moving),
    }
    has_gps = all(v is not None for v in lat) and all(v is not None for v in lon)
    if any(e is not None for e in ele):
        streams["altitude"] = _stream([round(e, 1) if e is not None else None for e in ele])
    if grade:
        streams["grade_smooth"] = _stream([round(g, 1) if g is not None else 0.0 for g in grade])
    if has_gps:
        streams["latlng"] = _stream([[round(a, 6), round(b, 6)] for a, b in zip(lat, lon)])
    if any(h is not None for h in hr):
        streams["heartrate"] = _stream([int(h) if h is not None else None for h in hr])
    if any(c is not None for c in cad):
        streams["cadence"] = _stream([int(c) if c is not None else None for c in cad])
    if any(w is not None for w in watts):
        streams["watts"] = _stream(watts)

    # ---- laps (TCX only) ----
    laps = _build_laps(raw_laps, points, times, dist, hr, cad)

    activity = {
        "id": synth_id,
        "athlete": {"id": athlete_id},
        "name": name or f"Imported {sport} {start_iso[:10]}",
        "sport_type": sport,
        "type": sport,
        "start_date": start_iso,
        "distance": round(total_dist, 1),
        "moving_time": int(moving_time),
        "elapsed_time": int(elapsed),
        "total_elevation_gain": round(gain, 1),
        "average_speed": round(total_dist / moving_time, 3) if moving_time else None,
        "max_speed": round(max(velocity), 3) if velocity else None,
        "average_heartrate": round(sum(hr_vals) / len(hr_vals), 1) if hr_vals else None,
        "max_heartrate": max(hr_vals) if hr_vals else None,
        "average_watts": None,
        "kilojoules": None,
        "kudos_count": 0,
        "start_latlng": [round(lat[0], 6), round(lon[0], 6)] if has_gps else None,
        "end_latlng": [round(lat[-1], 6), round(lon[-1], 6)] if has_gps else None,
        "splits_metric": splits,
        "manual_import": {"source_file": source_name, "format": "tcx/gpx"},
    }

    return {
        "activity": activity,
        "streams": streams,
        "laps": laps,
        "summary": {
            "strava_id": synth_id,
            "name": activity["name"],
            "sport_type": sport,
            "start_date": start_iso,
            "distance_km": round(total_dist / 1000, 2),
            "n_points": len(points),
            "n_laps": len(laps),
            "has_hr": bool(hr_vals),
        },
    }


def _build_splits(points, times, dist, hr, ele) -> list:
    """Bin points into 1 km splits, in Strava's splits_metric shape."""
    splits: list = []
    n = len(points)
    if n < 2 or dist[-1] < 100:
        return splits
    n_bins = int(dist[-1] // 1000) + 1
    for b in range(n_bins):
        lo_m, hi_m = b * 1000, (b + 1) * 1000
        idxs = [i for i in range(n) if lo_m <= dist[i] < hi_m or (b == n_bins - 1 and dist[i] >= lo_m)]
        if len(idxs) < 2:
            continue
        i0, i1 = idxs[0], idxs[-1]
        seg_dist = dist[i1] - dist[i0]
        seg_time = times[i1] - times[i0]
        if seg_dist < 50 or seg_time <= 0:
            continue
        hr_seg = [hr[i] for i in idxs if hr[i] is not None]
        ele_seg = [ele[i] for i in idxs if ele[i] is not None]
        splits.append({
            "split": b + 1,
            "distance": round(seg_dist, 1),
            "elapsed_time": int(seg_time),
            "moving_time": int(seg_time),
            "average_speed": round(seg_dist / seg_time, 3),
            "average_heartrate": round(sum(hr_seg) / len(hr_seg), 1) if hr_seg else None,
            "elevation_difference": round(ele_seg[-1] - ele_seg[0], 1) if len(ele_seg) >= 2 else 0.0,
        })
    return splits


def _build_laps(raw_laps, points, times, dist, hr, cad) -> list:
    laps: list = []
    for lp in raw_laps:
        s, e = lp["_start_idx"], lp["_end_idx"]
        if e <= s:
            continue
        seg_dist = dist[e] - dist[s]
        seg_time = lp.get("total_time_s") or (times[e] - times[s])
        hr_seg = [points[i]["hr"] for i in range(s, e + 1) if points[i]["hr"] is not None]
        cad_seg = [points[i]["cad"] for i in range(s, e + 1) if points[i]["cad"] is not None]
        laps.append({
            "lap_index": lp["lap_index"],
            "name": f"Lap {lp['lap_index']}",
            "start_index": s,
            "end_index": e,
            "distance": round(seg_dist, 1),
            "elapsed_time": int(seg_time),
            "moving_time": int(seg_time),
            "average_speed": round(seg_dist / seg_time, 3) if seg_time else None,
            "max_speed": None,
            "average_heartrate": round(sum(hr_seg) / len(hr_seg), 1) if hr_seg else None,
            "max_heartrate": max(hr_seg) if hr_seg else None,
            "average_cadence": round(sum(cad_seg) / len(cad_seg), 1) if cad_seg else None,
            "total_elevation_gain": None,
        })
    return laps


# --------------------------------------------------------------------------- #
# Public entry points                                                         #
# --------------------------------------------------------------------------- #
def parse_file(path: str, athlete_id: int | None) -> dict:
    """Parse a TCX/GPX(.gz) file into an import bundle. No DB writes."""
    root = _read_xml_root(path)
    tag = _localname(root.tag).lower()
    if tag == "gpx":
        points, laps, sport, name = parse_gpx(root)
    elif "trainingcenterdatabase" in tag:
        points, laps, sport, name = parse_tcx(root)
    else:
        # Fall back on content sniffing (some files omit a clean root name).
        if _deep(root, "Trackpoint"):
            points, laps, sport, name = parse_tcx(root)
        elif _deep(root, "trkpt"):
            points, laps, sport, name = parse_gpx(root)
        else:
            raise ValueError(f"unrecognised file format (root=<{_localname(root.tag)}>)")
    return build_bundle(points, laps, sport, name, athlete_id, os.path.basename(path))


def _existing_activity_id(db_path: str, start_date: str) -> int | None:
    """Return the strava_id of an activity already stored at this exact start
    timestamp, if any (used to avoid duplicating an activity that a prior API
    sync already stored under its real Strava id)."""
    try:
        con = sqlite3.connect(db_path)
        row = con.execute(
            "SELECT strava_id FROM activities WHERE start_date = ? LIMIT 1", (start_date,)
        ).fetchone()
        con.close()
        return int(row[0]) if row else None
    except sqlite3.Error:
        return None


def import_file(db_path: str, path: str, athlete_id: int | None) -> dict:
    """Parse a file and persist it (activity + streams + laps). Returns summary.

    Dedup: if an activity already exists at the same exact start timestamp under
    a *different* id (e.g. a legacy API-synced row), the file is treated as a
    duplicate and NOT re-inserted -- so we never end up with two rows for the
    same run.
    """
    bundle = parse_file(path, athlete_id)
    summary = bundle["summary"]
    synth_id = summary["strava_id"]

    existing = _existing_activity_id(db_path, summary["start_date"])
    if existing is not None and existing != synth_id:
        summary["status"] = "duplicate"
        summary["existing_strava_id"] = existing
        return summary

    upsert_activities(db_path, [bundle["activity"]])
    save_streams(db_path, synth_id, bundle["streams"])
    if bundle["laps"]:
        save_laps(db_path, synth_id, bundle["laps"])
    summary["status"] = "imported"
    return summary


# --------------------------------------------------------------------------- #
# Downloads-folder ingestion (the canonical data-in flow; replaces API sync)  #
# --------------------------------------------------------------------------- #
ACTIVITY_GLOBS = ["*.tcx", "*.gpx", "*.tcx.gz", "*.gpx.gz"]
FIT_GLOBS = ["*.fit", "*.fit.gz"]


def resolve_downloads_dir(override: str | None = None) -> str | None:
    """Locate the user's Downloads folder (honours localized dirs like Descargas)."""
    if override:
        return override if os.path.isdir(override) else None
    env = os.environ.get("XDG_DOWNLOAD_DIR")
    if env and os.path.isdir(env):
        return env
    try:
        out = subprocess.run(
            ["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=5
        )
        cand = out.stdout.strip()
        if cand and os.path.isdir(cand):
            return cand
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    for cand in (os.path.expanduser("~/Downloads"), os.path.expanduser("~/Descargas")):
        if os.path.isdir(cand):
            return cand
    return None


def resolve_athlete_id(db_path: str) -> int | None:
    """Reuse the athlete id already present in the DB for imported activities."""
    try:
        con = sqlite3.connect(db_path)
        row = con.execute(
            "SELECT athlete_id FROM activities WHERE athlete_id IS NOT NULL "
            "ORDER BY start_date DESC LIMIT 1"
        ).fetchone()
        con.close()
        return int(row[0]) if row else None
    except sqlite3.Error:
        return None


def import_from_downloads(db_path: str, downloads_dir: str | None = None,
                          athlete_id: int | None = None,
                          delete: bool = True, dry_run: bool = False) -> dict:
    """Scan the Downloads folder, import any activity files, delete on success.

    Returns a report whose ``action_needed`` field drives the caller:
      - ``"none"``               -> new data imported (or nothing to do but files present)
      - ``"export_then_import"`` -> no activity files found; the caller should open
                                    the browser, wait for the user to export, retry
      - ``"review_failures"``    -> files were present but all failed to parse
      - ``"configure_downloads_dir"`` -> Downloads folder could not be located
    """
    downloads = resolve_downloads_dir(downloads_dir)
    if not downloads:
        return {
            "downloads_dir": None, "athlete_id": athlete_id, "dry_run": dry_run,
            "deleted_after_import": False, "new_files_found": 0, "imported_count": 0,
            "imported": [], "deleted": [], "failed": [], "skipped_fit": [],
            "action_needed": "configure_downloads_dir",
        }
    if athlete_id is None:
        athlete_id = resolve_athlete_id(db_path)

    files = sorted({f for pat in ACTIVITY_GLOBS
                    for f in glob.glob(os.path.join(downloads, pat))})
    skipped_fit = sorted({f for pat in FIT_GLOBS
                          for f in glob.glob(os.path.join(downloads, pat))})

    imported, duplicates, failed, deleted = [], [], [], []
    for path in files:
        try:
            if dry_run:
                summary = parse_file(path, athlete_id)["summary"]
                existing = _existing_activity_id(db_path, summary["start_date"])
                if existing is not None and existing != summary["strava_id"]:
                    summary["status"] = "duplicate"
                    summary["existing_strava_id"] = existing
                else:
                    summary["status"] = "preview"
            else:
                summary = import_file(db_path, path, athlete_id)
            summary["file"] = os.path.basename(path)
        except Exception as exc:  # noqa: BLE001 -- report bad files, never crash the batch
            failed.append({"file": os.path.basename(path), "error": str(exc)})
            continue

        if summary.get("status") == "duplicate":
            duplicates.append(summary)
        else:
            imported.append(summary)

        # Delete on success. Duplicates are already captured in the DB, so the
        # redundant file is removed too (keeps Downloads clean, as requested).
        if delete and not dry_run:
            try:
                os.remove(path)
                deleted.append(os.path.basename(path))
            except OSError as exc:
                summary["delete_error"] = str(exc)

    if not files:
        action = "export_then_import"
    elif imported or duplicates:
        action = "none"
    else:
        action = "review_failures"

    return {
        "downloads_dir": downloads, "athlete_id": athlete_id, "dry_run": dry_run,
        "deleted_after_import": delete and not dry_run,
        "new_files_found": len(files),
        "imported_count": len(imported), "duplicate_count": len(duplicates),
        "imported": imported, "duplicates": duplicates, "deleted": deleted,
        "failed": failed,
        "skipped_fit": [os.path.basename(f) for f in skipped_fit],
        "action_needed": action,
    }
