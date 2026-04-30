#!/usr/bin/env python3
"""Deep analysis of a single training session: per-km splits, HR drift,
cadence, and comparison to the planned session."""

import argparse
import json
import math
import os
import sqlite3
import sys
from datetime import date, datetime, timezone

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
sys.path.insert(0, PROJECT_ROOT)

from strava.client import StravaClient, get_default_db_path, output_error, output_json
from strava.db import get_planned_blocks, load_laps, load_token
from strava.sync import sync_summary


INTERVAL_SESSION_TYPES = {"fartlek", "interval", "tempo"}

# Lap-based detection thresholds
LAP_MIN_DURATION_S = 30           # laps shorter than this are ignored (auto-pauses, fragments)
LAP_BIMODAL_GAP_MIN_KM = 1.5      # min pace gap (min/km) between rep and recovery clusters
LAP_BIMODAL_BALANCE_RATIO = 0.20  # each cluster must hold ≥ this fraction of total laps
LAP_REP_PACE_RATIO_MAX = 0.80     # rep cluster avg pace must be ≤ this × recovery cluster avg
LAP_REP_PACE_CV_MAX = 0.15        # rep paces must be tight as a cluster (sd / mean)
LAP_PACE_FLOOR_TOLERANCE = 1.10   # rep candidate if pace ≤ planned floor × this
LAP_REP_DURATION_CV_MAX = 0.6     # max coefficient of variation of rep durations
# Absolute pace ceiling used when the athlete's threshold pace is unknown;
# a "rep" slower than this is almost certainly walking, not running fast.
DEFAULT_REP_PACE_CEILING_MIN_KM = 7.5
# Multiplier applied to the snapshot's threshold pace when checking if rep
# paces are reasonably fast (1.10 = within 10% of threshold).
SNAPSHOT_THRESHOLD_TOLERANCE = 1.10
MIN_REPS_FOR_INTERVAL_SESSION = 3
RECENT_INTERVALS_WINDOW_DAYS = 120
RECENT_INTERVALS_MAX = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def speed_to_pace_str(speed_m_s: float | None) -> str | None:
    """Convert m/s to M:SS/km string."""
    if not speed_m_s or speed_m_s <= 0:
        return None
    total_sec = 1000.0 / speed_m_s
    mins = int(total_sec // 60)
    secs = int(total_sec % 60)
    return f"{mins}:{secs:02d}"


def speed_to_pace_float(speed_m_s: float | None) -> float | None:
    """Convert m/s to decimal min/km."""
    if not speed_m_s or speed_m_s <= 0:
        return None
    return round((1000.0 / speed_m_s) / 60.0, 3)


def avg_vs_range(value: float | None, low: float, high: float) -> str:
    if value is None:
        return "unknown"
    if value < low:
        return "below"
    if value > high:
        return "above"
    return "inside"


def pace_zone(pace_min_km: float, threshold: float) -> str:
    """Map a pace (min/km) to Z1-Z5 given threshold pace (min/km)."""
    if pace_min_km > threshold * 1.30:
        return "Z1"
    if pace_min_km > threshold * 1.15:
        return "Z2"
    if pace_min_km > threshold * 1.05:
        return "Z3"
    if pace_min_km > threshold * 0.97:
        return "Z4"
    return "Z5"


def hr_zone(avg_hr: float, hr_max: float, hr_rest: float) -> str:
    """Map avg HR to Z1-Z5 using Karvonen (%HRR) model.

    Boundaries (%HRR): Z1 <60%, Z2 60-70%, Z3 70-80%, Z4 80-90%, Z5 >=90%.
    """
    hrr = hr_max - hr_rest
    if hrr <= 0:
        return "?"
    pct = (avg_hr - hr_rest) / hrr
    if pct < 0.60:
        return "Z1"
    if pct < 0.70:
        return "Z2"
    if pct < 0.80:
        return "Z3"
    if pct < 0.90:
        return "Z4"
    return "Z5"


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def find_activity(db_path: str, strava_id: int | None, target_date: str | None) -> dict | None:
    """Find an activity by strava_id or by date (most recent on that day)."""
    conn = _connect(db_path)
    try:
        if strava_id:
            row = conn.execute(
                "SELECT * FROM activities WHERE strava_id = ?", (strava_id,)
            ).fetchone()
        elif target_date:
            row = conn.execute(
                "SELECT * FROM activities WHERE date(start_date) = date(?) ORDER BY start_date DESC LIMIT 1",
                (target_date,),
            ).fetchone()
        else:
            return None
        return dict(row) if row else None
    finally:
        conn.close()


def find_planned_session(db_path: str, athlete_id: int, target_date: str, sport_type: str) -> dict | None:
    """Find a planned session for the same day and sport."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """SELECT * FROM planned_sessions
               WHERE athlete_id = ? AND plan_date = ? AND sport_type = ?
               ORDER BY id ASC LIMIT 1""",
            (athlete_id, target_date, sport_type),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_snapshot_params(db_path: str, athlete_id: int) -> dict:
    """Read threshold_pace, hr_max, and hr_rest from the latest snapshot."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT threshold_pace_min_km, hr_max_bpm, hr_rest_bpm FROM athlete_snapshots "
            "WHERE athlete_id = ? ORDER BY captured_at DESC LIMIT 1",
            (athlete_id,),
        ).fetchone()
        if not row:
            return {}
        return {
            "threshold_pace": row["threshold_pace_min_km"],
            "hr_max": row["hr_max_bpm"],
            "hr_rest": row["hr_rest_bpm"],
        }
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_splits(splits: list[dict], laps: list[dict] | None,
                    threshold: float | None,
                    hr_max: float | None = None,
                    hr_rest: float | None = None) -> dict:
    """Build per-km analysis from splits_metric and optional laps.

    Zone classification priority: HR-based (Karvonen) when HR data is
    available, pace-based as fallback.  Both are included when possible.
    """
    has_hr_zones = hr_max is not None and hr_rest is not None and hr_max > hr_rest
    per_km = []
    for s in splits:
        dist = s.get("distance", 0)
        if dist < 100:
            continue  # skip tiny final fragment for per-km table

        time_s = s.get("moving_time") or s.get("elapsed_time", 0)
        avg_speed = s.get("average_speed", 0)
        avg_hr = s.get("average_heartrate")
        elev = s.get("elevation_difference", 0)

        pace_str = speed_to_pace_str(avg_speed)
        pace_float = speed_to_pace_float(avg_speed)

        entry = {
            "km": s.get("split", 0),
            "distance_m": round(dist, 0),
            "time_s": time_s,
            "pace": pace_str,
            "pace_min_km": pace_float,
            "avg_hr": round(avg_hr, 1) if avg_hr else None,
            "elevation_m": round(elev, 1),
        }

        # Primary zone: HR-based (Karvonen) when HR data exists
        if has_hr_zones and avg_hr:
            entry["zone"] = hr_zone(avg_hr, hr_max, hr_rest)
        elif threshold and pace_float:
            entry["zone"] = pace_zone(pace_float, threshold)

        # Secondary: always include pace_zone when threshold is known
        if threshold and pace_float:
            entry["pace_zone"] = pace_zone(pace_float, threshold)

        per_km.append(entry)

    # Enrich with cadence from laps (Strava reports cadence per lap, not per split)
    if laps:
        for i, km in enumerate(per_km):
            if i < len(laps):
                lap = laps[i]
                km["cadence_spm"] = lap.get("average_cadence")

    # HR drift: first half vs second half
    full_km_splits = [s for s in per_km if s.get("avg_hr")]
    hr_drift = None
    if len(full_km_splits) >= 4:
        mid = len(full_km_splits) // 2
        first_half_hr = sum(s["avg_hr"] for s in full_km_splits[:mid]) / mid
        second_half_hr = sum(s["avg_hr"] for s in full_km_splits[mid:]) / (len(full_km_splits) - mid)
        first_half_pace = sum(s["pace_min_km"] for s in full_km_splits[:mid] if s.get("pace_min_km")) / mid
        second_half_pace = sum(s["pace_min_km"] for s in full_km_splits[mid:] if s.get("pace_min_km")) / (len(full_km_splits) - mid)
        hr_drift = {
            "first_half_hr": round(first_half_hr, 1),
            "second_half_hr": round(second_half_hr, 1),
            "delta_hr": round(second_half_hr - first_half_hr, 1),
            "drift_pct": round(100.0 * (second_half_hr - first_half_hr) / first_half_hr, 1),
            "first_half_pace": round(first_half_pace, 3),
            "second_half_pace": round(second_half_pace, 3),
        }

    # Pace consistency
    paces = [s["pace_min_km"] for s in per_km if s.get("pace_min_km")]
    pace_stats = None
    if paces:
        avg_p = sum(paces) / len(paces)
        std_p = math.sqrt(sum((p - avg_p) ** 2 for p in paces) / len(paces))
        pace_stats = {
            "avg_pace_min_km": round(avg_p, 3),
            "std_dev_min_km": round(std_p, 3),
            "fastest_km": min(range(len(per_km)), key=lambda i: per_km[i].get("pace_min_km") or 99) + 1,
            "slowest_km": max(range(len(per_km)), key=lambda i: per_km[i].get("pace_min_km") or 0) + 1,
            "negative_split": paces[-1] < paces[0] if len(paces) >= 2 else None,
        }

    # Zone distribution
    zone_dist = {}
    if threshold:
        for km in per_km:
            z = km.get("zone", "?")
            zone_dist[z] = zone_dist.get(z, 0) + 1

    return {
        "per_km": per_km,
        "hr_drift": hr_drift,
        "pace_stats": pace_stats,
        "zone_distribution": zone_dist or None,
    }


def parse_pace_value(val) -> float | None:
    """Convert a pace value that may be a string 'M:SS' or a float to float min/km."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str) and ":" in val:
        parts = val.split(":")
        return int(parts[0]) + int(parts[1]) / 60.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def load_streams(db_path: str, strava_id: int) -> dict | None:
    """Return decoded per-second streams dict or None if not cached."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT json_data FROM activity_streams WHERE strava_id = ?",
            (strava_id,),
        ).fetchone()
        if not row or not row["json_data"]:
            return None
        try:
            return json.loads(row["json_data"])
        except (TypeError, ValueError):
            return None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _series(streams: dict, key: str) -> list | None:
    obj = streams.get(key)
    if not obj or not isinstance(obj, dict):
        return None
    data = obj.get("data")
    return data if isinstance(data, list) else None


def detect_intervals(streams: dict, work_blocks: list[dict]) -> list[dict]:
    """Detect real work intervals from per-second velocity streams.

    Strategy: find contiguous windows where velocity_smooth is well above the
    session baseline and lasts at least half the planned rep duration. If
    more windows are found than planned, keep the top-N by average velocity.
    """
    if not work_blocks:
        return []

    t = _series(streams, "time")
    v = _series(streams, "velocity_smooth")
    if not t or not v or len(t) != len(v):
        return []

    hr = _series(streams, "heartrate") or [None] * len(t)
    d = _series(streams, "distance") or list(range(len(t)))
    cad = _series(streams, "cadence") or [None] * len(t)

    expected_n = sum(int(wb.get("repeat_count") or 1) for wb in work_blocks)
    min_planned_dur_s = min(
        (wb.get("duration_min") or 1) * 60 for wb in work_blocks
    )
    # Tolerant detection: rep must last >= 50% of planned duration
    min_dur_s = max(20, int(min_planned_dur_s * 0.5))

    # Velocity threshold: 75% of planned pace_slow (the slower end of target).
    # Picks up anything meaningfully faster than warmup pace.
    pace_slow = work_blocks[0].get("pace_slow_min_km")
    if pace_slow and pace_slow > 0:
        v_target = 1000.0 / (float(pace_slow) * 60.0)
        v_threshold = v_target * 0.75
    else:
        # Fallback: top 25% velocity across the activity
        sorted_v = sorted(v)
        v_threshold = sorted_v[int(len(sorted_v) * 0.75)] if sorted_v else 2.5

    n = len(t)
    segments = []
    i = 0
    while i < n:
        if v[i] is not None and v[i] >= v_threshold:
            j = i
            while j < n and v[j] is not None and v[j] >= v_threshold:
                j += 1
            if t[j - 1] - t[i] >= min_dur_s:
                segments.append((i, j - 1))
            i = j
        else:
            i += 1

    if len(segments) > expected_n > 0:
        def seg_avg_v(ab):
            a, b = ab
            return sum(v[a : b + 1]) / max(b - a + 1, 1)
        segments = sorted(segments, key=seg_avg_v, reverse=True)[:expected_n]
        segments.sort(key=lambda ab: ab[0])

    reps = []
    for idx, (a, b) in enumerate(segments, 1):
        dur = t[b] - t[a]
        dist_m = (d[b] - d[a]) if (d[b] is not None and d[a] is not None) else None
        v_arr = [x for x in v[a : b + 1] if x is not None]
        hr_arr = [x for x in hr[a : b + 1] if x is not None]
        cad_arr = [x for x in cad[a : b + 1] if x is not None]
        v_avg = sum(v_arr) / len(v_arr) if v_arr else 0
        rep = {
            "idx": idx,
            "t_start_s": t[a],
            "duration_s": dur,
            "distance_m": round(dist_m, 0) if dist_m is not None else None,
            "pace": speed_to_pace_str(v_avg),
            "pace_min_km": speed_to_pace_float(v_avg),
            "hr_avg": round(sum(hr_arr) / len(hr_arr), 1) if hr_arr else None,
            "hr_max": max(hr_arr) if hr_arr else None,
            "cadence_spm": round(sum(cad_arr) / len(cad_arr) * 2, 0) if cad_arr else None,
        }
        reps.append(rep)

    return reps


def detect_recoveries(streams: dict, reps: list[dict]) -> list[dict]:
    """Compute recovery gaps between consecutive reps."""
    if len(reps) < 2:
        return []
    t = _series(streams, "time") or []
    v = _series(streams, "velocity_smooth") or []
    hr = _series(streams, "heartrate") or []
    if not t:
        return []

    recoveries = []
    for i in range(len(reps) - 1):
        start_s = reps[i]["t_start_s"] + reps[i]["duration_s"]
        end_s = reps[i + 1]["t_start_s"]
        if end_s <= start_s:
            continue
        # Find indices
        try:
            a = next(k for k, ts in enumerate(t) if ts >= start_s)
            b = next(k for k, ts in enumerate(t) if ts >= end_s) - 1
        except StopIteration:
            continue
        if b < a:
            continue
        hr_arr = [x for x in hr[a : b + 1] if x is not None]
        recoveries.append({
            "after_rep": reps[i]["idx"],
            "duration_s": end_s - start_s,
            "hr_end": round(hr[b], 1) if b < len(hr) and hr[b] is not None else None,
            "hr_min_during": min(hr_arr) if hr_arr else None,
        })
    return recoveries


# ---------------------------------------------------------------------------
# Lap-based interval detection
#
# Watch laps are the source of truth for sessions with structure (fartlek,
# intervals, tempo with reps): the athlete pressed the lap button to mark
# rep / recovery transitions. Per-km auto-splits aggregate reps and
# recoveries into a single moderate-looking row and lose the structure
# entirely.
#
# Detection runs unconditionally — it does NOT require a planned session.
# Trigger condition is purely the shape of the lap data: at least
# MIN_REPS_FOR_INTERVAL_SESSION laps that are clearly faster than the
# remaining ones, with consistent durations.
# ---------------------------------------------------------------------------


def _lap_pace_min_km(lap: dict) -> float | None:
    speed = lap.get("average_speed")
    if not speed or speed <= 0:
        return None
    return (1000.0 / speed) / 60.0


def _enrich_laps(laps: list[dict]) -> list[dict]:
    """Filter out micro-laps and decorate with computed pace."""
    enriched = []
    for lap in laps:
        pace = _lap_pace_min_km(lap)
        if pace is None:
            continue
        dur = lap.get("moving_time") or lap.get("elapsed_time") or 0
        if dur < LAP_MIN_DURATION_S:
            continue
        enriched.append({"lap": lap, "pace": pace, "duration_s": dur})
    return enriched


def _decide_rep_threshold(
    enriched: list[dict], planned_pace_floor: float | None
) -> float | None:
    """Return the pace cutoff (min/km) below which a lap is a rep candidate.

    Strategy:
    1. If planned_pace_floor is given, use floor × LAP_PACE_FLOOR_TOLERANCE.
       This is the strongest signal — the plan declared rep pace explicitly.
    2. Otherwise, look for a clear bimodal split. To avoid treating a
       continuous run with one outlier lap as "intervals", the gap must:
       - exceed LAP_BIMODAL_GAP_MIN_KM (a real rep/recovery delta is huge),
       - sit in the central portion of the sorted distribution so that
         both clusters have at least LAP_BIMODAL_BALANCE_RATIO of the laps.
       Without these guards, an easy run with one slow cool-down lap looks
       indistinguishable from a 4-rep fartlek.
    """
    if planned_pace_floor:
        return planned_pace_floor * LAP_PACE_FLOOR_TOLERANCE

    paces = sorted(e["pace"] for e in enriched)
    n = len(paces)
    if n < 5:
        return None

    min_per_side = max(1, int(n * LAP_BIMODAL_BALANCE_RATIO))
    best_gap = 0.0
    best_split = -1
    # Only consider gaps that leave enough laps on both sides to form clusters
    for i in range(min_per_side - 1, n - min_per_side):
        gap = paces[i + 1] - paces[i]
        if gap > best_gap:
            best_gap = gap
            best_split = i
    if best_gap < LAP_BIMODAL_GAP_MIN_KM or best_split < 0:
        return None
    return paces[best_split] + best_gap / 2


def _validate_rep_consistency(rep_durations: list[int]) -> bool:
    """Reject the detection if rep durations are wildly inconsistent."""
    if len(rep_durations) < 2:
        return True
    avg = sum(rep_durations) / len(rep_durations)
    if avg <= 0:
        return False
    variance = sum((d - avg) ** 2 for d in rep_durations) / len(rep_durations)
    cv = (variance**0.5) / avg
    return cv <= LAP_REP_DURATION_CV_MAX


def _lap_to_segment_dict(
    enriched_entry: dict, segment_type: str, rep_num: int | None = None
) -> dict:
    lap = enriched_entry["lap"]
    return {
        "lap_index": lap.get("lap_index"),
        "name": lap.get("name"),
        "type": segment_type,
        "rep_num": rep_num,
        "duration_s": int(enriched_entry["duration_s"]),
        "duration_str": _seconds_to_clock(enriched_entry["duration_s"]),
        "distance_m": round(lap.get("distance") or 0, 0),
        "pace": speed_to_pace_str(lap.get("average_speed")),
        "pace_min_km": round(enriched_entry["pace"], 3),
        "avg_hr": (
            round(lap.get("average_heartrate"), 1)
            if lap.get("average_heartrate") is not None
            else None
        ),
        "max_hr": lap.get("max_heartrate"),
        "avg_cadence": (
            round(lap.get("average_cadence"), 1)
            if lap.get("average_cadence") is not None
            else None
        ),
        "elevation_gain_m": round(lap.get("total_elevation_gain") or 0, 1),
    }


def _trend(values: list[float], min_delta: float = 0.5) -> str | None:
    """Return 'ascending' / 'descending' / 'stable' over an ordered list."""
    if len(values) < 3:
        return None
    half = len(values) // 2
    first = sum(values[:half]) / half
    second = sum(values[half:]) / (len(values) - half)
    if second > first + min_delta:
        return "ascending"
    if second < first - min_delta:
        return "descending"
    return "stable"


def detect_intervals_from_laps(
    laps: list[dict],
    planned_pace_floor: float | None = None,
    planned_hr_target: int | None = None,
    threshold_pace_min_km: float | None = None,
) -> dict | None:
    """Classify watch laps into warmup / rep / recovery / cooldown.

    Returns None when the session does NOT show interval structure — i.e.
    when it's a continuous run that the athlete didn't break into reps.

    The output mirrors the streams-based detect_intervals shape (reps and
    recoveries) plus aggregate metrics for cross-session comparison.

    threshold_pace_min_km: optional threshold pace from the athlete snapshot,
    used to validate that rep pace is fast enough in absolute terms (rules
    out walk-jog sessions that look bimodal but aren't intervals).
    """
    if not laps:
        return None
    enriched = _enrich_laps(laps)
    if len(enriched) < MIN_REPS_FOR_INTERVAL_SESSION + 1:
        return None

    threshold = _decide_rep_threshold(enriched, planned_pace_floor)
    if threshold is None:
        return None

    rep_idx_set = {i for i, e in enumerate(enriched) if e["pace"] <= threshold}
    if len(rep_idx_set) < MIN_REPS_FOR_INTERVAL_SESSION:
        return None

    rep_indices = sorted(rep_idx_set)
    rep_durations = [enriched[i]["duration_s"] for i in rep_indices]
    if not _validate_rep_consistency(rep_durations):
        return None

    # Sanity: reps must be substantially faster than recoveries. Without this,
    # a walk-jog session (9:00/km vs 10:30/km laps) gets misclassified as
    # intervals. We require the rep cluster average to be at most
    # LAP_REP_PACE_RATIO_MAX times the recovery cluster average — i.e. reps
    # are meaningfully faster, not just slightly faster.
    rep_paces_for_check = [enriched[i]["pace"] for i in rep_indices]
    recovery_paces_for_check = [
        e["pace"] for i, e in enumerate(enriched) if i not in rep_idx_set
    ]
    if not (rep_paces_for_check and recovery_paces_for_check):
        return None
    rep_avg_pace = sum(rep_paces_for_check) / len(rep_paces_for_check)
    rec_avg_pace = sum(recovery_paces_for_check) / len(recovery_paces_for_check)
    if rec_avg_pace <= 0 or (rep_avg_pace / rec_avg_pace) > LAP_REP_PACE_RATIO_MAX:
        return None

    # Sanity: rep paces must be tight as a cluster. A cluster with paces
    # spanning 6:46 to 12:15 isn't a coherent rep set — that's a session
    # that started running and ended walking, not intervals.
    if len(rep_paces_for_check) >= 2:
        rep_pace_var = sum(
            (p - rep_avg_pace) ** 2 for p in rep_paces_for_check
        ) / len(rep_paces_for_check)
        rep_pace_cv = (rep_pace_var**0.5) / rep_avg_pace
        if rep_pace_cv > LAP_REP_PACE_CV_MAX:
            return None

    # Sanity: rep pace must be reasonably fast in absolute terms. Anchored
    # on the athlete's threshold pace when a snapshot is available, falls
    # back to a generic running ceiling otherwise. Without this guard a
    # walking session (rep avg 9:00/km vs recovery 12:00/km) would still
    # pass the bimodal test.
    pace_ceiling = (
        threshold_pace_min_km * SNAPSHOT_THRESHOLD_TOLERANCE
        if threshold_pace_min_km
        else DEFAULT_REP_PACE_CEILING_MIN_KM
    )
    if rep_avg_pace > pace_ceiling:
        return None

    first_rep = rep_indices[0]
    last_rep = rep_indices[-1]
    warmup_indices = list(range(0, first_rep))
    cooldown_indices = list(range(last_rep + 1, len(enriched)))
    recovery_indices = [
        i for i in range(first_rep + 1, last_rep) if i not in rep_idx_set
    ]

    reps_out = []
    for rep_num, idx in enumerate(rep_indices, 1):
        rep = _lap_to_segment_dict(enriched[idx], "rep", rep_num)
        if planned_hr_target and rep.get("max_hr") is not None:
            rep["target_hr_min"] = planned_hr_target
            rep["hr_peak_verdict"] = (
                "reached" if rep["max_hr"] >= planned_hr_target else "below"
            )
        reps_out.append(rep)

    recoveries_out = []
    for after_rep_n, idx in enumerate(recovery_indices, 1):
        rec = _lap_to_segment_dict(enriched[idx], "recovery")
        rec["after_rep"] = after_rep_n
        recoveries_out.append(rec)

    warmup_out = [_lap_to_segment_dict(enriched[i], "warmup") for i in warmup_indices]
    cooldown_out = [
        _lap_to_segment_dict(enriched[i], "cooldown") for i in cooldown_indices
    ]

    rep_paces = [r["pace_min_km"] for r in reps_out if r.get("pace_min_km") is not None]
    rep_hrs = [r["avg_hr"] for r in reps_out if r.get("avg_hr") is not None]
    rep_max_hrs = [r["max_hr"] for r in reps_out if r.get("max_hr") is not None]
    rep_cadences = [
        r["avg_cadence"] for r in reps_out if r.get("avg_cadence") is not None
    ]

    avg_pace = sum(rep_paces) / len(rep_paces) if rep_paces else None

    aggregate = {
        "n_reps": len(reps_out),
        "avg_rep_pace_min_km": round(avg_pace, 3) if avg_pace else None,
        "avg_rep_pace_str": (
            speed_to_pace_str(1000.0 / (avg_pace * 60.0)) if avg_pace else None
        ),
        "avg_rep_hr": round(sum(rep_hrs) / len(rep_hrs), 1) if rep_hrs else None,
        "avg_rep_max_hr": (
            round(sum(rep_max_hrs) / len(rep_max_hrs), 1) if rep_max_hrs else None
        ),
        "avg_rep_cadence": (
            round(sum(rep_cadences) / len(rep_cadences), 1) if rep_cadences else None
        ),
        "avg_rep_duration_s": int(sum(rep_durations) / len(rep_durations)),
        "rep_threshold_pace_min_km": round(threshold, 3),
        "cadence_trend": _trend(rep_cadences),
        "hr_trend": _trend(rep_hrs, min_delta=1.0),
        "pace_trend": _trend(rep_paces, min_delta=0.05),
    }

    if planned_hr_target:
        reached = sum(1 for r in reps_out if r.get("hr_peak_verdict") == "reached")
        aggregate["reps_reached_hr_target"] = reached
        aggregate["target_hr_min"] = planned_hr_target

    return {
        "source": "laps",
        "aggregate": aggregate,
        "warmup": warmup_out,
        "reps": reps_out,
        "recoveries": recoveries_out,
        "cooldown": cooldown_out,
    }


# ---------------------------------------------------------------------------
# Cross-session interval comparison
#
# When the focal session is detected as an interval session, surface a
# rep-aggregated comparison against the user's previous interval sessions
# in the last RECENT_INTERVALS_WINDOW_DAYS days. Per-km splits won't show
# this signal because they aggregate across reps and recoveries.
# ---------------------------------------------------------------------------


def _laps_for_activity(db_path: str, activity_row: dict) -> list[dict]:
    """Pull laps from the dedicated table, falling back to raw_json."""
    laps = load_laps(db_path, activity_row["strava_id"])
    if laps:
        return laps
    try:
        raw = json.loads(activity_row.get("raw_json") or "{}")
    except (TypeError, ValueError):
        return []
    return raw.get("laps") or []


def find_recent_interval_sessions(
    db_path: str,
    athlete_id: int,
    current_strava_id: int,
    sport_type: str,
    days: int = RECENT_INTERVALS_WINDOW_DAYS,
    limit: int = RECENT_INTERVALS_MAX,
    threshold_pace_min_km: float | None = None,
) -> list[dict]:
    """Walk recent activities, run lap-based detection on each, keep the
    ones that look like interval sessions. Returns oldest-first."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT * FROM activities
               WHERE athlete_id = ? AND sport_type = ?
                 AND strava_id != ?
                 AND date(start_date) >= date('now', ?)
               ORDER BY start_date DESC""",
            (athlete_id, sport_type, current_strava_id, f"-{days} days"),
        ).fetchall()
        candidates = [dict(r) for r in rows]
    finally:
        conn.close()

    found = []
    for c in candidates:
        laps = _laps_for_activity(db_path, c)
        if not laps:
            continue
        planned_for_c = find_planned_session(
            db_path, athlete_id, (c.get("start_date") or "")[:10], sport_type
        )
        is_planned_interval = bool(
            planned_for_c
            and planned_for_c.get("session_type") in INTERVAL_SESSION_TYPES
        )
        pace_floor = (
            parse_pace_value(planned_for_c.get("pace_fast_min_km"))
            if is_planned_interval
            else None
        )
        hr_target = planned_for_c.get("hr_min_bpm") if is_planned_interval else None
        breakdown = detect_intervals_from_laps(
            laps, pace_floor, hr_target, threshold_pace_min_km
        )
        if not breakdown:
            continue
        found.append(
            {
                "strava_id": c["strava_id"],
                "date": (c.get("start_date") or "")[:10],
                "name": c.get("name"),
                "planned_session_type": (
                    planned_for_c.get("session_type") if planned_for_c else None
                ),
                "breakdown": breakdown,
            }
        )
        if len(found) >= limit:
            break

    found.reverse()  # oldest first → reads as a progression timeline
    return found


def compare_to_recent_intervals(
    this_breakdown: dict | None,
    recent: list[dict],
    this_date: str | None = None,
) -> dict | None:
    """Build a progression view of avg rep metrics across recent interval sessions."""
    if not this_breakdown or not recent:
        return None
    this_agg = this_breakdown.get("aggregate") or {}

    rows = []
    for s in recent:
        agg = s["breakdown"]["aggregate"]
        rows.append(
            {
                "date": s["date"],
                "name": s.get("name"),
                "planned_session_type": s.get("planned_session_type"),
                "n_reps": agg.get("n_reps"),
                "avg_rep_pace_str": agg.get("avg_rep_pace_str"),
                "avg_rep_pace_min_km": agg.get("avg_rep_pace_min_km"),
                "avg_rep_hr": agg.get("avg_rep_hr"),
                "avg_rep_max_hr": agg.get("avg_rep_max_hr"),
                "avg_rep_cadence": agg.get("avg_rep_cadence"),
                "avg_rep_duration_s": agg.get("avg_rep_duration_s"),
            }
        )
    rows.append(
        {
            "date": this_date or "this",
            "name": "(this session)",
            "planned_session_type": None,
            "n_reps": this_agg.get("n_reps"),
            "avg_rep_pace_str": this_agg.get("avg_rep_pace_str"),
            "avg_rep_pace_min_km": this_agg.get("avg_rep_pace_min_km"),
            "avg_rep_hr": this_agg.get("avg_rep_hr"),
            "avg_rep_max_hr": this_agg.get("avg_rep_max_hr"),
            "avg_rep_cadence": this_agg.get("avg_rep_cadence"),
            "avg_rep_duration_s": this_agg.get("avg_rep_duration_s"),
        }
    )

    delta = None
    prev = recent[-1]["breakdown"]["aggregate"] if recent else None
    if prev and this_agg:
        def _delta(a, b):
            return None if (a is None or b is None) else round(a - b, 1)
        delta_pace_min = _delta(
            this_agg.get("avg_rep_pace_min_km"), prev.get("avg_rep_pace_min_km")
        )
        delta = {
            "vs_date": recent[-1]["date"],
            "delta_n_reps": _delta(this_agg.get("n_reps"), prev.get("n_reps")),
            "delta_avg_pace_sec_km": (
                round(delta_pace_min * 60.0, 1) if delta_pace_min is not None else None
            ),
            "delta_avg_hr": _delta(this_agg.get("avg_rep_hr"), prev.get("avg_rep_hr")),
            "delta_avg_max_hr": _delta(
                this_agg.get("avg_rep_max_hr"), prev.get("avg_rep_max_hr")
            ),
            "delta_avg_cadence": _delta(
                this_agg.get("avg_rep_cadence"), prev.get("avg_rep_cadence")
            ),
        }

    return {
        "n_recent": len(recent),
        "window_days": RECENT_INTERVALS_WINDOW_DAYS,
        "rows": rows,
        "delta_vs_previous": delta,
    }


def compare_reps_to_blocks(
    reps: list[dict], work_blocks: list[dict]
) -> list[dict]:
    """Annotate each rep with its target block (expanded by repeat_count) and verdicts."""
    expanded = []
    for wb in work_blocks:
        for _ in range(int(wb.get("repeat_count") or 1)):
            expanded.append(wb)

    annotated = []
    for i, rep in enumerate(reps):
        target = expanded[i] if i < len(expanded) else None
        entry = dict(rep)
        if target:
            hr_min = target.get("hr_min_bpm")
            hr_max = target.get("hr_max_bpm")
            # HR peak verdict: did the rep reach the target hr_min?
            if hr_min and rep.get("hr_max") is not None:
                entry["hr_peak_verdict"] = (
                    "reached" if rep["hr_max"] >= hr_min else "below"
                )
            entry["target_duration_s"] = int((target.get("duration_min") or 0) * 60)
            entry["duration_delta_s"] = (
                rep["duration_s"] - entry["target_duration_s"]
            )
            entry["target_hr_range"] = [hr_min, hr_max]
            entry["target_pace_range"] = [
                target.get("pace_fast_min_km"),
                target.get("pace_slow_min_km"),
            ]
        annotated.append(entry)
    return annotated


def compare_recoveries_to_blocks(
    recoveries: list[dict], recovery_blocks: list[dict]
) -> list[dict]:
    """Annotate each recovery gap with its target recovery block."""
    expanded = []
    for rb in recovery_blocks:
        for _ in range(int(rb.get("repeat_count") or 1)):
            expanded.append(rb)

    annotated = []
    for i, rec in enumerate(recoveries):
        target = expanded[i] if i < len(expanded) else None
        entry = dict(rec)
        if target:
            entry["target_duration_s"] = int((target.get("duration_min") or 0) * 60)
            entry["duration_delta_s"] = rec["duration_s"] - entry["target_duration_s"]
            entry["target_hr_ceiling"] = target.get("hr_max_bpm")
        annotated.append(entry)
    return annotated


def detect_prs(db_path: str, strava_id: int, athlete_id: int) -> list[dict]:
    """Compare this activity's best_efforts against all-time history.

    Returns a list of efforts ranked among the athlete's best at that distance
    when this run cracked the top-5; each entry is annotated with delta vs PR.
    """
    conn = _connect(db_path)
    try:
        my_efforts = conn.execute(
            "SELECT effort_name, distance, elapsed_time FROM best_efforts WHERE strava_id = ?",
            (strava_id,),
        ).fetchall()
        if not my_efforts:
            return []

        results = []
        for me in my_efforts:
            name = me["effort_name"]
            time_s = me["elapsed_time"]
            history = conn.execute(
                "SELECT elapsed_time FROM best_efforts WHERE athlete_id = ? AND effort_name = ? ORDER BY elapsed_time ASC",
                (athlete_id, name),
            ).fetchall()
            times = [h["elapsed_time"] for h in history]
            if not times:
                continue
            pr_s = times[0]
            rank = sum(1 for t in times if t < time_s) + 1
            if rank > 5:
                continue
            results.append({
                "effort_name": name,
                "distance_m": round(me["distance"], 0),
                "time_s": time_s,
                "time_str": _seconds_to_clock(time_s),
                "rank_all_time": rank,
                "all_time_pr_s": pr_s,
                "delta_vs_pr_s": time_s - pr_s,
                "is_pr_today": rank == 1,
                "total_attempts": len(times),
            })
        results.sort(key=lambda x: (not x["is_pr_today"], x["rank_all_time"]))
        return results
    finally:
        conn.close()


def _seconds_to_clock(s: int | float | None) -> str | None:
    if s is None:
        return None
    s = int(s)
    if s < 3600:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def find_similar_sessions(
    db_path: str, athlete_id: int, strava_id: int, sport_type: str,
    distance_m: float, days: int = 90,
) -> list[dict]:
    """Activities of the same sport with distance within ±20% in the last N days,
    excluding this one. Up to 10 most recent."""
    if not distance_m:
        return []
    low, high = distance_m * 0.80, distance_m * 1.20
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT strava_id, name, start_date, distance, moving_time,
                      average_speed, average_hr, total_elevation
               FROM activities
               WHERE athlete_id = ? AND sport_type = ?
                 AND strava_id != ?
                 AND distance BETWEEN ? AND ?
                 AND date(start_date) >= date('now', ?)
               ORDER BY start_date DESC
               LIMIT 10""",
            (athlete_id, sport_type, strava_id, low, high, f"-{days} days"),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def find_most_similar_session(
    db_path: str, athlete_id: int, this_activity: dict,
    days: int = 365, planned_session_type: str | None = None,
) -> dict | None:
    """Pick the single past activity most comparable to this one.

    Score = 0.6*|dist_diff_pct| + 0.3*|elev_diff_pct| + 0.1*(days_ago/365).
    A same-session_type bonus halves the score when planned context matches.
    Returns the full activity row or None if nothing matches.
    """
    distance_m = this_activity.get("distance") or 0
    if distance_m <= 0:
        return None
    sport_type = this_activity.get("sport_type") or ""
    this_elev = this_activity.get("total_elevation") or 0

    low, high = distance_m * 0.85, distance_m * 1.15
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT * FROM activities
               WHERE athlete_id = ? AND sport_type = ?
                 AND strava_id != ?
                 AND distance BETWEEN ? AND ?
                 AND date(start_date) >= date('now', ?)
               ORDER BY start_date DESC""",
            (athlete_id, sport_type, this_activity["strava_id"], low, high, f"-{days} days"),
        ).fetchall()
        candidates = [dict(r) for r in rows]
        if not candidates:
            return None

        today = datetime.now(timezone.utc)
        scored = []
        for c in candidates:
            c_dist = c.get("distance") or 0
            c_elev = c.get("total_elevation") or 0
            dist_diff = abs(c_dist - distance_m) / distance_m
            elev_diff = abs(c_elev - this_elev) / max(abs(this_elev), 30.0)
            try:
                age_days = (today - datetime.fromisoformat(
                    (c.get("start_date") or "").replace("Z", "+00:00")
                )).days
            except (ValueError, TypeError):
                age_days = 365
            score = 0.6 * dist_diff + 0.3 * elev_diff + 0.1 * (age_days / 365.0)

            if planned_session_type:
                try:
                    raw = json.loads(c.get("raw_json") or "{}")
                except (TypeError, ValueError):
                    raw = {}
                planned_for_c = find_planned_session(
                    db_path, athlete_id,
                    (c.get("start_date") or "")[:10],
                    sport_type,
                )
                if planned_for_c and planned_for_c.get("session_type") == planned_session_type:
                    score *= 0.5

            scored.append((score, c, dist_diff, elev_diff, age_days))

        scored.sort(key=lambda x: x[0])
        best = scored[0]
        result = dict(best[1])
        result["_match"] = {
            "score": round(best[0], 4),
            "dist_diff_pct": round(best[2] * 100, 1),
            "elev_diff_pct": round(best[3] * 100, 1),
            "age_days": best[4],
        }
        return result
    finally:
        conn.close()


def analyze_other_session(db_path: str, activity: dict,
                          threshold: float | None,
                          hr_max: float | None,
                          hr_rest: float | None) -> dict:
    """Build the full per-km analysis + summary for any past activity.

    Mirrors what main() does for the focal session, so the side-by-side
    can show splits/drift/shape for the comparable run too.
    """
    raw = {}
    try:
        raw = json.loads(activity.get("raw_json") or "{}")
    except (TypeError, ValueError):
        pass

    splits = raw.get("splits_metric") or []
    laps = raw.get("laps")
    analysis = analyze_splits(splits, laps, threshold, hr_max, hr_rest) if splits else {
        "per_km": [], "hr_drift": None, "pace_stats": None, "zone_distribution": None,
    }

    summary = {
        "strava_id": activity["strava_id"],
        "date": (activity.get("start_date") or "")[:10],
        "name": activity.get("name"),
        "sport_type": activity.get("sport_type"),
        "distance_km": round((activity.get("distance") or 0) / 1000.0, 2),
        "moving_time_s": activity.get("moving_time"),
        "duration_str": f"{(activity.get('moving_time') or 0) // 60}:{(activity.get('moving_time') or 0) % 60:02d}",
        "avg_pace": speed_to_pace_str(activity.get("average_speed")),
        "avg_hr": activity.get("average_hr"),
        "max_hr": activity.get("max_hr"),
        "total_elevation_m": activity.get("total_elevation"),
        "calories": raw.get("calories"),
    }
    return {
        "summary": summary,
        "splits": analysis["per_km"],
        "hr_drift": analysis["hr_drift"],
        "pace_stats": analysis["pace_stats"],
        "pace_shape": pace_shape(analysis["per_km"]),
        "zone_distribution": analysis["zone_distribution"],
    }


def build_side_by_side(this_summary: dict, this_splits: list[dict],
                        other: dict | None) -> dict | None:
    """Per-km side-by-side rows + headline deltas between two sessions."""
    if not other:
        return None
    other_splits = other.get("splits") or []
    rows = []
    n = max(len(this_splits), len(other_splits))
    for i in range(n):
        a = this_splits[i] if i < len(this_splits) else {}
        b = other_splits[i] if i < len(other_splits) else {}
        delta_pace = None
        if a.get("pace_min_km") is not None and b.get("pace_min_km") is not None:
            delta_pace = round((a["pace_min_km"] - b["pace_min_km"]) * 60.0, 1)
        delta_hr = None
        if a.get("avg_hr") is not None and b.get("avg_hr") is not None:
            delta_hr = round(a["avg_hr"] - b["avg_hr"], 1)
        rows.append({
            "km": a.get("km") or b.get("km") or i + 1,
            "this_pace": a.get("pace"),
            "other_pace": b.get("pace"),
            "delta_pace_sec_km": delta_pace,
            "this_hr": a.get("avg_hr"),
            "other_hr": b.get("avg_hr"),
            "delta_hr": delta_hr,
            "this_elev": a.get("elevation_m"),
            "other_elev": b.get("elevation_m"),
            "this_cad": a.get("cadence_spm"),
            "other_cad": b.get("cadence_spm"),
        })

    this_pace_f = parse_pace_value(this_summary.get("avg_pace"))
    other_pace_f = parse_pace_value(other["summary"].get("avg_pace"))
    headline = {
        "this_date": this_summary.get("date"),
        "other_date": other["summary"].get("date"),
        "match_score": (other.get("_match") or {}).get("score"),
        "match_dist_diff_pct": (other.get("_match") or {}).get("dist_diff_pct"),
        "match_elev_diff_pct": (other.get("_match") or {}).get("elev_diff_pct"),
        "match_age_days": (other.get("_match") or {}).get("age_days"),
        "delta_distance_km": round(
            (this_summary.get("distance_km") or 0) - (other["summary"].get("distance_km") or 0), 2
        ),
        "delta_duration_min": round(
            ((this_summary.get("moving_time_s") or 0) - (other["summary"].get("moving_time_s") or 0)) / 60.0, 1
        ),
        "delta_pace_sec_km": round((this_pace_f - other_pace_f) * 60.0, 1) if (this_pace_f and other_pace_f) else None,
        "delta_hr": round(
            (this_summary.get("avg_hr") or 0) - (other["summary"].get("avg_hr") or 0), 1
        ) if (this_summary.get("avg_hr") and other["summary"].get("avg_hr")) else None,
        "delta_elevation_m": round(
            (this_summary.get("total_elevation_m") or 0) - (other["summary"].get("total_elevation_m") or 0), 1
        ),
    }
    return {"headline": headline, "rows": rows}


def compare_to_similar(activity: dict, similar: list[dict]) -> dict | None:
    """Median pace/HR baseline of similar sessions and the delta of this run vs it."""
    if not similar:
        return None
    paces = sorted(
        speed_to_pace_float(s.get("average_speed")) for s in similar
        if s.get("average_speed")
    )
    hrs = sorted(s["average_hr"] for s in similar if s.get("average_hr"))
    distances = sorted((s.get("distance") or 0) / 1000.0 for s in similar)

    def median(vals):
        if not vals:
            return None
        n = len(vals)
        m = n // 2
        return vals[m] if n % 2 else (vals[m - 1] + vals[m]) / 2

    median_pace = median(paces)
    median_hr = median(hrs)
    median_distance = median(distances)
    this_pace = speed_to_pace_float(activity.get("average_speed"))
    this_hr = activity.get("average_hr")
    this_distance_km = (activity.get("distance") or 0) / 1000.0

    pace_rank = None
    if this_pace is not None and paces:
        all_paces = sorted(paces + [this_pace])
        pace_rank = all_paces.index(this_pace) + 1

    return {
        "n_similar": len(similar),
        "window_days": 90,
        "distance_band_km": [round(this_distance_km * 0.80, 2), round(this_distance_km * 1.20, 2)],
        "median_pace_min_km": round(median_pace, 3) if median_pace else None,
        "median_pace_str": speed_to_pace_str(1000.0 / (median_pace * 60.0)) if median_pace else None,
        "median_hr": round(median_hr, 1) if median_hr else None,
        "median_distance_km": round(median_distance, 2) if median_distance else None,
        "this_pace_min_km": this_pace,
        "this_hr": round(this_hr, 1) if this_hr else None,
        "delta_pace_min_km": round(this_pace - median_pace, 3) if (this_pace and median_pace) else None,
        "delta_pace_sec_km": round((this_pace - median_pace) * 60.0, 1) if (this_pace and median_pace) else None,
        "delta_hr": round(this_hr - median_hr, 1) if (this_hr and median_hr) else None,
        "rank_in_band": pace_rank,
        "rank_total": len(paces) + 1,
    }


def _minetti_factor(grade: float) -> float:
    """Minetti's energy-cost factor relative to flat. grade is decimal (0.05 = 5%)."""
    g = max(min(grade, 0.45), -0.45)
    cost = (155.4 * g**5 - 30.4 * g**4 - 43.3 * g**3
            + 46.3 * g**2 + 19.5 * g + 3.6)
    return cost / 3.6


def elevation_analysis(streams: dict | None, total_elevation_m: float | None) -> dict | None:
    """Compute elevation profile, grade buckets and Grade-Adjusted Pace from streams."""
    if not streams:
        if total_elevation_m:
            return {"total_gain_m": round(total_elevation_m, 1), "source": "summary_only"}
        return None

    grade = _series(streams, "grade_smooth")
    dist = _series(streams, "distance")
    time = _series(streams, "time")
    moving = _series(streams, "moving") or [True] * (len(time or []))
    altitude = _series(streams, "altitude")

    if not grade or not dist or not time or len(grade) != len(dist):
        return None

    n = len(grade)
    gain = loss = 0.0
    if altitude:
        for i in range(1, n):
            d = altitude[i] - altitude[i - 1]
            if d > 0:
                gain += d
            else:
                loss -= d

    buckets = {
        "uphill": {"time_s": 0, "distance_m": 0.0, "_pace_num": 0.0, "_pace_den": 0.0},
        "flat": {"time_s": 0, "distance_m": 0.0, "_pace_num": 0.0, "_pace_den": 0.0},
        "downhill": {"time_s": 0, "distance_m": 0.0, "_pace_num": 0.0, "_pace_den": 0.0},
    }
    flat_equivalent_m = 0.0
    moving_time_s = 0
    moving_distance_m = 0.0
    steepest_grade = 0.0
    steepest_at_km = None

    for i in range(1, n):
        if not moving[i]:
            continue
        dt = time[i] - time[i - 1]
        dd = dist[i] - dist[i - 1]
        if dt <= 0 or dd <= 0:
            continue
        g_pct = grade[i] or 0.0
        moving_time_s += dt
        moving_distance_m += dd

        if g_pct > 3:
            key = "uphill"
        elif g_pct < -3:
            key = "downhill"
        else:
            key = "flat"
        b = buckets[key]
        b["time_s"] += dt
        b["distance_m"] += dd
        b["_pace_num"] += dt
        b["_pace_den"] += dd

        flat_equivalent_m += dd * _minetti_factor(g_pct / 100.0)

        if abs(g_pct) > abs(steepest_grade):
            steepest_grade = g_pct
            steepest_at_km = round(dist[i] / 1000.0, 2)

    def bucket_pace(b):
        if b["_pace_den"] <= 0:
            return None
        speed = b["_pace_den"] / b["_pace_num"]
        return speed_to_pace_str(speed)

    out = {
        "total_gain_m": round(gain, 1),
        "total_loss_m": round(loss, 1),
        "buckets": {
            k: {
                "time_s": int(v["time_s"]),
                "distance_m": round(v["distance_m"], 0),
                "pct_distance": round(100.0 * v["distance_m"] / moving_distance_m, 1) if moving_distance_m else None,
                "avg_pace": bucket_pace(v),
            }
            for k, v in buckets.items()
        },
        "steepest_grade_pct": round(steepest_grade, 1),
        "steepest_at_km": steepest_at_km,
    }

    if flat_equivalent_m > 0 and moving_time_s > 0:
        gap_speed = flat_equivalent_m / moving_time_s
        actual_speed = moving_distance_m / moving_time_s
        out["gap_pace"] = speed_to_pace_str(gap_speed)
        out["gap_pace_min_km"] = speed_to_pace_float(gap_speed)
        out["actual_pace"] = speed_to_pace_str(actual_speed)
        out["actual_pace_min_km"] = speed_to_pace_float(actual_speed)
        if out["gap_pace_min_km"] and out["actual_pace_min_km"]:
            out["terrain_cost_sec_km"] = round(
                (out["actual_pace_min_km"] - out["gap_pace_min_km"]) * 60.0, 1
            )

    return out


def slowdown_analysis(per_km: list[dict], threshold_sec: float = 12.0) -> dict | None:
    """Identify splits that ran significantly slower than the median, and explain why.

    Reasons considered, in priority order:
    - uphill: split elevation_m gain > 5m
    - cardiac_drift: HR more than 5 bpm above the run's median HR
    - cadence_drop: cadence more than 4 spm below the run's median cadence
    - intrinsic: nothing external explains the drop
    """
    paces = [k.get("pace_min_km") for k in per_km if k.get("pace_min_km")]
    if len(paces) < 3:
        return None

    sorted_paces = sorted(paces)
    median_pace = sorted_paces[len(sorted_paces) // 2]
    threshold_min = threshold_sec / 60.0

    hrs = [k.get("avg_hr") for k in per_km if k.get("avg_hr")]
    median_hr = sorted(hrs)[len(hrs) // 2] if hrs else None

    cads = [k.get("cadence_spm") for k in per_km if k.get("cadence_spm")]
    median_cad = sorted(cads)[len(cads) // 2] if cads else None

    worst = []
    for k in per_km:
        pace = k.get("pace_min_km")
        if pace is None:
            continue
        delta = pace - median_pace
        if delta < threshold_min:
            continue

        reasons = []
        elev = k.get("elevation_m") or 0
        hr = k.get("avg_hr")
        cad = k.get("cadence_spm")

        if elev > 5:
            reasons.append({"type": "uphill", "detail": f"+{round(elev,1)}m elevation"})
        if median_hr is not None and hr is not None and hr - median_hr > 5:
            reasons.append({"type": "cardiac_drift", "detail": f"HR +{round(hr-median_hr,1)} vs median"})
        if median_cad is not None and cad is not None and median_cad - cad > 4:
            reasons.append({"type": "cadence_drop", "detail": f"cadence -{round(median_cad-cad,1)} spm vs median"})
        if not reasons:
            reasons.append({"type": "intrinsic", "detail": "no external factor — likely effort/willpower"})

        worst.append({
            "km": k.get("km"),
            "pace": k.get("pace"),
            "pace_min_km": pace,
            "delta_sec_vs_median": round(delta * 60.0, 1),
            "avg_hr": hr,
            "elevation_m": elev,
            "cadence_spm": cad,
            "reasons": reasons,
        })

    worst.sort(key=lambda x: -x["delta_sec_vs_median"])
    return {
        "median_pace_min_km": round(median_pace, 3),
        "median_hr": round(median_hr, 1) if median_hr else None,
        "median_cadence_spm": round(median_cad, 1) if median_cad else None,
        "threshold_sec_vs_median": threshold_sec,
        "slow_splits": worst,
        "n_slow": len(worst),
    }


def pace_shape(per_km: list[dict]) -> dict | None:
    """Classify the pace pattern across the run: progressive / fade / u_shape / even."""
    paces = [k.get("pace_min_km") for k in per_km if k.get("pace_min_km")]
    if len(paces) < 3:
        return None
    n = len(paces)
    third = max(1, n // 3)
    first = sum(paces[:third]) / third
    last = sum(paces[-third:]) / third
    middle = sum(paces[third:n - third]) / max(1, n - 2 * third) if n > 2 * third else (first + last) / 2

    delta_first_last = last - first
    threshold = 0.15

    if delta_first_last < -threshold:
        shape = "progressive"
    elif delta_first_last > threshold:
        shape = "fade"
    elif middle > first + threshold and middle > last + threshold:
        shape = "u_shape"
    elif middle < first - threshold and middle < last - threshold:
        shape = "surge"
    else:
        shape = "even"

    return {
        "shape": shape,
        "first_third_pace_min_km": round(first, 3),
        "middle_pace_min_km": round(middle, 3),
        "last_third_pace_min_km": round(last, 3),
        "first_to_last_delta_sec_km": round(delta_first_last * 60.0, 1),
    }


def build_narrative(
    summary: dict,
    hr_drift: dict | None,
    pace_stats: dict | None,
    plan_comparison: dict | None,
    pr_summary: list[dict],
    similar_summary: dict | None,
    elevation: dict | None,
    slowdown: dict | None,
    shape: dict | None,
    interval_breakdown: dict | None,
    side_by_side: dict | None = None,
    recent_intervals: dict | None = None,
) -> list[str]:
    """Convert structured analysis into natural-language English sentences.

    Output is consumed by the assistant, which translates / paraphrases
    into the user's preferred conversation language at presentation time.
    """
    n: list[str] = []

    dist_km = summary.get("distance_km")
    pace = summary.get("avg_pace")
    avg_hr = summary.get("avg_hr")
    n.append(
        f"Session: {dist_km} km at {pace}/km"
        + (f", avg HR {round(avg_hr)} bpm." if avg_hr else ".")
    )

    if shape:
        s = shape["shape"]
        delta = shape["first_to_last_delta_sec_km"]
        if s == "progressive":
            n.append(f"Pace pattern: progressive — last third {abs(delta):.0f} s/km faster than the first.")
        elif s == "fade":
            n.append(f"Pace pattern: clear fade — last third {delta:.0f} s/km slower than the first.")
        elif s == "u_shape":
            n.append("Pace pattern: U-shape — middle of the session was the slowest stretch.")
        elif s == "surge":
            n.append("Pace pattern: middle surge — the centre was the fastest stretch.")
        else:
            n.append("Pace pattern: even across the session.")

    if hr_drift and hr_drift.get("drift_pct") is not None:
        d = hr_drift["drift_pct"]
        if d > 5:
            n.append(f"High cardiac drift: +{d}% HR between halves — sign of aerobic fatigue.")
        elif d > 2:
            n.append(f"Moderate cardiac drift: +{d}% (acceptable for long runs or hot conditions).")
        else:
            n.append(f"Cardiac drift contained (+{d}%) — solid aerobic base for this intensity.")

    if elevation and elevation.get("buckets"):
        b = elevation["buckets"]
        gain = elevation.get("total_gain_m")
        if elevation.get("terrain_cost_sec_km") is not None and abs(elevation["terrain_cost_sec_km"]) > 5:
            cost = elevation["terrain_cost_sec_km"]
            if cost > 0:
                n.append(
                    f"Hilly terrain ({gain} m gain): actual pace {elevation.get('actual_pace')}/km "
                    f"equals {elevation.get('gap_pace')}/km on flat (GAP, {cost:.0f} s/km cost)."
                )
            else:
                n.append(
                    f"Net descending terrain: GAP {elevation.get('gap_pace')}/km vs actual {elevation.get('actual_pace')}/km."
                )
        if b["uphill"]["pct_distance"] and b["uphill"]["pct_distance"] > 15:
            n.append(
                f"{b['uphill']['pct_distance']}% of the route was uphill (>3% grade), avg pace {b['uphill']['avg_pace']}/km."
            )

    if side_by_side and side_by_side.get("headline"):
        h = side_by_side["headline"]
        age = h.get("match_age_days")
        delta_p = h.get("delta_pace_sec_km")
        delta_hr = h.get("delta_hr")
        delta_elev = h.get("delta_elevation_m")
        line = f"Closest match: {h.get('other_date')} ({age} d ago, {h.get('match_dist_diff_pct')}% distance diff)"
        if delta_p is not None:
            if delta_p < -5:
                line += f" — today {abs(delta_p):.0f} s/km faster"
            elif delta_p > 5:
                line += f" — today {delta_p:.0f} s/km slower"
            else:
                line += " — pace within ±5 s/km"
        if delta_hr is not None:
            line += f", HR {delta_hr:+.0f} bpm"
        if delta_elev is not None and abs(delta_elev) > 20:
            line += f", elevation {delta_elev:+.0f} m"
        line += "."
        n.append(line)

    if similar_summary and similar_summary.get("delta_pace_sec_km") is not None:
        delta_p = similar_summary["delta_pace_sec_km"]
        delta_hr = similar_summary.get("delta_hr")
        n_sim = similar_summary["n_similar"]
        if delta_p < -10:
            line = f"Faster than your median of the last {n_sim} similar sessions ({-delta_p:.0f} s/km faster)"
        elif delta_p > 10:
            line = f"Slower than your median of the last {n_sim} similar sessions ({delta_p:.0f} s/km slower)"
        else:
            line = f"In line with your median of the last {n_sim} similar sessions (±10 s/km)"
        if delta_hr is not None:
            if delta_hr > 3 and delta_p < -10:
                line += f", but at higher HR (+{delta_hr:.0f} bpm) — paid for the speed with cardiac effort."
            elif delta_hr > 3:
                line += f", at higher HR (+{delta_hr:.0f} bpm) — more cardiac stress for equal or worse pace."
            elif delta_hr < -3 and delta_p < -10:
                line += f", and at lower HR ({delta_hr:.0f} bpm) — clear aerobic progress."
            elif delta_hr < -3:
                line += f", at lower HR ({delta_hr:.0f} bpm) — easier session than usual."
            else:
                line += f", HR similar ({delta_hr:+.0f} bpm)."
        else:
            line += "."
        n.append(line)

    if pr_summary:
        prs_today = [p for p in pr_summary if p.get("is_pr_today")]
        top5 = [p for p in pr_summary if not p.get("is_pr_today") and p.get("rank_all_time", 99) <= 5]
        if prs_today:
            names = ", ".join(p["effort_name"] for p in prs_today)
            n.append(f"All-time PR today on: {names}.")
        if top5:
            parts = [f"{p['effort_name']} (rank {p['rank_all_time']})" for p in top5]
            n.append(f"All-time top-5 also on: {', '.join(parts)}.")

    if slowdown and slowdown.get("slow_splits"):
        worst = slowdown["slow_splits"][:2]
        for w in worst:
            reasons = ", ".join(r["type"].replace("_", " ") for r in w["reasons"])
            n.append(
                f"Km {w['km']}: {w['delta_sec_vs_median']:.0f} s/km below median — cause: {reasons}."
            )

    if interval_breakdown and interval_breakdown.get("reps"):
        reps = interval_breakdown["reps"]
        reached = sum(1 for r in reps if r.get("hr_peak_verdict") == "reached")
        agg = interval_breakdown.get("aggregate") or {}
        if interval_breakdown.get("source") == "laps":
            line = (
                f"Detected {len(reps)} reps from watch laps "
                f"(avg pace {agg.get('avg_rep_pace_str')}/km, avg HR {agg.get('avg_rep_hr')} bpm)."
            )
            if agg.get("target_hr_min"):
                line += f" {reached}/{len(reps)} reps reached the target peak HR ({agg['target_hr_min']} bpm)."
            n.append(line)
        else:
            n.append(f"Intervals: {reached}/{len(reps)} reached the target peak HR.")

    if recent_intervals and recent_intervals.get("delta_vs_previous"):
        d = recent_intervals["delta_vs_previous"]
        prev_date = d.get("vs_date")
        bits = []
        dp = d.get("delta_avg_pace_sec_km")
        if dp is not None:
            if dp < -2:
                bits.append(f"avg rep pace {abs(dp):.0f} s/km faster")
            elif dp > 2:
                bits.append(f"avg rep pace {dp:.0f} s/km slower")
        dh = d.get("delta_avg_hr")
        if dh is not None:
            if dh < -1:
                bits.append(f"avg rep HR {dh:+.0f} bpm (lower)")
            elif dh > 1:
                bits.append(f"avg rep HR {dh:+.0f} bpm (higher)")
        dn = d.get("delta_n_reps")
        if dn:
            bits.append(f"{dn:+d} reps")
        dc = d.get("delta_avg_cadence")
        if dc is not None and abs(dc) >= 1:
            bits.append(f"cadence {dc:+.0f} spm")
        if bits:
            n.append(
                f"Vs last interval session ({prev_date}): " + ", ".join(bits) + "."
            )

    if plan_comparison:
        v = plan_comparison.get("hr_verdict")
        if v == "inside":
            n.append("HR average inside the planned range — session executed as prescribed.")
        elif v == "above":
            n.append("HR average above the planned range — session ran harder than planned.")
        elif v == "below":
            n.append("HR average below the planned range — session ran softer than planned.")

    return n


def build_plan_comparison(planned: dict, activity: dict) -> dict:
    """Compare actual activity metrics against the planned session."""
    actual_duration_min = (activity.get("moving_time") or 0) / 60.0
    actual_distance_km = (activity.get("distance") or 0) / 1000.0
    actual_hr = activity.get("average_hr")
    actual_pace = speed_to_pace_float(activity.get("average_speed"))

    pace_fast = parse_pace_value(planned.get("pace_fast_min_km"))
    pace_slow = parse_pace_value(planned.get("pace_slow_min_km"))

    return {
        "planned_duration_min": planned.get("duration_min"),
        "actual_duration_min": round(actual_duration_min, 1),
        "duration_delta_min": round(actual_duration_min - (planned.get("duration_min") or 0), 1),
        "planned_distance_km": planned.get("distance_km"),
        "actual_distance_km": round(actual_distance_km, 2),
        "distance_delta_km": round(actual_distance_km - (planned.get("distance_km") or 0), 2),
        "planned_hr_range": [planned.get("hr_min_bpm"), planned.get("hr_max_bpm")],
        "actual_hr_avg": round(actual_hr, 1) if actual_hr else None,
        "hr_verdict": avg_vs_range(
            actual_hr,
            planned.get("hr_min_bpm") or 0,
            planned.get("hr_max_bpm") or 9999,
        ),
        "planned_pace_range": [planned.get("pace_fast_min_km"), planned.get("pace_slow_min_km")],
        "actual_pace_min_km": actual_pace,
        "pace_verdict": avg_vs_range(
            actual_pace,
            pace_fast or 0,
            pace_slow or 99,
        ),
        "session_type": planned.get("session_type"),
        "phase": planned.get("phase"),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Deep analysis of a single session")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--strava-id", type=int, default=None)
    parser.add_argument("--sync", action="store_true", help="Sync from Strava before analysis")
    parser.add_argument("--similar-window", type=int, default=90, help="Days back to look for similar sessions")
    args = parser.parse_args()

    if not args.date and not args.strava_id:
        args.date = date.today().isoformat()

    db_path = get_default_db_path()
    token = load_token(db_path)
    if not token:
        output_error("No token. Run strava-setup first.")
    athlete_id = token["athlete_id"]

    if args.sync:
        try:
            client = StravaClient(db_path)
            sync_summary(client, db_path, days=14)
        except Exception:
            pass

    activity = find_activity(db_path, args.strava_id, args.date)
    if not activity:
        output_error(f"No activity found for {'strava_id=' + str(args.strava_id) if args.strava_id else 'date=' + str(args.date)}")

    # Parse raw_json for splits and laps
    raw = {}
    try:
        raw = json.loads(activity.get("raw_json") or "{}")
    except (TypeError, ValueError):
        pass

    splits = raw.get("splits_metric")
    if not splits:
        output_error("splits_metric not available. Sync details first: strava-sync --level details --limit 5")

    laps = raw.get("laps")

    # Get snapshot params for zone mapping
    snap = get_snapshot_params(db_path, athlete_id)
    threshold = snap.get("threshold_pace")
    hr_max = snap.get("hr_max")
    hr_rest = snap.get("hr_rest")

    # Run analysis
    analysis = analyze_splits(splits, laps, threshold, hr_max, hr_rest)

    # Build summary
    activity_date = activity.get("start_date", "")[:10]
    summary = {
        "strava_id": activity["strava_id"],
        "date": activity_date,
        "name": activity.get("name"),
        "sport_type": activity.get("sport_type"),
        "distance_km": round((activity.get("distance") or 0) / 1000.0, 2),
        "moving_time_s": activity.get("moving_time"),
        "duration_str": f"{(activity.get('moving_time') or 0) // 60}:{(activity.get('moving_time') or 0) % 60:02d}",
        "avg_pace": speed_to_pace_str(activity.get("average_speed")),
        "avg_hr": activity.get("average_hr"),
        "max_hr": activity.get("max_hr"),
        "total_elevation_m": activity.get("total_elevation"),
        "calories": raw.get("calories"),
        "device": raw.get("device_name"),
    }

    # Plan comparison
    plan_comparison = None
    interval_breakdown = None
    planned = None
    if activity_date:
        planned = find_planned_session(db_path, athlete_id, activity_date, activity.get("sport_type") or "")
        if planned:
            plan_comparison = build_plan_comparison(planned, activity)

    # Streams (used by elevation and as a fallback for interval detection)
    streams = load_streams(db_path, activity["strava_id"])

    # ------------------------------------------------------------------
    # Interval breakdown
    #
    # Order of preference:
    # 1. Watch laps (authoritative — the athlete pressed the lap button).
    #    Triggers when the lap pace pattern is clearly bimodal, even if
    #    no planned session exists.
    # 2. Streams + planned blocks (legacy path for plans authored with
    #    structured work/recovery blocks).
    # 3. Error message asking to sync streams.
    # ------------------------------------------------------------------
    laps_for_intervals = load_laps(db_path, activity["strava_id"]) or laps or []
    is_planned_interval_session = bool(
        planned and planned.get("session_type") in INTERVAL_SESSION_TYPES
    )
    planned_pace_floor = (
        parse_pace_value(planned.get("pace_fast_min_km"))
        if is_planned_interval_session
        else None
    )
    planned_hr_target = (
        planned.get("hr_min_bpm") if is_planned_interval_session else None
    )

    interval_breakdown = detect_intervals_from_laps(
        laps_for_intervals, planned_pace_floor, planned_hr_target,
        threshold_pace_min_km=threshold,
    )

    if not interval_breakdown and planned and planned.get("session_type") in INTERVAL_SESSION_TYPES:
        blocks = get_planned_blocks(db_path, planned["id"])
        work_blocks = [b for b in blocks if b.get("block_type") == "work"]
        recovery_blocks = [b for b in blocks if b.get("block_type") == "recovery"]
        if work_blocks:
            if streams:
                reps = detect_intervals(streams, work_blocks)
                recoveries = detect_recoveries(streams, reps)
                interval_breakdown = {
                    "source": "streams",
                    "expected_reps": sum(
                        int(wb.get("repeat_count") or 1) for wb in work_blocks
                    ),
                    "detected_reps": len(reps),
                    "reps": compare_reps_to_blocks(reps, work_blocks),
                    "recoveries": compare_recoveries_to_blocks(
                        recoveries, recovery_blocks
                    ),
                }
            else:
                interval_breakdown = {
                    "source": "streams",
                    "error": "streams not cached — run strava-sync --level streams first",
                    "expected_reps": sum(
                        int(wb.get("repeat_count") or 1) for wb in work_blocks
                    ),
                }

    # Cross-session comparison against the user's recent interval sessions.
    # Only meaningful when we have an aggregate (lap-based detection).
    recent_intervals_comparison = None
    if interval_breakdown and interval_breakdown.get("aggregate"):
        recent = find_recent_interval_sessions(
            db_path,
            athlete_id,
            activity["strava_id"],
            activity.get("sport_type") or "",
            threshold_pace_min_km=threshold,
        )
        recent_intervals_comparison = compare_to_recent_intervals(
            interval_breakdown, recent, this_date=activity_date
        )

    # PR detection
    pr_summary = detect_prs(db_path, activity["strava_id"], athlete_id)

    # Similar sessions baseline (median of N comparable runs)
    similar = find_similar_sessions(
        db_path, athlete_id, activity["strava_id"],
        activity.get("sport_type") or "",
        activity.get("distance") or 0,
        days=args.similar_window,
    )
    similar_summary = compare_to_similar(activity, similar)

    # Single most-comparable past session (for side-by-side)
    planned_type = planned.get("session_type") if planned else None
    most_similar_activity = find_most_similar_session(
        db_path, athlete_id, activity,
        days=args.similar_window,
        planned_session_type=planned_type,
    )
    most_similar = None
    side_by_side = None
    if most_similar_activity:
        most_similar = analyze_other_session(
            db_path, most_similar_activity, threshold, hr_max, hr_rest,
        )
        most_similar["_match"] = most_similar_activity.get("_match")
        if not most_similar["splits"]:
            most_similar["details_not_synced"] = True
        side_by_side = build_side_by_side(summary, analysis["per_km"], most_similar)

    # Elevation analysis (uses streams)
    elevation = elevation_analysis(streams, activity.get("total_elevation"))

    # Slowdown analysis (uses per-km splits + cadence)
    slowdown = slowdown_analysis(analysis["per_km"])

    # Pace shape
    shape = pace_shape(analysis["per_km"])

    # Auto-narrative
    narrative = build_narrative(
        summary=summary,
        hr_drift=analysis["hr_drift"],
        pace_stats=analysis["pace_stats"],
        plan_comparison=plan_comparison,
        pr_summary=pr_summary,
        similar_summary=similar_summary,
        elevation=elevation,
        slowdown=slowdown,
        shape=shape,
        interval_breakdown=interval_breakdown,
        side_by_side=side_by_side,
        recent_intervals=recent_intervals_comparison,
    )

    output_json({
        "summary": summary,
        "narrative": narrative,
        "splits": analysis["per_km"],
        "hr_drift": analysis["hr_drift"],
        "pace_stats": analysis["pace_stats"],
        "pace_shape": shape,
        "zone_distribution": analysis["zone_distribution"],
        "plan_comparison": plan_comparison,
        "interval_breakdown": interval_breakdown,
        "recent_intervals": recent_intervals_comparison,
        "elevation": elevation,
        "slowdown": slowdown,
        "similar_sessions": similar_summary,
        "most_similar": most_similar,
        "side_by_side": side_by_side,
        "prs": pr_summary,
    })


if __name__ == "__main__":
    main()
