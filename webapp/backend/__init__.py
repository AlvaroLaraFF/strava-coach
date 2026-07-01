"""Read-only local web API for strava-coach.

The backend reuses the same SQLite DB and the analytics/db helpers under
``strava/``. It never writes to the DB: only GET endpoints exist, calendar
adherence is recomputed in memory (no auto-match), and snapshots are read
(or computed without persisting). See webapp/backend/server.py.
"""
