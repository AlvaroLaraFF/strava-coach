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
    elif "T" not in s:
        s = s + "T00:00:00+00:00"
    return datetime.fromisoformat(s)


def day_key(s: str) -> str:
    return parse_iso(s).strftime("%Y-%m-%d")


def iso_week(s: str) -> str:
    dt = parse_iso(s)
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


# ---------------------------------------------------------------------------
# Age and physiological estimation (evidence-based)
# ---------------------------------------------------------------------------

def age_from_birthdate(birth_date_str: str) -> float | None:
    """Compute age in years from an ISO date string (YYYY-MM-DD)."""
    if not birth_date_str:
        return None
    try:
        bd = datetime.strptime(birth_date_str[:10], "%Y-%m-%d")
        today = datetime.now(timezone.utc)
        return (today - bd.replace(tzinfo=timezone.utc)).days / 365.25
    except (ValueError, TypeError):
        return None


def hr_max_tanaka(age: float) -> float:
    """Tanaka (2001) — meta-analysis of 18,712 subjects, SEE ~10 bpm.

    Tanaka, Monahan, Seals. JACC 37(1):153-156, 2001.
    """
    return 208.0 - 0.7 * age


def hr_max_gulati(age: float) -> float:
    """Gulati (2010) — women-specific, validated on 5,437 women.

    Gulati et al. Circulation 2010.
    """
    return 206.0 - 0.88 * age


def estimate_hr_max(
    age: float | None,
    gender: str = "M",
    observed_peaks: list[float] | None = None,
) -> float:
    """Estimate HR max using the best available evidence.

    Strategy (based on sports science consensus):
    - Formula: Tanaka for men, Gulati for women
    - Observed peak is a FLOOR, not a ceiling (most recreational athletes
      are 5-15 bpm below true max in regular training)
    - Working HR max = max(formula, best credible observed peak)
    - A peak is "credible" if > 100 bpm (filters sensor artifacts at rest)

    Returns the working HR max estimate.
    """
    # Formula-based estimate
    formula_est = None
    if age is not None:
        if gender.upper().startswith("F"):
            formula_est = hr_max_gulati(age)
        else:
            formula_est = hr_max_tanaka(age)

    # Best credible observed peak (> 100 bpm filters obvious artifacts)
    best_observed = None
    if observed_peaks:
        credible = [p for p in observed_peaks if p and p > 100]
        if credible:
            best_observed = max(credible)

    # Combine: take the higher of the two (observed is a floor)
    candidates = [v for v in [formula_est, best_observed] if v is not None]
    if not candidates:
        return 190.0  # last-resort fallback
    return round(max(candidates), 0)


def estimate_hr_rest(
    activities: list[dict] | None = None,
    age: float | None = None,
    default: float = 55.0,
) -> float:
    """Estimate resting HR.

    Resting HR cannot be reliably derived from exercise data alone — even
    easy runs have average HRs of 120-160 bpm, far above true resting.

    Strategy:
    1. If the user has manually provided a value, that should be passed
       directly and this function skipped.
    2. Otherwise, use age-based defaults for a recreationally active
       endurance athlete (conservative estimates).
    3. Falls back to 55 bpm if nothing else available.

    Norms for recreational endurance athletes:
      Age 20-35: ~50 bpm
      Age 35-50: ~55 bpm
      Age 50-65: ~58 bpm
      Age 65+:   ~62 bpm
    """
    if age is not None:
        if age < 35:
            return 50.0
        elif age < 50:
            return 55.0
        elif age < 65:
            return 58.0
        else:
            return 62.0
    return default


def estimate_lthr(
    hr_max: float,
    hr_rest: float = 55.0,
    best_20min_hr: float | None = None,
) -> float:
    """Estimate Lactate Threshold Heart Rate.

    Hierarchy:
    1. If best 20-min avg HR available: LTHR ≈ 95% of that value
       (intervals.icu method — Friel recommends last-20min of a 30min test,
       but best-20min from hard efforts is a practical proxy)
    2. Fallback: 88% of HR max (central tendency for recreational trained
       athletes, from Inoue et al. 2019 and Friel guidelines)

    The 88% figure is a population average with high variance (85-92% range),
    so the best_20min_hr path is strongly preferred when data exists.
    """
    if best_20min_hr and best_20min_hr > 100:
        return round(best_20min_hr * 0.95, 0)
    return round(hr_max * 0.88, 0)


def hr_zones_karvonen(hr_max: float, hr_rest: float) -> list[dict]:
    """5-zone model using Heart Rate Reserve (Karvonen method).

    HRR = HRmax - HRrest; Target = HRrest + (%HRR × HRR).
    Recommended by ACSM over simple %HRmax (Swain et al. 1994).

    Zone boundaries (%HRR):
      Z1: 50-60%  Recovery
      Z2: 60-70%  Aerobic base (below LT1)
      Z3: 70-80%  Tempo / lactate clearance
      Z4: 80-90%  Threshold (around LT2)
      Z5: 90-100% VO2max / anaerobic
    """
    hrr = hr_max - hr_rest
    boundaries = [
        (1, "Recovery",  0.50, 0.60),
        (2, "Aerobic",   0.60, 0.70),
        (3, "Tempo",     0.70, 0.80),
        (4, "Threshold", 0.80, 0.90),
        (5, "VO2max",    0.90, 1.00),
    ]
    zones = []
    for num, name, lo, hi in boundaries:
        zones.append({
            "zone": num,
            "name": name,
            "min_bpm": round(hr_rest + hrr * lo),
            "max_bpm": round(hr_rest + hrr * hi),
            "pct_hrr_lo": lo,
            "pct_hrr_hi": hi,
        })
    return zones


def hr_zones_friel(lthr: float) -> list[dict]:
    """7-zone Friel model anchored to LTHR (TrainingPeaks standard for running).

    Joe Friel, "The Triathlete's Training Bible" / TrainingPeaks.
    """
    boundaries = [
        (1,   "Recovery",    0.00, 0.85),
        (2,   "Aerobic",     0.85, 0.89),
        (3,   "Tempo",       0.90, 0.94),
        (4,   "SubThreshold", 0.95, 0.99),
        ("5a", "SuperThreshold", 1.00, 1.02),
        ("5b", "Aerobic capacity", 1.03, 1.06),
        ("5c", "Anaerobic",  1.06, 1.15),
    ]
    zones = []
    for num, name, lo, hi in boundaries:
        zones.append({
            "zone": num,
            "name": name,
            "min_bpm": round(lthr * lo),
            "max_bpm": round(lthr * hi),
            "pct_lthr_lo": lo,
            "pct_lthr_hi": hi,
        })
    return zones


# ACSM / Cooper Institute VO2max norms by age and gender (ml/kg/min)
_VO2MAX_NORMS_M = {
    # (age_lo, age_hi): (poor, below_avg, average, above_avg, good, excellent)
    (20, 29): (33, 36, 41, 45, 52),
    (30, 39): (31, 34, 39, 43, 50),
    (40, 49): (28, 32, 36, 40, 47),
    (50, 59): (25, 28, 33, 37, 44),
    (60, 69): (22, 25, 30, 34, 41),
    (70, 99): (19, 22, 27, 31, 38),
}
_VO2MAX_NORMS_F = {
    (20, 29): (24, 28, 32, 36, 41),
    (30, 39): (22, 26, 30, 34, 39),
    (40, 49): (20, 24, 28, 32, 37),
    (50, 59): (18, 21, 25, 29, 34),
    (60, 69): (16, 18, 22, 26, 31),
    (70, 99): (14, 16, 20, 24, 29),
}


def vo2max_classification(
    vdot: float, age: float, gender: str = "M",
) -> dict:
    """Classify VO2max (approximated by VDOT) using ACSM/Cooper norms.

    Returns a dict with the category and percentile band.
    Note: VDOT ≈ VO2max ±2-3 ml/kg/min for trained runners (Daniels).
    """
    norms = _VO2MAX_NORMS_M if gender.upper().startswith("M") else _VO2MAX_NORMS_F
    thresholds = None
    for (lo, hi), t in norms.items():
        if lo <= age <= hi:
            thresholds = t
            break
    if thresholds is None:
        thresholds = list(norms.values())[-1]  # fallback to oldest bracket

    labels = ["Poor", "Below average", "Average", "Above average", "Good", "Excellent"]
    category = labels[0]
    for i, cutoff in enumerate(thresholds):
        if vdot >= cutoff:
            category = labels[i + 1]
        else:
            break

    return {
        "vo2max_proxy": round(vdot, 1),
        "category": category,
        "age_bracket": f"{int(age)//10*10}-{int(age)//10*10+9}",
        "gender": gender,
        "thresholds": dict(zip(labels[1:], thresholds)),
    }


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
    coeff = 0.64 if sex.upper().startswith("M") else 0.86
    return duration_min * hrr * coeff * math.exp(k * hrr)


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


def vdot_to_threshold_pace(vdot: float) -> float:
    """Threshold pace in min/km from VDOT (Daniels T-pace at ~88% VO2max).

    Inverts: vo2 = -4.6 + 0.182258*v + 0.000104*v^2  (v in m/min)
    at vo2 = 0.88 * vdot.
    """
    if not vdot:
        return 0.0
    a = 0.000104
    b = 0.182258
    c = -(4.6 + 0.88 * vdot)
    disc = b * b - 4 * a * c
    if disc < 0:
        return 0.0
    v_m_per_min = (-b + math.sqrt(disc)) / (2 * a)
    if v_m_per_min <= 0:
        return 0.0
    return round(1000.0 / v_m_per_min, 3)


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
        return round(mmp[300] * 0.75, 0)
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
    """Acute (last 7d) divided by chronic (last 28d) load — rolling average."""
    if len(daily_loads) < 28:
        return 0.0
    acute = sum(daily_loads[-7:]) / 7.0
    chronic = sum(daily_loads[-28:]) / 28.0
    if chronic == 0:
        return 0.0
    return round(acute / chronic, 2)


def ewma_acwr(daily_loads: list[float]) -> float:
    """EWMA-based ACWR (Hulin 2016 / Williams 2017).

    Uses exponential decay: alpha_acute = 2/(7+1), alpha_chronic = 2/(28+1).
    More sensitive to load spikes than rolling averages.
    """
    if not daily_loads:
        return 0.0
    alpha_a = 2.0 / (7 + 1)
    alpha_c = 2.0 / (28 + 1)
    ewma_a = ewma_c = 0.0
    for load in daily_loads:
        ewma_a = alpha_a * load + (1 - alpha_a) * ewma_a
        ewma_c = alpha_c * load + (1 - alpha_c) * ewma_c
    if ewma_c == 0:
        return 0.0
    return round(ewma_a / ewma_c, 2)


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
    """Bucket activity time into easy / moderate / hard.

    If an activity has a ``time_in_zones_s`` key (list of three floats:
    [easy_s, moderate_s, hard_s] derived from per-second HR streams), that
    is used for accurate second-by-second classification.  Otherwise falls
    back to classifying the entire session by its average HR (less accurate
    for interval workouts).
    """
    easy_s = mod_s = hard_s = 0
    stream_count = avg_count = 0
    for a in activities:
        tiz = a.get("time_in_zones_s")
        if tiz and len(tiz) == 3:
            easy_s += tiz[0]
            mod_s += tiz[1]
            hard_s += tiz[2]
            stream_count += 1
            continue
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
        avg_count += 1
    total = easy_s + mod_s + hard_s
    if total == 0:
        return {"easy_pct": 0, "moderate_pct": 0, "hard_pct": 0, "total_min": 0,
                "method": "none", "stream_activities": 0, "avg_hr_activities": 0}
    return {
        "easy_pct": round(easy_s / total * 100, 1),
        "moderate_pct": round(mod_s / total * 100, 1),
        "hard_pct": round(hard_s / total * 100, 1),
        "total_min": round(total / 60, 1),
        "method": "stream" if stream_count > avg_count else "avg_hr",
        "stream_activities": stream_count,
        "avg_hr_activities": avg_count,
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
