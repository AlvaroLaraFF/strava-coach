"""Sports-science formulas used by the analytics skills.

Pure functions only — no I/O. All inputs are plain Python data structures
so the same primitives can be reused from any script or skill.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Iterable


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def day_key(s: str) -> str:
    return parse_iso(s).strftime("%Y-%m-%d")


def iso_week(s: str) -> str:
    dt = parse_iso(s)
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


# ---------------------------------------------------------------------------
# Heart-rate based load (TRIMP / Relative Effort proxy)
# ---------------------------------------------------------------------------

def hr_reserve_fraction(avg_hr: float, hr_rest: float, hr_max: float) -> float:
    if hr_max <= hr_rest:
        return 0.0
    return max(0.0, min(1.0, (avg_hr - hr_rest) / (hr_max - hr_rest)))


def banister_trimp(
    duration_min: float,
    avg_hr: float,
    hr_rest: float,
    hr_max: float,
    sex: str = "M",
) -> float:
    """Banister TRIMP — single-activity training impulse from average HR."""
    if not duration_min or not avg_hr:
        return 0.0
    hrr = hr_reserve_fraction(avg_hr, hr_rest, hr_max)
    k = 1.92 if sex.upper().startswith("M") else 1.67
    return duration_min * hrr * 0.64 * math.exp(k * hrr)


def relative_effort_from_zones(time_in_zone_s: list[float]) -> float:
    """Strava-style Relative Effort weighted by HR zone."""
    weights = [10, 20, 30, 50, 100]
    score = 0.0
    for i, t in enumerate(time_in_zone_s[:5]):
        score += (t / 60.0) * weights[i]
    return round(score / 10.0, 1)


# ---------------------------------------------------------------------------
# Power-based load (cycling — TSS / NP / IF)
# ---------------------------------------------------------------------------

def normalized_power(watts_stream: list[float]) -> float:
    """30-second rolling average, ^4, mean, ^(1/4)."""
    if not watts_stream:
        return 0.0
    window = 30
    rolling: list[float] = []
    s = 0.0
    q: list[float] = []
    for w in watts_stream:
        w = w or 0.0
        q.append(w)
        s += w
        if len(q) > window:
            s -= q.pop(0)
        if len(q) == window:
            rolling.append(s / window)
    if not rolling:
        return 0.0
    mean4 = sum(r ** 4 for r in rolling) / len(rolling)
    return mean4 ** 0.25


def intensity_factor(np_value: float, ftp: float) -> float:
    if not ftp:
        return 0.0
    return np_value / ftp


def tss(duration_s: float, np_value: float, intensity: float, ftp: float) -> float:
    if not ftp:
        return 0.0
    return (duration_s * np_value * intensity) / (ftp * 3600.0) * 100.0


def variability_index(np_value: float, avg_power: float) -> float:
    if not avg_power:
        return 0.0
    return np_value / avg_power


def efficiency_factor(np_or_ngp: float, avg_hr: float) -> float:
    if not avg_hr:
        return 0.0
    return np_or_ngp / avg_hr


# ---------------------------------------------------------------------------
# Running pace
# ---------------------------------------------------------------------------

def pace_min_per_km(distance_m: float, moving_time_s: float) -> float | None:
    if not distance_m or not moving_time_s:
        return None
    return (moving_time_s / 60.0) / (distance_m / 1000.0)


def speed_to_pace_min_km(speed_m_s: float) -> float | None:
    if not speed_m_s:
        return None
    return (1000.0 / speed_m_s) / 60.0


def grade_adjusted_pace(speed_m_s: float, grade_pct: float) -> float:
    """Minetti cost-of-running approximation, returns flat-equivalent m/s."""
    if speed_m_s is None or speed_m_s <= 0:
        return 0.0
    g = (grade_pct or 0.0) / 100.0
    cost_factor = (
        155.4 * g ** 5
        - 30.4 * g ** 4
        - 43.3 * g ** 3
        + 46.3 * g ** 2
        + 19.5 * g
        + 3.6
    ) / 3.6
    if cost_factor <= 0:
        return speed_m_s
    return speed_m_s / cost_factor


# ---------------------------------------------------------------------------
# Best efforts / race predictor
# ---------------------------------------------------------------------------

def riegel_predict(known_time_s: float, known_dist_m: float, target_dist_m: float) -> float:
    """Riegel formula for race time prediction."""
    if not known_time_s or not known_dist_m:
        return 0.0
    return known_time_s * (target_dist_m / known_dist_m) ** 1.06


def vdot_from_5k(time_s: float) -> float:
    """Approximate Daniels VDOT from a 5k time."""
    if not time_s:
        return 0.0
    minutes = time_s / 60.0
    velocity_m_min = 5000.0 / minutes
    pct_vo2max = 0.8 + 0.1894393 * math.exp(-0.012778 * minutes) + 0.2989558 * math.exp(-0.1932605 * minutes)
    vo2 = -4.6 + 0.182258 * velocity_m_min + 0.000104 * velocity_m_min ** 2
    return round(vo2 / pct_vo2max, 1)


# ---------------------------------------------------------------------------
# Mean-max curves (rolling max for power or pace)
# ---------------------------------------------------------------------------

def mean_max_curve(stream: list[float], windows_s: list[int]) -> dict[int, float]:
    """Best rolling-mean value for each window length (assumes 1Hz samples)."""
    out: dict[int, float] = {}
    if not stream:
        return out
    cum = [0.0]
    for v in stream:
        cum.append(cum[-1] + (v or 0.0))
    n = len(stream)
    for w in windows_s:
        if w > n:
            continue
        best = 0.0
        for i in range(n - w + 1):
            avg = (cum[i + w] - cum[i]) / w
            if avg > best:
                best = avg
        out[w] = best
    return out


def estimate_ftp_from_mmp(mmp: dict[int, float]) -> float:
    """0.95 * 20-min best, fallback to 0.92 * 5-min if 20-min missing."""
    if 1200 in mmp and mmp[1200] > 0:
        return round(mmp[1200] * 0.95, 0)
    if 300 in mmp and mmp[300] > 0:
        return round(mmp[300] * 0.92, 0)
    return 0.0


# ---------------------------------------------------------------------------
# Performance Management Chart (CTL / ATL / TSB)
# ---------------------------------------------------------------------------

def pmc_series(daily_loads: list[tuple[str, float]]) -> list[dict]:
    """Compute CTL/ATL/TSB from a sorted list of (day, load) tuples.

    Days with no entry are filled with load=0.
    """
    if not daily_loads:
        return []
    days_map = {d: l for d, l in daily_loads}
    start = datetime.strptime(daily_loads[0][0], "%Y-%m-%d")
    end = datetime.strptime(daily_loads[-1][0], "%Y-%m-%d")
    out = []
    ctl = 0.0
    atl = 0.0
    k_ctl = 1 - math.exp(-1 / 42)
    k_atl = 1 - math.exp(-1 / 7)
    cur = start
    while cur <= end:
        key = cur.strftime("%Y-%m-%d")
        load = days_map.get(key, 0.0)
        ctl = ctl + (load - ctl) * k_ctl
        atl = atl + (load - atl) * k_atl
        out.append({
            "day": key,
            "load": round(load, 1),
            "ctl": round(ctl, 1),
            "atl": round(atl, 1),
            "tsb": round(ctl - atl, 1),
        })
        cur += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# ACWR / monotony / strain
# ---------------------------------------------------------------------------

def acute_chronic_ratio(daily_loads: list[float]) -> float:
    """Acute (last 7d) divided by chronic (last 28d) load."""
    if len(daily_loads) < 28:
        return 0.0
    acute = sum(daily_loads[-7:]) / 7.0
    chronic = sum(daily_loads[-28:]) / 28.0
    if chronic == 0:
        return 0.0
    return round(acute / chronic, 2)


def monotony(daily_loads: list[float]) -> float:
    """Foster monotony — mean / std over last 7 days."""
    window = daily_loads[-7:]
    if len(window) < 2:
        return 0.0
    mean = sum(window) / len(window)
    var = sum((x - mean) ** 2 for x in window) / len(window)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return round(mean / std, 2)


def strain(daily_loads: list[float]) -> float:
    """Foster strain = weekly load * monotony."""
    weekly = sum(daily_loads[-7:])
    return round(weekly * monotony(daily_loads), 1)


# ---------------------------------------------------------------------------
# Decoupling
# ---------------------------------------------------------------------------

def aerobic_decoupling(power_or_pace: list[float], hr: list[float]) -> float:
    """Pa:Hr or Pw:Hr decoupling in % between first and second half."""
    n = min(len(power_or_pace), len(hr))
    if n < 60:
        return 0.0
    half = n // 2
    def ratio(p, h):
        clean = [(pi, hi) for pi, hi in zip(p, h) if pi and hi]
        if not clean:
            return 0.0
        avg_p = sum(x[0] for x in clean) / len(clean)
        avg_h = sum(x[1] for x in clean) / len(clean)
        return avg_p / avg_h if avg_h else 0.0
    r1 = ratio(power_or_pace[:half], hr[:half])
    r2 = ratio(power_or_pace[half:n], hr[half:n])
    if r1 == 0:
        return 0.0
    return round((r1 - r2) / r1 * 100.0, 2)


# ---------------------------------------------------------------------------
# Zone classification
# ---------------------------------------------------------------------------

def classify_polarization(
    activities: Iterable[dict], easy_hr: float, hard_hr: float
) -> dict:
    """Bucket activity time into easy / moderate / hard based on average HR."""
    easy_s = mod_s = hard_s = 0
    for a in activities:
        hr = a.get("average_hr") or 0
        t = a.get("moving_time") or 0
        if not hr or not t:
            continue
        if hr < easy_hr:
            easy_s += t
        elif hr < hard_hr:
            mod_s += t
        else:
            hard_s += t
    total = easy_s + mod_s + hard_s
    if total == 0:
        return {"easy_pct": 0, "moderate_pct": 0, "hard_pct": 0, "total_min": 0}
    return {
        "easy_pct": round(easy_s / total * 100, 1),
        "moderate_pct": round(mod_s / total * 100, 1),
        "hard_pct": round(hard_s / total * 100, 1),
        "total_min": round(total / 60, 1),
    }


# ---------------------------------------------------------------------------
# Swim
# ---------------------------------------------------------------------------

def swolf(time_s: float, strokes: int) -> float:
    return time_s + strokes


def css_estimate(t_400_s: float, t_200_s: float) -> float:
    """Critical Swim Speed in m/s from 400 and 200 m time trials."""
    if not t_400_s or not t_200_s or t_400_s <= t_200_s:
        return 0.0
    return 200.0 / (t_400_s - t_200_s)


# ---------------------------------------------------------------------------
# Climbing
# ---------------------------------------------------------------------------

def vam(elevation_gain_m: float, duration_s: float) -> float:
    """Vertical Ascent Meters per hour."""
    if not duration_s:
        return 0.0
    return round(elevation_gain_m / (duration_s / 3600.0), 0)


def watts_per_kg(avg_watts: float, weight_kg: float) -> float:
    if not weight_kg:
        return 0.0
    return round(avg_watts / weight_kg, 2)


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def fmt_duration(seconds: float) -> str:
    seconds = int(seconds or 0)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_pace(minutes_per_km: float | None) -> str:
    if not minutes_per_km:
        return "-"
    m = int(minutes_per_km)
    s = int((minutes_per_km - m) * 60)
    return f"{m}:{s:02d}"
