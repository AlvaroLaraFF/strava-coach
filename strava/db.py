"""SQLite database management for strava-coach."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str) -> None:
    """Create tables if they don't exist. Idempotent."""
    conn = _connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                athlete_id     INTEGER PRIMARY KEY,
                access_token   TEXT    NOT NULL,
                refresh_token  TEXT    NOT NULL,
                expires_at     INTEGER NOT NULL,
                scope          TEXT,
                updated_at     TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS activities (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                strava_id       INTEGER UNIQUE NOT NULL,
                athlete_id      INTEGER NOT NULL,
                name            TEXT,
                sport_type      TEXT,
                start_date      TEXT,
                distance        REAL,
                moving_time     INTEGER,
                elapsed_time    INTEGER,
                total_elevation REAL,
                average_speed   REAL,
                max_speed       REAL,
                average_hr      REAL,
                max_hr          REAL,
                average_watts   REAL,
                kilojoules      REAL,
                kudos_count     INTEGER,
                raw_json        TEXT,
                synced_at       TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS athlete_stats (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                athlete_id     INTEGER NOT NULL,
                fetched_at     TEXT DEFAULT (datetime('now')),
                ytd_run_m      REAL,
                ytd_ride_m     REAL,
                ytd_swim_m     REAL,
                all_run_m      REAL,
                all_ride_m     REAL,
                all_swim_m     REAL,
                raw_json       TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_activities_start_date
                ON activities(start_date DESC);
            CREATE INDEX IF NOT EXISTS idx_activities_sport_type
                ON activities(sport_type);

            CREATE TABLE IF NOT EXISTS activity_streams (
                strava_id   INTEGER PRIMARY KEY,
                json_data   TEXT NOT NULL,
                fetched_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS activity_laps (
                strava_id   INTEGER PRIMARY KEY,
                json_data   TEXT NOT NULL,
                fetched_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS athlete_zones (
                athlete_id  INTEGER PRIMARY KEY,
                json_data   TEXT NOT NULL,
                fetched_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS best_efforts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                strava_id       INTEGER NOT NULL,
                athlete_id      INTEGER NOT NULL,
                effort_name     TEXT NOT NULL,
                distance        REAL NOT NULL,
                elapsed_time    INTEGER NOT NULL,
                start_date      TEXT NOT NULL,
                UNIQUE(strava_id, effort_name)
            );
            CREATE INDEX IF NOT EXISTS idx_best_efforts_distance
                ON best_efforts(distance);

            CREATE TABLE IF NOT EXISTS daily_load (
                athlete_id  INTEGER NOT NULL,
                day         TEXT NOT NULL,
                load        REAL NOT NULL,
                PRIMARY KEY (athlete_id, day)
            );

            CREATE TABLE IF NOT EXISTS goals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                athlete_id  INTEGER NOT NULL,
                metric      TEXT NOT NULL,
                period      TEXT NOT NULL,
                sport_type  TEXT,
                target      REAL NOT NULL,
                start_date  TEXT NOT NULL,
                end_date    TEXT NOT NULL,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS user_profile (
                athlete_id  INTEGER PRIMARY KEY,
                name        TEXT,
                height_cm   REAL,
                weight_kg   REAL,
                gender      TEXT,
                birth_date  TEXT,
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS athlete_snapshots (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                athlete_id              INTEGER NOT NULL,
                captured_at             TEXT NOT NULL DEFAULT (datetime('now')),
                source                  TEXT,

                -- Tier 1: Input parameters
                ftp_w                   REAL,
                hr_max_bpm              REAL,
                hr_rest_bpm             REAL,
                vdot                    REAL,
                threshold_pace_min_km   REAL,
                css_m_s                 REAL,
                weight_kg               REAL,

                -- Tier 2: Load state indicators
                ctl                     REAL,
                atl                     REAL,
                tsb                     REAL,
                acwr                    REAL,
                monotony                REAL,
                strain                  REAL,

                -- Tier 1b: Derived physiological parameters
                lthr_bpm                REAL,

                -- Tier 3: Trend markers
                avg_decoupling_pct      REAL,
                avg_cadence_spm         REAL
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_athlete_date
                ON athlete_snapshots(athlete_id, captured_at DESC);

        """)
        conn.commit()
    finally:
        conn.close()


# --- Tokens ---

def save_token(db_path: str, token_data: dict) -> None:
    """Upsert into oauth_tokens."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO oauth_tokens
               (athlete_id, access_token, refresh_token, expires_at, scope, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (
                token_data["athlete_id"],
                token_data["access_token"],
                token_data["refresh_token"],
                token_data["expires_at"],
                token_data.get("scope", ""),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_token(db_path: str) -> dict | None:
    """Return the stored token or None if not found."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM oauth_tokens ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# --- Activities ---

def upsert_activities(db_path: str, activities: list[dict]) -> int:
    """Insert or update activities. Returns the number of affected rows."""
    conn = _connect(db_path)
    count = 0
    try:
        for act in activities:
            conn.execute(
                """INSERT OR REPLACE INTO activities
                   (strava_id, athlete_id, name, sport_type, start_date,
                    distance, moving_time, elapsed_time, total_elevation,
                    average_speed, max_speed, average_hr, max_hr,
                    average_watts, kilojoules, kudos_count, raw_json, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    act["id"],
                    act.get("athlete", {}).get("id"),
                    act.get("name"),
                    act.get("sport_type") or act.get("type"),
                    act.get("start_date"),
                    act.get("distance"),
                    act.get("moving_time"),
                    act.get("elapsed_time"),
                    act.get("total_elevation_gain"),
                    act.get("average_speed"),
                    act.get("max_speed"),
                    act.get("average_heartrate"),
                    act.get("max_heartrate"),
                    act.get("average_watts"),
                    act.get("kilojoules"),
                    act.get("kudos_count"),
                    json.dumps(act, ensure_ascii=False),
                ),
            )
            count += 1
        conn.commit()
    finally:
        conn.close()
    return count


def get_recent_activities(
    db_path: str, limit: int = 20, sport_type: str | None = None
) -> list[dict]:
    """Recent activities sorted by date descending."""
    conn = _connect(db_path)
    try:
        query = "SELECT * FROM activities"
        params: list = []
        if sport_type:
            query += " WHERE sport_type = ?"
            params.append(sport_type)
        query += " ORDER BY start_date DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_activities_range(db_path: str, days: int = 90) -> list[dict]:
    """Activities from the last N days."""
    conn = _connect(db_path)
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = conn.execute(
            "SELECT * FROM activities WHERE start_date >= ? ORDER BY start_date DESC",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Athlete Stats ---

def save_athlete_stats(db_path: str, athlete_id: int, stats: dict) -> None:
    """Insert a stats snapshot."""
    conn = _connect(db_path)
    try:
        ytd_run = stats.get("ytd_run_totals", {})
        ytd_ride = stats.get("ytd_ride_totals", {})
        ytd_swim = stats.get("ytd_swim_totals", {})
        all_run = stats.get("all_run_totals", {})
        all_ride = stats.get("all_ride_totals", {})
        all_swim = stats.get("all_swim_totals", {})

        conn.execute(
            """INSERT INTO athlete_stats
               (athlete_id, ytd_run_m, ytd_ride_m, ytd_swim_m,
                all_run_m, all_ride_m, all_swim_m, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                athlete_id,
                ytd_run.get("distance", 0),
                ytd_ride.get("distance", 0),
                ytd_swim.get("distance", 0),
                all_run.get("distance", 0),
                all_ride.get("distance", 0),
                all_swim.get("distance", 0),
                json.dumps(stats, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_stats(db_path: str, athlete_id: int) -> dict | None:
    """Return the latest stats snapshot."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM athlete_stats WHERE athlete_id = ? ORDER BY fetched_at DESC LIMIT 1",
            (athlete_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# --- Streams ---

def save_streams(db_path: str, strava_id: int, streams: dict) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO activity_streams (strava_id, json_data, fetched_at)
               VALUES (?, ?, datetime('now'))""",
            (strava_id, json.dumps(streams, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def load_streams(db_path: str, strava_id: int) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT json_data FROM activity_streams WHERE strava_id = ?",
            (strava_id,),
        ).fetchone()
        return json.loads(row["json_data"]) if row else None
    finally:
        conn.close()


def has_streams(db_path: str, strava_id: int) -> bool:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM activity_streams WHERE strava_id = ?", (strava_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# --- Laps ---

def save_laps(db_path: str, strava_id: int, laps: list) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO activity_laps (strava_id, json_data, fetched_at)
               VALUES (?, ?, datetime('now'))""",
            (strava_id, json.dumps(laps, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def load_laps(db_path: str, strava_id: int) -> list | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT json_data FROM activity_laps WHERE strava_id = ?", (strava_id,)
        ).fetchone()
        return json.loads(row["json_data"]) if row else None
    finally:
        conn.close()


# --- Athlete zones ---

def save_athlete_zones(db_path: str, athlete_id: int, zones: dict) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO athlete_zones (athlete_id, json_data, fetched_at)
               VALUES (?, ?, datetime('now'))""",
            (athlete_id, json.dumps(zones, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def load_athlete_zones(db_path: str, athlete_id: int) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT json_data FROM athlete_zones WHERE athlete_id = ?", (athlete_id,)
        ).fetchone()
        return json.loads(row["json_data"]) if row else None
    finally:
        conn.close()


# --- Best efforts ---

def upsert_best_efforts(db_path: str, strava_id: int, athlete_id: int, efforts: list) -> int:
    if not efforts:
        return 0
    conn = _connect(db_path)
    count = 0
    try:
        for eff in efforts:
            conn.execute(
                """INSERT OR REPLACE INTO best_efforts
                   (strava_id, athlete_id, effort_name, distance, elapsed_time, start_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    strava_id,
                    athlete_id,
                    eff.get("name"),
                    eff.get("distance"),
                    eff.get("elapsed_time"),
                    eff.get("start_date"),
                ),
            )
            count += 1
        conn.commit()
    finally:
        conn.close()
    return count


def get_best_efforts_pr(db_path: str, athlete_id: int) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT be.effort_name, be.distance, be.elapsed_time AS pr_time,
                      be.strava_id, be.start_date
               FROM best_efforts be
               INNER JOIN (
                   SELECT effort_name, MIN(elapsed_time) AS min_time
                   FROM best_efforts
                   WHERE athlete_id = ?
                   GROUP BY effort_name
               ) sub ON be.effort_name = sub.effort_name
                     AND be.elapsed_time = sub.min_time
               WHERE be.athlete_id = ?
               ORDER BY be.distance ASC""",
            (athlete_id, athlete_id),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Daily load (PMC) ---

def upsert_daily_load(db_path: str, athlete_id: int, day: str, load: float) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO daily_load (athlete_id, day, load)
               VALUES (?, ?, ?)""",
            (athlete_id, day, load),
        )
        conn.commit()
    finally:
        conn.close()


def get_daily_load(db_path: str, athlete_id: int, days: int = 120) -> list[dict]:
    conn = _connect(db_path)
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT day, load FROM daily_load
               WHERE athlete_id = ? AND day >= ?
               ORDER BY day ASC""",
            (athlete_id, cutoff),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Goals ---

def add_goal(
    db_path: str,
    athlete_id: int,
    metric: str,
    period: str,
    sport_type: str | None,
    target: float,
    start_date: str,
    end_date: str,
) -> int:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO goals
               (athlete_id, metric, period, sport_type, target, start_date, end_date)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (athlete_id, metric, period, sport_type, target, start_date, end_date),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_goals(db_path: str, athlete_id: int) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT * FROM goals WHERE athlete_id = ?
               AND date(end_date) >= date('now')
               ORDER BY end_date ASC""",
            (athlete_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- User profile ---

def save_user_profile(db_path: str, athlete_id: int, profile: dict) -> None:
    """Upsert user profile fields. Only updates non-None values."""
    conn = _connect(db_path)
    try:
        existing = conn.execute(
            "SELECT * FROM user_profile WHERE athlete_id = ?", (athlete_id,)
        ).fetchone()
        if existing:
            existing = dict(existing)
            merged = {
                "name": profile.get("name") or existing.get("name"),
                "height_cm": profile.get("height_cm") or existing.get("height_cm"),
                "weight_kg": profile.get("weight_kg") or existing.get("weight_kg"),
                "gender": profile.get("gender") or existing.get("gender"),
                "birth_date": profile.get("birth_date") or existing.get("birth_date"),
            }
            conn.execute(
                """UPDATE user_profile
                   SET name = ?, height_cm = ?, weight_kg = ?, gender = ?,
                       birth_date = ?, updated_at = datetime('now')
                   WHERE athlete_id = ?""",
                (merged["name"], merged["height_cm"], merged["weight_kg"],
                 merged["gender"], merged["birth_date"], athlete_id),
            )
        else:
            conn.execute(
                """INSERT INTO user_profile
                   (athlete_id, name, height_cm, weight_kg, gender, birth_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (athlete_id, profile.get("name"), profile.get("height_cm"),
                 profile.get("weight_kg"), profile.get("gender"),
                 profile.get("birth_date")),
            )
        conn.commit()
    finally:
        conn.close()


def load_user_profile(db_path: str, athlete_id: int | None = None) -> dict | None:
    """Return the user profile or None. If athlete_id is None, returns the first profile found.

    Returns None gracefully if the user_profile table does not exist yet.
    """
    conn = _connect(db_path)
    try:
        if athlete_id:
            row = conn.execute(
                "SELECT * FROM user_profile WHERE athlete_id = ?", (athlete_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM user_profile ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def get_all_activities(db_path: str, athlete_id: int | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        if athlete_id:
            rows = conn.execute(
                "SELECT * FROM activities WHERE athlete_id = ? ORDER BY start_date ASC",
                (athlete_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM activities ORDER BY start_date ASC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Athlete snapshots ---

_SNAPSHOT_METRICS = [
    "ftp_w", "hr_max_bpm", "hr_rest_bpm", "vdot", "threshold_pace_min_km",
    "css_m_s", "weight_kg", "lthr_bpm", "ctl", "atl", "tsb", "acwr",
    "monotony", "strain", "avg_decoupling_pct", "avg_cadence_spm",
]


def get_latest_snapshot(db_path: str, athlete_id: int) -> dict | None:
    """Return the most recent snapshot row, or None."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM athlete_snapshots WHERE athlete_id = ? ORDER BY captured_at DESC LIMIT 1",
            (athlete_id,),
        ).fetchone()
        return dict(row) if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def upsert_athlete_snapshot(
    db_path: str, athlete_id: int, source: str, metrics: dict
) -> int:
    """Insert a new snapshot merging provided metrics with the previous one.

    Only the keys present in *metrics* are overwritten; all other columns
    carry forward from the latest existing snapshot so partial updates don't
    lose data.  Returns the new row id.
    """
    previous = get_latest_snapshot(db_path, athlete_id)
    merged = {}
    for col in _SNAPSHOT_METRICS:
        if col in metrics and metrics[col] is not None:
            merged[col] = metrics[col]
        elif previous and previous.get(col) is not None:
            merged[col] = previous[col]
        else:
            merged[col] = None

    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO athlete_snapshots
               (athlete_id, source, ftp_w, hr_max_bpm, hr_rest_bpm, vdot,
                threshold_pace_min_km, css_m_s, weight_kg, lthr_bpm,
                ctl, atl, tsb, acwr, monotony, strain,
                avg_decoupling_pct, avg_cadence_spm)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                athlete_id,
                source,
                merged["ftp_w"],
                merged["hr_max_bpm"],
                merged["hr_rest_bpm"],
                merged["vdot"],
                merged["threshold_pace_min_km"],
                merged["css_m_s"],
                merged["weight_kg"],
                merged["lthr_bpm"],
                merged["ctl"],
                merged["atl"],
                merged["tsb"],
                merged["acwr"],
                merged["monotony"],
                merged["strain"],
                merged["avg_decoupling_pct"],
                merged["avg_cadence_spm"],
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_snapshot_history(
    db_path: str, athlete_id: int, limit: int = 30
) -> list[dict]:
    """Return the last *limit* snapshots ordered by captured_at DESC."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT * FROM athlete_snapshots
               WHERE athlete_id = ?
               ORDER BY captured_at DESC LIMIT ?""",
            (athlete_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
