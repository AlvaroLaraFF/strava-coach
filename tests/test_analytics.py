#!/usr/bin/env python3
"""Strict unit tests for strava/analytics.py.

Verifies formulas against known textbook values, edge cases that can
cause division by zero / NaN / overflow, and cross-checks between
related functions that must be mathematically consistent.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from strava.analytics import (
    acute_chronic_ratio,
    aerobic_decoupling,
    banister_trimp,
    classify_polarization,
    css_estimate,
    estimate_ftp_from_mmp,
    fmt_duration,
    fmt_pace,
    grade_adjusted_pace,
    hr_reserve_fraction,
    intensity_factor,
    mean_max_curve,
    monotony,
    normalized_power,
    pace_min_per_km,
    pmc_series,
    riegel_predict,
    speed_to_pace_min_km,
    strain,
    swolf,
    tss,
    vam,
    variability_index,
    vdot_from_5k,
    watts_per_kg,
)


# ───────────────────────────────────────────────────────────────
# HR reserve
# ───────────────────────────────────────────────────────────────

class TestHRReserve(unittest.TestCase):
    def test_at_rest(self):
        self.assertAlmostEqual(hr_reserve_fraction(50, 50, 190), 0.0)

    def test_at_max(self):
        self.assertAlmostEqual(hr_reserve_fraction(190, 50, 190), 1.0)

    def test_midpoint(self):
        self.assertAlmostEqual(hr_reserve_fraction(120, 50, 190), 0.5, places=2)

    def test_clamps_below_zero(self):
        self.assertEqual(hr_reserve_fraction(40, 50, 190), 0.0)

    def test_clamps_above_one(self):
        self.assertEqual(hr_reserve_fraction(200, 50, 190), 1.0)

    def test_max_equals_rest_no_crash(self):
        self.assertEqual(hr_reserve_fraction(100, 100, 100), 0.0)


# ───────────────────────────────────────────────────────────────
# TRIMP
# ───────────────────────────────────────────────────────────────

class TestTrimp(unittest.TestCase):
    def test_harder_session_higher_trimp(self):
        easy = banister_trimp(60, 130, 50, 190, "M")
        hard = banister_trimp(60, 175, 50, 190, "M")
        self.assertGreater(hard, easy * 2)

    def test_longer_session_higher_trimp(self):
        short = banister_trimp(30, 150, 50, 190, "M")
        long = banister_trimp(60, 150, 50, 190, "M")
        self.assertAlmostEqual(long, short * 2, delta=1.0)

    def test_female_coefficient(self):
        m = banister_trimp(60, 160, 50, 190, "M")
        f = banister_trimp(60, 160, 50, 190, "F")
        self.assertNotEqual(m, f)
        self.assertGreater(m, f)

    def test_zero_duration_returns_zero(self):
        self.assertEqual(banister_trimp(0, 150, 50, 190), 0.0)

    def test_zero_hr_returns_zero(self):
        self.assertEqual(banister_trimp(60, 0, 50, 190), 0.0)

    def test_negative_inputs_no_crash(self):
        result = banister_trimp(-10, -50, 50, 190)
        self.assertIsInstance(result, float)


# ───────────────────────────────────────────────────────────────
# Normalized Power — Coggan definition
# ───────────────────────────────────────────────────────────────

class TestNormalizedPower(unittest.TestCase):
    def test_constant_power_equals_average(self):
        stream = [250.0] * 300
        self.assertAlmostEqual(normalized_power(stream), 250.0, delta=0.5)

    def test_variable_power_exceeds_average(self):
        stream = ([50.0] * 30 + [400.0] * 30) * 5
        np = normalized_power(stream)
        avg = sum(stream) / len(stream)
        self.assertGreater(np, avg)

    def test_all_zeros(self):
        self.assertEqual(normalized_power([0.0] * 120), 0.0)

    def test_single_spike_dominates(self):
        stream = [100.0] * 120
        stream[60] = 1000.0
        np_spike = normalized_power(stream)
        np_flat = normalized_power([100.0] * 120)
        self.assertGreater(np_spike, np_flat)

    def test_empty_returns_zero(self):
        self.assertEqual(normalized_power([]), 0.0)

    def test_below_window_returns_zero(self):
        self.assertEqual(normalized_power([200] * 10), 0.0)

    def test_none_values_treated_as_zero(self):
        stream = [None, 200.0, None, 200.0] * 30
        result = normalized_power(stream)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)


# ───────────────────────────────────────────────────────────────
# TSS / IF — cross-consistency
# ───────────────────────────────────────────────────────────────

class TestTSSConsistency(unittest.TestCase):
    def test_one_hour_at_ftp_is_100(self):
        self.assertAlmostEqual(tss(3600, 250, 1.0, 250), 100.0, delta=0.1)

    def test_two_hours_at_ftp_is_200(self):
        self.assertAlmostEqual(tss(7200, 250, 1.0, 250), 200.0, delta=0.1)

    def test_half_hour_at_ftp_is_50(self):
        self.assertAlmostEqual(tss(1800, 250, 1.0, 250), 50.0, delta=0.1)

    def test_if_above_one_tss_grows_faster(self):
        tss_at = tss(3600, 250, 1.0, 250)
        tss_above = tss(3600, 275, 1.1, 250)
        self.assertGreater(tss_above, tss_at * 1.1)

    def test_if_and_np_are_consistent(self):
        np = 275.0
        ftp = 250.0
        if_val = intensity_factor(np, ftp)
        self.assertAlmostEqual(if_val, 1.1, delta=0.01)

    def test_vi_is_one_for_constant(self):
        self.assertAlmostEqual(variability_index(200, 200), 1.0)

    def test_vi_above_one_for_variable(self):
        self.assertGreater(variability_index(220, 200), 1.0)

    def test_zero_ftp_safe(self):
        self.assertEqual(tss(3600, 200, 0.8, 0), 0.0)
        self.assertEqual(intensity_factor(200, 0), 0.0)


# ───────────────────────────────────────────────────────────────
# Riegel — known reference values
# ───────────────────────────────────────────────────────────────

class TestRiegel(unittest.TestCase):
    def test_known_20min_5k_to_10k(self):
        t = riegel_predict(20 * 60, 5000, 10000)
        self.assertAlmostEqual(t, 41 * 60 + 42, delta=30)

    def test_double_distance_more_than_double_time(self):
        t5 = riegel_predict(20 * 60, 5000, 5000)
        t10 = riegel_predict(20 * 60, 5000, 10000)
        self.assertGreater(t10, t5 * 2)

    def test_same_distance_same_time(self):
        t = riegel_predict(1500, 5000, 5000)
        self.assertAlmostEqual(t, 1500, delta=1)

    def test_shorter_distance_faster(self):
        t5k = riegel_predict(25 * 60, 5000, 5000)
        t1k = riegel_predict(25 * 60, 5000, 1000)
        self.assertLess(t1k, t5k)

    def test_zero_time_returns_zero(self):
        self.assertEqual(riegel_predict(0, 5000, 10000), 0.0)

    def test_zero_distance_returns_zero(self):
        self.assertEqual(riegel_predict(1200, 0, 10000), 0.0)


# ───────────────────────────────────────────────────────────────
# VDOT — known Daniels table values
# ───────────────────────────────────────────────────────────────

class TestVDOT(unittest.TestCase):
    def test_elite_5k_sub15(self):
        vdot = vdot_from_5k(14 * 60 + 30)
        self.assertGreater(vdot, 65)

    def test_recreational_5k_30min(self):
        vdot = vdot_from_5k(30 * 60)
        self.assertGreater(vdot, 28)
        self.assertLess(vdot, 38)

    def test_faster_5k_higher_vdot(self):
        fast = vdot_from_5k(18 * 60)
        slow = vdot_from_5k(28 * 60)
        self.assertGreater(fast, slow)

    def test_zero_returns_zero(self):
        self.assertEqual(vdot_from_5k(0), 0.0)


# ───────────────────────────────────────────────────────────────
# Mean-max curve
# ───────────────────────────────────────────────────────────────

class TestMeanMaxCurve(unittest.TestCase):
    def test_constant_all_windows_equal(self):
        stream = [200.0] * 3600
        curve = mean_max_curve(stream, [1, 5, 30, 60, 300, 1200, 3600])
        for w in curve:
            self.assertAlmostEqual(curve[w], 200.0, delta=0.1)

    def test_spike_only_visible_in_short_windows(self):
        stream = [100.0] * 600
        stream[300] = 1000.0
        curve = mean_max_curve(stream, [1, 60, 600])
        self.assertAlmostEqual(curve[1], 1000.0)
        self.assertAlmostEqual(curve[600], sum(stream) / 600, delta=1.0)

    def test_longer_window_never_exceeds_shorter(self):
        import random
        random.seed(42)
        stream = [random.uniform(100, 400) for _ in range(600)]
        curve = mean_max_curve(stream, [1, 5, 30, 60, 300, 600])
        windows = sorted(curve.keys())
        for i in range(len(windows) - 1):
            self.assertGreaterEqual(curve[windows[i]], curve[windows[i + 1]] - 0.01)

    def test_window_larger_than_stream_excluded(self):
        curve = mean_max_curve([100, 200, 300], [1, 5, 100])
        self.assertNotIn(100, curve)
        self.assertNotIn(5, curve)
        self.assertIn(1, curve)

    def test_ftp_estimate_consistent_with_mmp(self):
        stream = [280.0] * 1200
        curve = mean_max_curve(stream, [1200])
        ftp = estimate_ftp_from_mmp(curve)
        self.assertAlmostEqual(ftp, 266.0, delta=1.0)


# ───────────────────────────────────────────────────────────────
# PMC (CTL / ATL / TSB) — mathematical properties
# ───────────────────────────────────────────────────────────────

class TestPMC(unittest.TestCase):
    def test_tsb_equals_ctl_minus_atl(self):
        loads = [(f"2026-01-{i+1:02d}", 80) for i in range(30)]
        series = pmc_series(loads)
        for day in series:
            self.assertAlmostEqual(day["tsb"], day["ctl"] - day["atl"], delta=0.2)

    def test_rest_period_tsb_rises(self):
        loads = [(f"2026-01-{i+1:02d}", 100) for i in range(14)]
        loads += [(f"2026-01-{i+15:02d}", 0) for i in range(14)]
        series = pmc_series(loads)
        end_training = series[13]["tsb"]
        after_rest = series[-1]["tsb"]
        self.assertGreater(after_rest, end_training)

    def test_atl_responds_faster_than_ctl(self):
        loads = [(f"2026-01-{i+1:02d}", 100) for i in range(7)]
        series = pmc_series(loads)
        self.assertGreater(series[-1]["atl"], series[-1]["ctl"])

    def test_zero_load_ctl_decays(self):
        loads = [("2026-01-01", 200)] + [(f"2026-01-{i+2:02d}", 0) for i in range(30)]
        series = pmc_series(loads)
        self.assertGreater(series[0]["ctl"], series[-1]["ctl"])

    def test_gaps_filled_with_zero(self):
        loads = [("2026-01-01", 100), ("2026-01-10", 100)]
        series = pmc_series(loads)
        self.assertEqual(len(series), 10)

    def test_empty_returns_empty(self):
        self.assertEqual(pmc_series([]), [])


# ───────────────────────────────────────────────────────────────
# ACWR / Monotony / Strain — Foster model
# ───────────────────────────────────────────────────────────────

class TestACWR(unittest.TestCase):
    def test_steady_state_is_one(self):
        loads = [100.0] * 28
        self.assertAlmostEqual(acute_chronic_ratio(loads), 1.0, places=1)

    def test_sudden_spike_above_threshold(self):
        loads = [50.0] * 21 + [200.0] * 7
        self.assertGreater(acute_chronic_ratio(loads), 1.5)

    def test_taper_below_one(self):
        loads = [100.0] * 21 + [20.0] * 7
        self.assertLess(acute_chronic_ratio(loads), 0.5)

    def test_needs_28_days_minimum(self):
        self.assertEqual(acute_chronic_ratio([50.0] * 27), 0.0)

    def test_all_zeros_no_crash(self):
        self.assertEqual(acute_chronic_ratio([0.0] * 28), 0.0)


class TestMonotony(unittest.TestCase):
    def test_identical_days_returns_zero(self):
        self.assertEqual(monotony([100] * 7), 0.0)

    def test_alternating_pattern(self):
        m = monotony([100, 0, 100, 0, 100, 0, 100])
        self.assertGreater(m, 0)

    def test_one_hard_day_low_monotony(self):
        m = monotony([200, 0, 0, 0, 0, 0, 0])
        self.assertLess(m, 0.5)

    def test_short_input_safe(self):
        self.assertEqual(monotony([100]), 0.0)


class TestStrain(unittest.TestCase):
    def test_strain_is_load_times_monotony(self):
        loads = [0] * 21 + [100, 50, 100, 50, 100, 50, 100]
        s = strain(loads)
        m = monotony(loads)
        weekly = sum(loads[-7:])
        self.assertAlmostEqual(s, weekly * m, places=1)

    def test_all_zeros_is_zero(self):
        self.assertEqual(strain([0.0] * 28), 0.0)


# ───────────────────────────────────────────────────────────────
# Aerobic decoupling
# ───────────────────────────────────────────────────────────────

class TestDecoupling(unittest.TestCase):
    def test_no_drift_is_zero(self):
        pace = [3.0] * 200
        hr = [150.0] * 200
        self.assertAlmostEqual(aerobic_decoupling(pace, hr), 0.0, delta=0.1)

    def test_positive_drift_positive_decoupling(self):
        pace = [3.0] * 200
        hr = [140.0] * 100 + [160.0] * 100
        result = aerobic_decoupling(pace, hr)
        self.assertGreater(result, 0)

    def test_opposite_direction(self):
        pace = [3.0] * 200
        hr_up = [140.0] * 100 + [160.0] * 100
        hr_down = [160.0] * 100 + [140.0] * 100
        d_up = aerobic_decoupling(pace, hr_up)
        d_down = aerobic_decoupling(pace, hr_down)
        self.assertGreater(d_up, 0)
        self.assertLess(d_down, 0)

    def test_too_short_returns_zero(self):
        self.assertEqual(aerobic_decoupling([3] * 30, [150] * 30), 0.0)

    def test_mismatched_lengths_uses_minimum(self):
        result = aerobic_decoupling([3.0] * 200, [150.0] * 100)
        self.assertIsInstance(result, float)


# ───────────────────────────────────────────────────────────────
# Polarization
# ───────────────────────────────────────────────────────────────

class TestPolarization(unittest.TestCase):
    def test_all_easy_is_100_pct(self):
        acts = [{"average_hr": 110, "moving_time": 3600}] * 10
        result = classify_polarization(acts, 140, 170)
        self.assertEqual(result["easy_pct"], 100.0)
        self.assertEqual(result["moderate_pct"], 0.0)
        self.assertEqual(result["hard_pct"], 0.0)

    def test_all_hard_is_100_pct(self):
        acts = [{"average_hr": 180, "moving_time": 3600}] * 10
        result = classify_polarization(acts, 140, 170)
        self.assertEqual(result["hard_pct"], 100.0)

    def test_percentages_sum_to_100(self):
        acts = [
            {"average_hr": 120, "moving_time": 3600},
            {"average_hr": 155, "moving_time": 1800},
            {"average_hr": 180, "moving_time": 600},
        ]
        result = classify_polarization(acts, 140, 170)
        total = result["easy_pct"] + result["moderate_pct"] + result["hard_pct"]
        self.assertAlmostEqual(total, 100.0, delta=0.5)

    def test_no_hr_ignored(self):
        acts = [{"average_hr": 0, "moving_time": 3600}]
        result = classify_polarization(acts, 140, 170)
        self.assertEqual(result["total_min"], 0)

    def test_no_time_ignored(self):
        acts = [{"average_hr": 150, "moving_time": 0}]
        result = classify_polarization(acts, 140, 170)
        self.assertEqual(result["total_min"], 0)

    def test_empty_safe(self):
        result = classify_polarization([], 140, 170)
        self.assertEqual(result["total_min"], 0)


# ───────────────────────────────────────────────────────────────
# GAP (grade-adjusted pace)
# ───────────────────────────────────────────────────────────────

class TestGAP(unittest.TestCase):
    def test_flat_grade_is_identity(self):
        gap = grade_adjusted_pace(3.0, 0.0)
        self.assertAlmostEqual(gap, 3.0, delta=0.3)

    def test_uphill_slower_gap(self):
        gap = grade_adjusted_pace(2.5, 10.0)
        self.assertGreater(gap, 0)

    def test_steep_downhill_faster_gap(self):
        gap_flat = grade_adjusted_pace(3.0, 0.0)
        gap_down = grade_adjusted_pace(3.0, -5.0)
        self.assertGreater(gap_down, gap_flat)

    def test_zero_speed_is_zero(self):
        self.assertEqual(grade_adjusted_pace(0, 5), 0.0)

    def test_negative_speed_is_zero(self):
        self.assertEqual(grade_adjusted_pace(-1, 0), 0.0)


# ───────────────────────────────────────────────────────────────
# Pace helpers — cross-consistency
# ───────────────────────────────────────────────────────────────

class TestPaceHelpers(unittest.TestCase):
    def test_pace_from_distance_time(self):
        self.assertAlmostEqual(pace_min_per_km(5000, 25 * 60), 5.0)

    def test_pace_from_speed(self):
        self.assertAlmostEqual(speed_to_pace_min_km(1000 / 300), 5.0, delta=0.01)

    def test_both_methods_agree(self):
        d, t = 10000, 50 * 60
        p1 = pace_min_per_km(d, t)
        p2 = speed_to_pace_min_km(d / t)
        self.assertAlmostEqual(p1, p2, places=2)

    def test_zero_distance(self):
        self.assertIsNone(pace_min_per_km(0, 300))

    def test_zero_speed(self):
        self.assertIsNone(speed_to_pace_min_km(0))

    def test_fmt_roundtrip(self):
        self.assertEqual(fmt_pace(5.0), "5:00")
        self.assertEqual(fmt_pace(4.25), "4:15")
        self.assertEqual(fmt_pace(None), "-")


# ───────────────────────────────────────────────────────────────
# Format duration
# ───────────────────────────────────────────────────────────────

class TestFmtDuration(unittest.TestCase):
    def test_exact_minute(self):
        self.assertEqual(fmt_duration(60), "1:00")

    def test_exact_hour(self):
        self.assertEqual(fmt_duration(3600), "1:00:00")

    def test_complex(self):
        self.assertEqual(fmt_duration(3661), "1:01:01")

    def test_zero(self):
        self.assertEqual(fmt_duration(0), "0:00")

    def test_none_treated_as_zero(self):
        self.assertEqual(fmt_duration(None), "0:00")

    def test_large_value(self):
        result = fmt_duration(36000)
        self.assertEqual(result, "10:00:00")


# ───────────────────────────────────────────────────────────────
# Swim: SWOLF, CSS
# ───────────────────────────────────────────────────────────────

class TestSwim(unittest.TestCase):
    def test_swolf_formula(self):
        self.assertEqual(swolf(28, 12), 40)

    def test_css_known_value(self):
        css = css_estimate(6 * 60, 2 * 60 + 50)
        pace_100 = 100 / css
        self.assertGreater(pace_100, 80)
        self.assertLess(pace_100, 130)

    def test_css_400_must_be_slower_than_200(self):
        self.assertEqual(css_estimate(100, 200), 0.0)

    def test_css_zero_inputs(self):
        self.assertEqual(css_estimate(0, 0), 0.0)
        self.assertEqual(css_estimate(300, 0), 0.0)


# ───────────────────────────────────────────────────────────────
# Climbing: VAM, W/kg
# ───────────────────────────────────────────────────────────────

class TestClimbing(unittest.TestCase):
    def test_vam_known(self):
        self.assertAlmostEqual(vam(1500, 3600), 1500.0)

    def test_vam_half_hour(self):
        self.assertAlmostEqual(vam(750, 1800), 1500.0)

    def test_vam_zero_time(self):
        self.assertEqual(vam(500, 0), 0.0)

    def test_wkg_known(self):
        self.assertAlmostEqual(watts_per_kg(300, 75), 4.0)

    def test_wkg_zero_weight(self):
        self.assertEqual(watts_per_kg(300, 0), 0.0)

    def test_wkg_zero_watts(self):
        self.assertAlmostEqual(watts_per_kg(0, 70), 0.0)


# ───────────────────────────────────────────────────────────────
# FTP estimation cross-check
# ───────────────────────────────────────────────────────────────

class TestFTPEstimate(unittest.TestCase):
    def test_20min_method(self):
        self.assertAlmostEqual(estimate_ftp_from_mmp({1200: 300}), 285.0, delta=1)

    def test_5min_fallback(self):
        ftp = estimate_ftp_from_mmp({300: 350})
        self.assertAlmostEqual(ftp, 322.0, delta=2)

    def test_20min_takes_priority_over_5min(self):
        ftp = estimate_ftp_from_mmp({300: 400, 1200: 300})
        self.assertAlmostEqual(ftp, 285.0, delta=1)

    def test_empty_mmp(self):
        self.assertEqual(estimate_ftp_from_mmp({}), 0.0)

    def test_zero_values(self):
        self.assertEqual(estimate_ftp_from_mmp({1200: 0}), 0.0)


if __name__ == "__main__":
    unittest.main()
