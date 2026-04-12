"""Incremental sync helpers — used by skills that need streams/laps/zones on demand."""

import json
import time
from datetime import datetime, timedelta, timezone

from strava.client import StravaClient
from strava.db import (
    get_all_activities,
    has_streams,
    load_athlete_zones,
    save_athlete_zones,
    save_laps,
    save_streams,
    upsert_activities,
    upsert_best_efforts,
)


def ensure_streams(client: StravaClient, db_path: str, strava_id: int) -> dict:
    """Fetch streams from API only if not already cached. Returns the streams dict."""
    from strava.db import load_streams
    cached = load_streams(db_path, strava_id)
    if cached is not None:
        return cached
    streams = client.get_streams(strava_id)
    save_streams(db_path, strava_id, streams)
    return streams


def ensure_laps(client: StravaClient, db_path: str, strava_id: int) -> list:
    from strava.db import load_laps
    cached = load_laps(db_path, strava_id)
    if cached is not None:
        return cached
    laps = client.get_laps(strava_id)
    save_laps(db_path, strava_id, laps)
    return laps


def ensure_athlete_zones(client: StravaClient, db_path: str, athlete_id: int) -> dict:
    cached = load_athlete_zones(db_path, athlete_id)
    if cached is not None:
        return cached
    zones = client.get_athlete_zones()
    save_athlete_zones(db_path, athlete_id, zones)
    return zones


def extract_best_efforts_from_activity(db_path: str, activity_row: dict) -> int:
    """Parse best_efforts from a stored activity's raw_json into the dedicated table."""
    raw = activity_row.get("raw_json")
    if not raw:
        return 0
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return 0
    efforts = payload.get("best_efforts") or []
    if not efforts:
        return 0
    return upsert_best_efforts(
        db_path,
        activity_row["strava_id"],
        activity_row["athlete_id"],
        efforts,
    )


def backfill_best_efforts(db_path: str) -> int:
    """Walk all stored activities and extract best_efforts into the dedicated table."""
    total = 0
    for act in get_all_activities(db_path):
        total += extract_best_efforts_from_activity(db_path, act)
    return total


# ---------------------------------------------------------------------------
# Bulk sync orchestration
# ---------------------------------------------------------------------------

def _latest_activity_epoch(db_path: str) -> int | None:
    """Return epoch timestamp of the most recent activity, or None if DB is empty."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT MAX(start_date) FROM activities").fetchone()
        if row and row[0]:
            dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            return int(dt.timestamp())
        return None
    finally:
        conn.close()


def sync_summary(client: StravaClient, db_path: str, days: int | None = None,
                 max_pages: int = 50, per_page: int = 100,
                 full: bool = False) -> int:
    """Fetch summary activities from /athlete/activities, paginated.

    Sync modes (in priority order):
    - ``days=N``: explicit window — fetch last N days.
    - ``full=True``: fetch entire history from the beginning.
    - Neither (default): **auto-incremental** — if the DB already has
      activities, fetch only newer ones (with a 2-day overlap buffer);
      if the DB is empty, fetch everything.

    Returns total inserted/updated.
    """
    after = None
    if days:
        after = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    elif not full:
        latest = _latest_activity_epoch(db_path)
        if latest:
            after = latest - 2 * 86400  # 2-day overlap buffer
        # else: DB empty → after stays None → fetch everything
    total = 0
    for page in range(1, max_pages + 1):
        batch = client.get_activities(per_page=per_page, page=page, after=after)
        if not batch:
            break
        total += upsert_activities(db_path, batch)
        if len(batch) < per_page:
            break
        time.sleep(0.5)
    return total


def sync_activity_details(client: StravaClient, db_path: str,
                          limit: int | None = None,
                          force: bool = False,
                          sleep_s: float = 0.7) -> dict:
    """Fetch /activities/{id} for stored activities and update raw_json with the
    detailed payload (best_efforts, splits, weighted_average_watts, etc.).

    By default, only activities whose raw_json doesn't already contain
    best_efforts (i.e. summary-only) are upgraded. Pass force=True to refresh all.
    """
    activities = get_all_activities(db_path)
    activities.sort(key=lambda a: a.get("start_date") or "", reverse=True)

    upgraded = 0
    skipped = 0
    failed = 0
    best_efforts_extracted = 0

    for a in activities:
        if limit is not None and upgraded >= limit:
            break

        if not force:
            try:
                payload = json.loads(a.get("raw_json") or "{}")
            except (TypeError, ValueError):
                payload = {}
            if "best_efforts" in payload or payload.get("resource_state") == 3:
                skipped += 1
                continue

        try:
            detailed = client.get_activity(a["strava_id"])
        except Exception:
            failed += 1
            time.sleep(sleep_s)
            continue

        upsert_activities(db_path, [detailed])
        efforts = detailed.get("best_efforts") or []
        if efforts:
            best_efforts_extracted += upsert_best_efforts(
                db_path, a["strava_id"], a["athlete_id"], efforts
            )
        upgraded += 1
        time.sleep(sleep_s)

    return {
        "upgraded": upgraded,
        "skipped": skipped,
        "failed": failed,
        "best_efforts_rows": best_efforts_extracted,
    }


def sync_streams_bulk(client: StravaClient, db_path: str,
                      sport_types: set[str] | None = None,
                      limit: int | None = None,
                      sleep_s: float = 0.7) -> dict:
    """Fetch streams for activities that don't have them yet."""
    activities = get_all_activities(db_path)
    activities.sort(key=lambda a: a.get("start_date") or "", reverse=True)

    fetched = 0
    skipped = 0
    failed = 0

    for a in activities:
        if limit is not None and fetched >= limit:
            break
        if sport_types and a.get("sport_type") not in sport_types:
            continue
        if has_streams(db_path, a["strava_id"]):
            skipped += 1
            continue
        try:
            streams = client.get_streams(a["strava_id"])
            save_streams(db_path, a["strava_id"], streams)
            fetched += 1
        except Exception:
            failed += 1
        time.sleep(sleep_s)

    return {"fetched": fetched, "skipped": skipped, "failed": failed}


def sync_athlete_zones_now(client: StravaClient, db_path: str, athlete_id: int) -> dict:
    zones = client.get_athlete_zones()
    save_athlete_zones(db_path, athlete_id, zones)
    return zones
