"""Athlete snapshot management: compute, ensure freshness, and read.

This module centralises the snapshot lifecycle so that every skill script
can call ``ensure_snapshot()`` and get a guaranteed-populated dict of
physiological parameters without worrying about whether the snapshot exists,
is stale, or is missing required fields.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from strava.analytics import (
    acute_chronic_ratio,
    age_from_birthdate,
    banister_trimp,
    day_key,
    estimate_hr_max,
    estimate_hr_rest,
    estimate_lthr,
    monotony as calc_monotony,
    pace_min_per_km,
    pmc_series,
    strain as calc_strain,
    vdot_from_5k,
    vdot_to_threshold_pace,
)
from strava.db import (
    get_activities_range,
    get_best_efforts_pr,
    get_latest_snapshot,
    init_db,
    load_token,
    load_user_profile,
    upsert_athlete_snapshot,
)


# ---------------------------------------------------------------------------
# Core computation (extracted from full_refresh_snapshot.py)
# ---------------------------------------------------------------------------

def _compute_daily_loads(
    activities: list[dict], hr_max: float, hr_rest: float, gender: str,
) -> dict[str, float]:
    day_loads: dict[str, float] = {}
    for a in activities:
        avg_hr = a.get("average_hr")
        moving = a.get("moving_time")
        start = a.get("start_date")
        if not avg_hr or not moving or not start:
            continue
        trimp = banister_trimp(moving / 60.0, avg_hr, hr_rest, hr_max, gender)
        dk = day_key(start)
        day_loads[dk] = day_loads.get(dk, 0.0) + trimp
    return day_loads


def _compute_pmc(day_loads: dict[str, float]):
    if not day_loads:
        return None, None, None
    sorted_loads = sorted(day_loads.items())
    series = pmc_series(sorted_loads)
    if not series:
        return None, None, None
    last = series[-1]
    return last["ctl"], last["atl"], last["tsb"]


def _compute_acwr_monotony_strain(day_loads: dict[str, float]):
    if not day_loads:
        return None, None, None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = min(day_loads.keys())
    cur = datetime.strptime(start, "%Y-%m-%d")
    end = datetime.strptime(today, "%Y-%m-%d")
    loads_list: list[float] = []
    while cur <= end:
        k = cur.strftime("%Y-%m-%d")
        loads_list.append(day_loads.get(k, 0.0))
        cur += timedelta(days=1)

    acwr = acute_chronic_ratio(loads_list) if len(loads_list) >= 28 else None
    mono = calc_monotony(loads_list) if len(loads_list) >= 7 else None
    st = calc_strain(loads_list) if len(loads_list) >= 7 else None
    return acwr, mono, st


def _compute_vdot_and_threshold(best_efforts: list[dict]):
    effort_5k = None
    for e in best_efforts:
        name = (e.get("effort_name") or "").lower()
        if "5k" in name or name == "5k":
            effort_5k = e
            break
    if not effort_5k:
        return None, None
    time_s = effort_5k.get("pr_time")
    if not time_s:
        return None, None
    vdot = vdot_from_5k(time_s)
    t_pace = vdot_to_threshold_pace(vdot)
    return vdot, t_pace


def _collect_observed_hr_peaks(activities: list[dict]) -> list[float]:
    """Collect all max_hr values from activities for use in estimate_hr_max."""
    peaks = []
    for a in activities:
        mhr = a.get("max_hr")
        if mhr and mhr > 0:
            peaks.append(mhr)
    return peaks


def _compute_avg_cadence(activities: list[dict], days: int = 60) -> float | None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cadences: list[float] = []
    for a in activities:
        sport = (a.get("sport_type") or "").lower()
        if "run" not in sport:
            continue
        start = a.get("start_date") or ""
        if start < cutoff:
            continue
        raw = a.get("raw_json")
        if not raw:
            continue
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        cad = data.get("average_cadence")
        if cad and cad > 0:
            cadences.append(cad * 2)  # Strava reports half-cadence for running
    if not cadences:
        return None
    return round(sum(cadences) / len(cadences), 1)


def _compute_avg_decoupling(
    activities: list[dict], hr_max: float, days: int = 60,
) -> float | None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    decouplings: list[float] = []
    for a in activities:
        sport = (a.get("sport_type") or "").lower()
        if "run" not in sport:
            continue
        start = a.get("start_date") or ""
        if start < cutoff:
            continue
        moving = a.get("moving_time") or 0
        avg_hr = a.get("average_hr") or 0
        distance = a.get("distance") or 0
        if moving < 2400 or not avg_hr or not distance:
            continue
        if hr_max and avg_hr > hr_max * 0.85:
            continue
        raw = a.get("raw_json")
        if not raw:
            continue
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        splits = data.get("splits_metric")
        if not splits or len(splits) < 4:
            continue
        half = len(splits) // 2
        first_half = splits[:half]
        second_half = splits[half:]

        def _half_ratio(sp):
            paces, hrs = [], []
            for s in sp:
                d = s.get("distance", 0)
                t = s.get("moving_time", 0)
                h = s.get("average_heartrate", 0)
                if d > 0 and t > 0 and h > 0:
                    p = pace_min_per_km(d, t)
                    if p:
                        paces.append(p)
                        hrs.append(h)
            if not paces:
                return None
            return (sum(paces) / len(paces)) / (sum(hrs) / len(hrs))

        r1 = _half_ratio(first_half)
        r2 = _half_ratio(second_half)
        if r1 and r2 and r1 > 0:
            dec = (r1 - r2) / r1 * 100.0
            decouplings.append(dec)

    if not decouplings:
        return None
    return round(sum(decouplings) / len(decouplings), 2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_full_snapshot(db_path: str, *, days: int = 90) -> dict:
    """Recompute all variable physiological metrics from the activity DB.

    Returns a dict of metric_name -> value (only non-None metrics included).
    Does NOT write to the database — the caller decides when to persist.
    """
    token = load_token(db_path)
    if not token:
        return {}
    athlete_id = token["athlete_id"]

    profile = load_user_profile(db_path, athlete_id)
    gender = (profile or {}).get("gender", "M")
    weight_kg = (profile or {}).get("weight_kg")
    birth_date = (profile or {}).get("birth_date")
    age = age_from_birthdate(birth_date)

    activities = get_activities_range(db_path, days=days)
    if not activities:
        return {}

    best_efforts = get_best_efforts_pr(db_path, athlete_id)

    # HR max: evidence-based estimation (Tanaka/Gulati + observed peaks)
    all_activities = get_activities_range(db_path, days=365)
    observed_peaks = _collect_observed_hr_peaks(all_activities)
    hr_max = estimate_hr_max(age, gender, observed_peaks)

    # HR rest: age-based default for recreational endurance athlete
    hr_rest = estimate_hr_rest(age=age)

    # VDOT + threshold pace
    vdot, threshold_pace = _compute_vdot_and_threshold(best_efforts)

    # LTHR: from best 20-min effort or %HR max
    lthr = estimate_lthr(hr_max, hr_rest)

    # Daily loads + PMC
    day_loads = _compute_daily_loads(all_activities, hr_max, hr_rest, gender)
    ctl, atl, tsb = _compute_pmc(day_loads)

    # ACWR, monotony, strain
    acwr, mono, st = _compute_acwr_monotony_strain(day_loads)

    # Cadence + decoupling
    avg_cadence = _compute_avg_cadence(activities, days=days)
    avg_decoupling = _compute_avg_decoupling(activities, hr_max, days=days)

    metrics: dict = {}
    metrics["hr_max_bpm"] = hr_max
    metrics["hr_rest_bpm"] = hr_rest
    metrics["lthr_bpm"] = lthr
    if vdot:
        metrics["vdot"] = vdot
    if threshold_pace:
        metrics["threshold_pace_min_km"] = threshold_pace
    if weight_kg:
        metrics["weight_kg"] = weight_kg
    if ctl is not None:
        metrics["ctl"] = ctl
    if atl is not None:
        metrics["atl"] = atl
    if tsb is not None:
        metrics["tsb"] = tsb
    if acwr is not None:
        metrics["acwr"] = acwr
    if mono is not None:
        metrics["monotony"] = mono
    if st is not None:
        metrics["strain"] = st
    if avg_cadence is not None:
        metrics["avg_cadence_spm"] = avg_cadence
    if avg_decoupling is not None:
        metrics["avg_decoupling_pct"] = avg_decoupling

    return metrics


def ensure_snapshot(
    db_path: str,
    *,
    max_age_hours: float = 12,
    required_fields: list[str] | None = None,
) -> dict:
    """Return a snapshot guaranteed to be recent and to contain *required_fields*.

    Logic:
    1. Read the latest snapshot from the DB.
    2. If it doesn't exist, is older than *max_age_hours*, or is missing any
       of *required_fields* → run ``compute_full_snapshot`` and persist.
    3. Return the (possibly freshly-computed) snapshot as a plain dict.

    The returned dict always has every snapshot column as a key (some may be
    ``None`` if the data isn't available).
    """
    init_db(db_path)

    token = load_token(db_path)
    if not token:
        return {}
    athlete_id = token["athlete_id"]

    snap = get_latest_snapshot(db_path, athlete_id)

    needs_refresh = False
    if snap is None:
        needs_refresh = True
    else:
        # Check age
        captured = snap.get("captured_at", "")
        if captured:
            try:
                dt = datetime.fromisoformat(captured).replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                if age_h > max_age_hours:
                    needs_refresh = True
            except (ValueError, TypeError):
                needs_refresh = True
        else:
            needs_refresh = True

        # Check required fields
        if not needs_refresh and required_fields:
            for field in required_fields:
                if snap.get(field) is None:
                    needs_refresh = True
                    break

    if needs_refresh:
        metrics = compute_full_snapshot(db_path, days=90)
        if metrics:
            upsert_athlete_snapshot(db_path, athlete_id, "auto-ensure", metrics)
            snap = get_latest_snapshot(db_path, athlete_id)

    if snap is None:
        return {}

    # Return a clean dict without internal DB fields
    return {k: snap[k] for k in snap if k not in ("id", "athlete_id")}
