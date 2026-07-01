#!/usr/bin/env python3
"""Open Strava in the default browser so the athlete can export a file by hand.

This helper only OPENS a URL in the user's browser -- exactly like clicking a
bookmark. It does not log in, navigate, scrape, collect or download any data:
the login, the navigation and the export click are all performed by the human.

Strava's Terms of Service prohibit automated access to or collection of data
from the service "by any means, including ... scripts ... crawlers ...
regardless of whether you are logged in". This script stays strictly on the
navigation side of that line -- it launches a page and stops.

Usage:
    # Open the training log (list of your activities)
    python3 open_export.py

    # Open a specific activity page (where the "..." > Export GPX menu lives)
    python3 open_export.py --activity-id 18968005660
"""
import argparse
import webbrowser

TRAINING_URL = "https://www.strava.com/athlete/training"
ACTIVITY_URL = "https://www.strava.com/activities/{activity_id}"

MANUAL_STEPS = """
Manual export (you do this -- Strava requires a human at the browser):
  1. Log in if prompted, then find/open the activity you want.
  2. Click the '...' (more) menu on the activity > 'Export GPX'.
     Tip: adding '/export_tcx' to the activity URL gives HR + cadence + laps,
     which is the richest file for session analysis.
  3. Save the downloaded file. It is then ready to be imported into the DB.
"""


def build_url(activity_id: int | None) -> str:
    if activity_id is not None:
        return ACTIVITY_URL.format(activity_id=activity_id)
    return TRAINING_URL


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open Strava in the browser for a manual (human) export."
    )
    parser.add_argument(
        "--activity-id",
        type=int,
        default=None,
        help="Open this activity's page instead of the training log.",
    )
    args = parser.parse_args()

    url = build_url(args.activity_id)
    print(f"Opening in your browser: {url}")

    opened = webbrowser.open(url, new=2)  # new=2 => new tab when possible
    if not opened:
        print("Could not launch a browser automatically.")
        print(f"Open this URL manually: {url}")

    print(MANUAL_STEPS)


if __name__ == "__main__":
    main()
