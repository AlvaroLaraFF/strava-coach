"""Shape + read-only assertions for the webapp backend service layer.

Runs against the local strava_coach.db (read-only). Skips gracefully when the
DB has no data so the suite still passes on a fresh checkout.
"""
import os
import sqlite3
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from strava.client import get_default_db_path  # noqa: E402
from webapp.backend import downsample, service  # noqa: E402

HAS_DATA = os.path.exists(get_default_db_path())


def _counts():
    con = sqlite3.connect(get_default_db_path())
    try:
        snaps = con.execute("SELECT COUNT(*) FROM athlete_snapshots").fetchone()[0]
        completed = con.execute(
            "SELECT COUNT(*) FROM planned_sessions WHERE status='completed'"
        ).fetchone()[0]
        return snaps, completed
    finally:
        con.close()


def test_health():
    h = service.health()
    assert h["status"] == "ok"
    assert "db" in h


def test_dashboard_shape():
    d = service.dashboard()
    assert set(["snapshot", "tsb_verdict", "next_session", "recent"]).issubset(d)
    assert isinstance(d["recent"], list)


def test_activities_shape():
    a = service.activities(days=365)
    assert "activities" in a and isinstance(a["activities"], list)
    if a["activities"]:
        first = a["activities"][0]
        for key in ("strava_id", "name", "sport_type", "start_date"):
            assert key in first


def test_calendar_is_read_only():
    """Calling calendar() must NOT mutate the DB (no auto-match writes)."""
    if not HAS_DATA:
        pytest.skip("no DB")
    before = _counts()
    service.calendar("2026-06-01", "2026-07-31")
    after = _counts()
    assert before == after, "calendar() must not write to the DB"


def test_evolution_shape():
    e = service.evolution(days=120)
    assert "pmc" in e and isinstance(e["pmc"], list)
    assert "snapshot_history" in e
    if e["pmc"]:
        assert set(["day", "ctl", "atl", "tsb"]).issubset(e["pmc"][0])


def test_prs_shape():
    p = service.prs()
    assert "prs" in p and isinstance(p["prs"], list)


def test_downsample_index_aligned():
    streams = {
        "time": {"data": list(range(1000)), "series_type": "distance",
                 "original_size": 1000, "resolution": "high"},
        "hr": {"data": list(range(1000)), "series_type": "distance",
               "original_size": 1000, "resolution": "high"},
    }
    out = downsample.decimate_streams(streams, target=100)
    assert len(out["time"]["data"]) == 100
    assert len(out["hr"]["data"]) == 100
    # same index map applied to every channel
    assert out["time"]["data"] == out["hr"]["data"]
