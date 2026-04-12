#!/usr/bin/env python3
"""Strict e2e tests for skill scripts.

Runs each script as a subprocess and validates:
1. Output is valid JSON with the {success, data|error} contract
2. Data fields have correct types and sane value ranges
3. Skills that should fail with no data do so with clear errors
4. Cross-skill consistency: values that overlap must agree
"""

import json
import os
import subprocess
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def run_script(path: str, args: list[str] | None = None, timeout: int = 60) -> dict:
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, path)] + (args or [])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=PROJECT_ROOT)
    stdout = result.stdout.strip()
    if not stdout:
        return {"_empty": True, "_returncode": result.returncode, "_stderr": result.stderr}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"_parse_error": True, "_raw": stdout[:500]}


ALL_SCRIPTS = [
    (".claude/skills/training-load/scripts/training_load.py", ["--days", "90"]),
    (".claude/skills/readiness-today/scripts/readiness.py", []),
    (".claude/skills/overtraining-check/scripts/overtraining.py", []),
    (".claude/skills/weekly-log/scripts/weekly_log.py", ["--weeks", "4"]),
    (".claude/skills/consistency/scripts/consistency.py", ["--weeks", "4"]),
    (".claude/skills/polarization-check/scripts/polarization.py", ["--days", "30"]),
    (".claude/skills/run-race-predictor/scripts/race_predictor.py", ["--recent-days", "90"]),
    (".claude/skills/run-pr-tracker/scripts/pr_tracker.py", []),
    (".claude/skills/run-pace-zones/scripts/pace_zones.py", ["--days", "30"]),
    (".claude/skills/run-cadence-form/scripts/cadence.py", ["--days", "90"]),
    (".claude/skills/run-decoupling/scripts/decoupling.py", ["--min-minutes", "30", "--max-runs", "2"]),
    (".claude/skills/ride-power-curve/scripts/power_curve.py", ["--days", "90"]),
    (".claude/skills/ride-ftp-estimate/scripts/ftp_estimate.py", ["--days", "90"]),
    (".claude/skills/ride-climbing/scripts/climbing.py", ["--days", "90"]),
    (".claude/skills/ride-tss-load/scripts/ride_tss.py", ["--days", "30", "--ftp", "200"]),
    (".claude/skills/swim-swolf/scripts/swim_swolf.py", ["--days", "60"]),
    (".claude/skills/swim-css/scripts/swim_css.py", ["--t400", "6:20", "--t200", "2:55"]),
    (".claude/skills/swim-volume/scripts/swim_volume.py", ["--weeks", "12"]),
    (".claude/skills/tri-combined-load/scripts/tri_load.py", ["--days", "90"]),
    (".claude/skills/tri-discipline-balance/scripts/balance.py", ["--days", "90"]),
    (".claude/skills/gear-mileage/scripts/gear_mileage.py", []),
    (".claude/skills/goals-tracker/scripts/goals.py", ["list"]),
    (".claude/skills/personal-heatmap/scripts/heatmap.py", ["--output", "/tmp/test_heatmap.html", "--days", "90"]),
    (".claude/skills/matched-activities/scripts/matched.py", ["--days", "365", "--min-occurrences", "2"]),
    (".claude/skills/memory-consolidate/scripts/consolidate.py", []),
    (".claude/skills/strava-sync/scripts/sync.py", ["--level", "summary", "--days", "7"]),
]


class TestJSONContract(unittest.TestCase):
    """Every script must produce valid JSON with {success, data|error}."""

    def test_all_scripts(self):
        for path, args in ALL_SCRIPTS:
            with self.subTest(script=path):
                result = run_script(path, args)
                self.assertNotIn("_parse_error", result, f"{path}: invalid JSON")
                self.assertNotIn("_empty", result, f"{path}: no output")
                self.assertIn("success", result, f"{path}: missing 'success'")
                if result["success"]:
                    self.assertIn("data", result, f"{path}: success=true but no 'data'")
                    self.assertIsInstance(result["data"], dict, f"{path}: data is not a dict")
                else:
                    self.assertIn("error", result, f"{path}: success=false but no 'error'")
                    self.assertIsInstance(result["error"], str)
                    self.assertGreater(len(result["error"]), 5, f"{path}: error message too vague")


# ───────────────────────────────────────────────────────────────
# Cross-sport skills with strict field + range validation
# ───────────────────────────────────────────────────────────────

class TestTrainingLoad(unittest.TestCase):
    def setUp(self):
        self.result = run_script(".claude/skills/training-load/scripts/training_load.py", ["--days", "90"])
        self.assertTrue(self.result["success"])
        self.data = self.result["data"]

    def test_today_has_all_pmc_fields(self):
        for key in ("ctl", "atl", "tsb", "load", "day"):
            self.assertIn(key, self.data["today"])

    def test_tsb_equals_ctl_minus_atl(self):
        t = self.data["today"]
        self.assertAlmostEqual(t["tsb"], t["ctl"] - t["atl"], delta=0.2)

    def test_ctl_atl_non_negative(self):
        self.assertGreaterEqual(self.data["today"]["ctl"], 0)
        self.assertGreaterEqual(self.data["today"]["atl"], 0)

    def test_series_is_chronological(self):
        days = [r["day"] for r in self.data["series"]]
        self.assertEqual(days, sorted(days))

    def test_delta_7d_is_consistent(self):
        series = self.data["series"]
        if len(series) >= 8:
            today = series[-1]
            week_ago = series[-8]
            expected_delta = round(today["ctl"] - week_ago["ctl"], 1)
            self.assertAlmostEqual(self.data["delta_7d"]["ctl"], expected_delta, delta=0.2)


class TestReadiness(unittest.TestCase):
    def setUp(self):
        self.result = run_script(".claude/skills/readiness-today/scripts/readiness.py")
        self.assertTrue(self.result["success"])
        self.data = self.result["data"]

    def test_verdict_is_valid(self):
        self.assertIn(self.data["verdict"], ["GO HARD", "MODERATE", "EASY", "REST"])

    def test_numeric_fields_present_and_typed(self):
        for key in ("ctl", "atl", "tsb", "acwr", "last_48h_load"):
            self.assertIn(key, self.data)
            self.assertIsInstance(self.data[key], (int, float))

    def test_acwr_non_negative(self):
        self.assertGreaterEqual(self.data["acwr"], 0)

    def test_verdict_matches_tsb(self):
        if self.data["tsb"] < -20:
            self.assertIn(self.data["verdict"], ["REST", "EASY"])


class TestOvertraining(unittest.TestCase):
    def setUp(self):
        self.result = run_script(".claude/skills/overtraining-check/scripts/overtraining.py")
        self.assertTrue(self.result["success"])
        self.data = self.result["data"]

    def test_verdict_valid(self):
        self.assertIn(self.data["verdict"], ["RED", "YELLOW", "GREEN"])

    def test_acwr_range(self):
        self.assertGreaterEqual(self.data["acwr"], 0)
        self.assertLess(self.data["acwr"], 10)

    def test_monotony_non_negative(self):
        self.assertGreaterEqual(self.data["monotony"], 0)

    def test_red_implies_high_acwr_or_monotony(self):
        if self.data["verdict"] == "RED":
            self.assertTrue(self.data["acwr"] > 1.5 or self.data["monotony"] > 2.5)

    def test_green_implies_low_values(self):
        if self.data["verdict"] == "GREEN":
            self.assertLessEqual(self.data["acwr"], 1.3)
            self.assertLessEqual(self.data["monotony"], 2.0)


class TestPolarization(unittest.TestCase):
    def setUp(self):
        self.result = run_script(".claude/skills/polarization-check/scripts/polarization.py", ["--days", "30"])
        self.assertTrue(self.result["success"])
        self.data = self.result["data"]

    def test_percentages_sum_to_100(self):
        d = self.data["distribution"]
        total = d["easy_pct"] + d["moderate_pct"] + d["hard_pct"]
        self.assertAlmostEqual(total, 100.0, delta=0.5)

    def test_verdict_matches_distribution(self):
        if self.data["verdict"] == "POLARIZED":
            self.assertGreaterEqual(self.data["distribution"]["easy_pct"], 75)


# ───────────────────────────────────────────────────────────────
# Run skills — strict validation
# ───────────────────────────────────────────────────────────────

class TestRacePredictor(unittest.TestCase):
    def setUp(self):
        self.result = run_script(".claude/skills/run-race-predictor/scripts/race_predictor.py", ["--recent-days", "90"])
        self.assertTrue(self.result["success"])
        self.data = self.result["data"]

    def test_predictions_increase_with_distance(self):
        p = self.data["predictions_riegel"]
        self.assertLess(p["5k"]["seconds"], p["10k"]["seconds"])
        self.assertLess(p["10k"]["seconds"], p["half_marathon"]["seconds"])
        self.assertLess(p["half_marathon"]["seconds"], p["marathon"]["seconds"])

    def test_marathon_less_than_double_half(self):
        p = self.data["predictions_riegel"]
        self.assertLess(p["marathon"]["seconds"], p["half_marathon"]["seconds"] * 2.15)

    def test_vdot_positive_if_present(self):
        if self.data["vdot"] is not None:
            self.assertGreater(self.data["vdot"], 15)
            self.assertLess(self.data["vdot"], 90)

    def test_anchor_effort_has_fields(self):
        a = self.data["anchor_effort"]
        for key in ("name", "distance_m", "time", "date"):
            self.assertIn(key, a)


class TestPRTracker(unittest.TestCase):
    def setUp(self):
        self.result = run_script(".claude/skills/run-pr-tracker/scripts/pr_tracker.py")
        self.assertTrue(self.result["success"])
        self.data = self.result["data"]

    def test_prs_sorted_by_distance(self):
        distances = [p["distance_m"] for p in self.data["prs"]]
        self.assertEqual(distances, sorted(distances))

    def test_longer_distance_slower_time(self):
        prs = self.data["prs"]
        if len(prs) >= 2:
            for i in range(len(prs) - 1):
                if prs[i]["distance_m"] < prs[i + 1]["distance_m"]:
                    t1 = self._parse_time(prs[i]["time"])
                    t2 = self._parse_time(prs[i + 1]["time"])
                    self.assertLess(t1, t2, f"{prs[i]['distance_name']} should be faster than {prs[i+1]['distance_name']}")

    def test_stale_count_matches(self):
        stale = sum(1 for p in self.data["prs"] if p["stale"])
        self.assertEqual(stale, self.data["stale_count"])

    @staticmethod
    def _parse_time(s):
        parts = s.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return int(parts[0]) * 60 + int(parts[1])


class TestPaceZones(unittest.TestCase):
    def setUp(self):
        self.result = run_script(".claude/skills/run-pace-zones/scripts/pace_zones.py", ["--days", "30"])
        self.assertTrue(self.result["success"])
        self.data = self.result["data"]

    def test_five_zones_exist(self):
        self.assertEqual(len(self.data["zones"]), 5)

    def test_zones_ordered_fast_to_slow(self):
        zones = self.data["zones"]
        z5_low = zones["Z5_vo2max"]["low"]
        z1_high = zones["Z1_recovery"]["high"]
        self.assertLess(z5_low, z1_high)

    def test_distribution_sums_to_analyzed(self):
        total = sum(self.data["recent_distribution"].values())
        self.assertLessEqual(total, self.data["runs_analyzed"])


class TestDecoupling(unittest.TestCase):
    def setUp(self):
        self.result = run_script(".claude/skills/run-decoupling/scripts/decoupling.py",
                                 ["--min-minutes", "30", "--max-runs", "3"])
        self.assertTrue(self.result["success"])
        self.data = self.result["data"]

    def test_each_run_has_verdict(self):
        for r in self.data["runs"]:
            if "decoupling_pct" in r:
                self.assertIn(r["verdict"], ["GOOD", "OK", "POOR base"])

    def test_average_is_mean_of_runs(self):
        valid = [r["decoupling_pct"] for r in self.data["runs"] if "decoupling_pct" in r]
        if valid:
            expected = sum(valid) / len(valid)
            self.assertAlmostEqual(self.data["average_decoupling_pct"], expected, delta=0.1)


# ───────────────────────────────────────────────────────────────
# Cross-skill consistency
# ───────────────────────────────────────────────────────────────

class TestCrossSkillConsistency(unittest.TestCase):
    """Values that appear in multiple skills must agree."""

    def test_ctl_atl_tsb_agree_across_skills(self):
        tl = run_script(".claude/skills/training-load/scripts/training_load.py", ["--days", "90"])
        rd = run_script(".claude/skills/readiness-today/scripts/readiness.py", ["--days", "90"])
        if tl["success"] and rd["success"]:
            self.assertAlmostEqual(tl["data"]["today"]["ctl"], rd["data"]["ctl"], delta=1.0)
            self.assertAlmostEqual(tl["data"]["today"]["atl"], rd["data"]["atl"], delta=1.0)
            self.assertAlmostEqual(tl["data"]["today"]["tsb"], rd["data"]["tsb"], delta=1.0)

    def test_pr_tracker_and_race_predictor_use_same_anchor(self):
        prs = run_script(".claude/skills/run-pr-tracker/scripts/pr_tracker.py")
        pred = run_script(".claude/skills/run-race-predictor/scripts/race_predictor.py", ["--recent-days", "365"])
        if prs["success"] and pred["success"]:
            anchor_dist = pred["data"]["anchor_effort"]["distance_m"]
            pr_distances = [p["distance_m"] for p in prs["data"]["prs"]]
            self.assertIn(anchor_dist, pr_distances)


# ───────────────────────────────────────────────────────────────
# No-data skills: graceful failure
# ───────────────────────────────────────────────────────────────

class TestNoDataSkills(unittest.TestCase):
    EXPECTED_FAILURES = [
        (".claude/skills/ride-power-curve/scripts/power_curve.py", ["--days", "90"], "ride"),
        (".claude/skills/ride-ftp-estimate/scripts/ftp_estimate.py", ["--days", "90"], "ride"),
        (".claude/skills/ride-climbing/scripts/climbing.py", ["--days", "90"], "ride"),
        (".claude/skills/ride-tss-load/scripts/ride_tss.py", ["--days", "30", "--ftp", "200"], "ride"),
        (".claude/skills/swim-swolf/scripts/swim_swolf.py", ["--days", "60"], "swim"),
        (".claude/skills/swim-volume/scripts/swim_volume.py", ["--weeks", "12"], "swim"),
    ]

    def test_graceful_failures(self):
        for path, args, keyword in self.EXPECTED_FAILURES:
            with self.subTest(script=path):
                result = run_script(path, args)
                self.assertFalse(result["success"], f"{path} should fail with no {keyword} data")
                self.assertIn(keyword, result["error"].lower())


# ───────────────────────────────────────────────────────────────
# Pure calculators (no Strava needed)
# ───────────────────────────────────────────────────────────────

class TestPureCalculators(unittest.TestCase):
    def test_swim_css_output(self):
        result = run_script(".claude/skills/swim-css/scripts/swim_css.py", ["--t400", "6:20", "--t200", "2:55"])
        self.assertTrue(result["success"])
        d = result["data"]
        self.assertGreater(d["css_m_per_s"], 0.5)
        self.assertLess(d["css_m_per_s"], 2.5)
        for pace_key in ("endurance", "threshold", "vo2max"):
            self.assertIn(pace_key, d["training_paces_per_100m"])

    def test_swim_css_invalid_inputs(self):
        result = run_script(".claude/skills/swim-css/scripts/swim_css.py", ["--t400", "2:00", "--t200", "3:00"])
        self.assertFalse(result["success"])

    def test_memory_consolidate(self):
        result = run_script(".claude/skills/memory-consolidate/scripts/consolidate.py")
        self.assertTrue(result["success"])
        d = result["data"]
        self.assertIsInstance(d["memories"], list)
        self.assertIsInstance(d["findings"], list)
        for m in d["memories"]:
            self.assertIn("type", m)
            self.assertIn(m["type"], ("user", "feedback", "project", "reference", "unknown"))


if __name__ == "__main__":
    unittest.main()
