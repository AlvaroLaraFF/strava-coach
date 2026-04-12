#!/usr/bin/env python3
"""Unit tests for strava/db.py — uses a temp in-memory DB."""

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from strava.db import (
    add_goal,
    get_activities_range,
    get_all_activities,
    get_best_efforts_pr,
    get_latest_stats,
    get_recent_activities,
    has_streams,
    init_db,
    list_goals,
    load_athlete_zones,
    load_laps,
    load_streams,
    load_token,
    save_athlete_stats,
    save_athlete_zones,
    save_laps,
    save_streams,
    save_token,
    upsert_activities,
    upsert_best_efforts,
    upsert_daily_load,
    get_daily_load,
)


class TestDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = self.tmp.name
        self.tmp.close()
        init_db(self.db)

    def tearDown(self):
        os.unlink(self.db)

    def test_init_idempotent(self):
        init_db(self.db)
        init_db(self.db)

    def test_token_roundtrip(self):
        save_token(self.db, {
            "athlete_id": 123,
            "access_token": "abc",
            "refresh_token": "def",
            "expires_at": 9999999999,
        })
        token = load_token(self.db)
        self.assertIsNotNone(token)
        self.assertEqual(token["athlete_id"], 123)
        self.assertEqual(token["access_token"], "abc")

    def test_token_none(self):
        self.assertIsNone(load_token(self.db))

    def test_upsert_activities(self):
        acts = [
            {"id": 1, "athlete": {"id": 10}, "name": "Run", "sport_type": "Run",
             "start_date": "2026-04-01T00:00:00Z", "distance": 5000,
             "moving_time": 1800, "elapsed_time": 1900,
             "total_elevation_gain": 50, "average_speed": 2.7,
             "max_speed": 3.5, "average_heartrate": 150,
             "max_heartrate": 175, "average_watts": None,
             "kilojoules": None, "kudos_count": 3},
        ]
        count = upsert_activities(self.db, acts)
        self.assertEqual(count, 1)
        recent = get_recent_activities(self.db, limit=5)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["name"], "Run")

    def test_upsert_replaces(self):
        act = {"id": 1, "athlete": {"id": 10}, "name": "v1", "sport_type": "Run",
               "start_date": "2026-04-01T00:00:00Z", "distance": 5000,
               "moving_time": 1800, "elapsed_time": 1900,
               "total_elevation_gain": 0, "average_speed": 0,
               "max_speed": 0, "average_heartrate": 0, "max_heartrate": 0,
               "average_watts": None, "kilojoules": None, "kudos_count": 0}
        upsert_activities(self.db, [act])
        act["name"] = "v2"
        upsert_activities(self.db, [act])
        recent = get_recent_activities(self.db, limit=5)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["name"], "v2")

    def test_get_activities_range(self):
        upsert_activities(self.db, [
            {"id": 1, "athlete": {"id": 10}, "name": "old", "sport_type": "Run",
             "start_date": "2020-01-01T00:00:00Z", "distance": 1000,
             "moving_time": 600, "elapsed_time": 600,
             "total_elevation_gain": 0, "average_speed": 0, "max_speed": 0,
             "average_heartrate": 0, "max_heartrate": 0,
             "average_watts": None, "kilojoules": None, "kudos_count": 0},
        ])
        recent = get_activities_range(self.db, days=30)
        self.assertEqual(len(recent), 0)

    def test_sport_filter(self):
        upsert_activities(self.db, [
            {"id": 1, "athlete": {"id": 10}, "name": "run", "sport_type": "Run",
             "start_date": "2026-04-01T00:00:00Z", "distance": 5000,
             "moving_time": 1800, "elapsed_time": 1900,
             "total_elevation_gain": 0, "average_speed": 0, "max_speed": 0,
             "average_heartrate": 0, "max_heartrate": 0,
             "average_watts": None, "kilojoules": None, "kudos_count": 0},
            {"id": 2, "athlete": {"id": 10}, "name": "ride", "sport_type": "Ride",
             "start_date": "2026-04-01T00:00:00Z", "distance": 30000,
             "moving_time": 3600, "elapsed_time": 3700,
             "total_elevation_gain": 0, "average_speed": 0, "max_speed": 0,
             "average_heartrate": 0, "max_heartrate": 0,
             "average_watts": None, "kilojoules": None, "kudos_count": 0},
        ])
        runs = get_recent_activities(self.db, limit=10, sport_type="Run")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["name"], "run")

    def test_streams_roundtrip(self):
        self.assertFalse(has_streams(self.db, 999))
        save_streams(self.db, 999, {"heartrate": {"data": [140, 145]}})
        self.assertTrue(has_streams(self.db, 999))
        loaded = load_streams(self.db, 999)
        self.assertEqual(loaded["heartrate"]["data"], [140, 145])

    def test_laps_roundtrip(self):
        self.assertIsNone(load_laps(self.db, 888))
        save_laps(self.db, 888, [{"lap_index": 1, "elapsed_time": 300}])
        loaded = load_laps(self.db, 888)
        self.assertEqual(len(loaded), 1)

    def test_athlete_zones_roundtrip(self):
        self.assertIsNone(load_athlete_zones(self.db, 10))
        save_athlete_zones(self.db, 10, {"heart_rate": {"zones": []}})
        loaded = load_athlete_zones(self.db, 10)
        self.assertIn("heart_rate", loaded)

    def test_best_efforts(self):
        efforts = [
            {"name": "5K", "distance": 5000, "elapsed_time": 1500, "start_date": "2026-04-01"},
            {"name": "1K", "distance": 1000, "elapsed_time": 300, "start_date": "2026-04-01"},
        ]
        upsert_best_efforts(self.db, 1, 10, efforts)
        prs = get_best_efforts_pr(self.db, 10)
        self.assertEqual(len(prs), 2)
        five_k = next(p for p in prs if p["effort_name"] == "5K")
        self.assertEqual(five_k["pr_time"], 1500)

    def test_best_efforts_updates_pr(self):
        upsert_best_efforts(self.db, 1, 10, [
            {"name": "5K", "distance": 5000, "elapsed_time": 1500, "start_date": "2026-04-01"},
        ])
        upsert_best_efforts(self.db, 2, 10, [
            {"name": "5K", "distance": 5000, "elapsed_time": 1400, "start_date": "2026-04-10"},
        ])
        prs = get_best_efforts_pr(self.db, 10)
        five_k = next(p for p in prs if p["effort_name"] == "5K")
        self.assertEqual(five_k["pr_time"], 1400)

    def test_daily_load(self):
        upsert_daily_load(self.db, 10, "2026-04-01", 85.5)
        upsert_daily_load(self.db, 10, "2026-04-02", 0.0)
        loads = get_daily_load(self.db, 10, days=30)
        self.assertEqual(len(loads), 2)

    def test_goals_crud(self):
        gid = add_goal(self.db, 10, "distance", "year", "Run", 1500, "2026-01-01", "2026-12-31")
        self.assertIsNotNone(gid)
        goals = list_goals(self.db, 10)
        self.assertEqual(len(goals), 1)
        self.assertEqual(goals[0]["target"], 1500)

    def test_stats_roundtrip(self):
        save_athlete_stats(self.db, 10, {
            "ytd_run_totals": {"distance": 500000},
            "ytd_ride_totals": {"distance": 0},
            "ytd_swim_totals": {"distance": 0},
            "all_run_totals": {"distance": 2000000},
            "all_ride_totals": {"distance": 0},
            "all_swim_totals": {"distance": 0},
        })
        stats = get_latest_stats(self.db, 10)
        self.assertIsNotNone(stats)
        self.assertEqual(stats["ytd_run_m"], 500000)

    def test_get_all_activities(self):
        upsert_activities(self.db, [
            {"id": 1, "athlete": {"id": 10}, "name": "A", "sport_type": "Run",
             "start_date": "2026-04-01T00:00:00Z", "distance": 5000,
             "moving_time": 1800, "elapsed_time": 1800,
             "total_elevation_gain": 0, "average_speed": 0, "max_speed": 0,
             "average_heartrate": 0, "max_heartrate": 0,
             "average_watts": None, "kilojoules": None, "kudos_count": 0},
        ])
        all_acts = get_all_activities(self.db)
        self.assertEqual(len(all_acts), 1)
        by_athlete = get_all_activities(self.db, athlete_id=10)
        self.assertEqual(len(by_athlete), 1)
        by_other = get_all_activities(self.db, athlete_id=99)
        self.assertEqual(len(by_other), 0)


if __name__ == "__main__":
    unittest.main()
