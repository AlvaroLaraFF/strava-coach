#!/usr/bin/env python3
"""Scan the Downloads folder for exported activity files, import them into the
local DB, and delete each file once it has been imported successfully.

This is the canonical data-in path for strava-coach. It replaces the old
Strava API sync (which no longer exists -- Strava moved API access behind a
paid subscription). Only ``.tcx`` / ``.gpx`` (and ``.gz`` variants) are picked
up; other files in Downloads are left untouched. FIT is reported as skipped
(not yet supported). A file is deleted ONLY after its data is committed; a file
that fails to parse is left in place and reported.

The interactive fallback -- "no new files found, so open the browser and wait
for the user to export" -- is orchestrated by the assistant (see the
strava-sync SKILL.md), not by this script. Here, ``action_needed`` in the
output tells the caller which case occurred.

Usage:
    python3 import_downloads.py               # import + delete imported files
    python3 import_downloads.py --dry-run     # preview only, no writes/deletes
    python3 import_downloads.py --keep        # import but keep the files
    python3 import_downloads.py --downloads-dir /path/to/dir
"""
import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
sys.path.insert(0, PROJECT_ROOT)

from strava.client import get_default_db_path, output_json  # noqa: E402
from strava.fileimport import import_from_downloads  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Import exported activities from Downloads.")
    parser.add_argument("--downloads-dir", default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only; no DB writes, no deletions.")
    parser.add_argument("--keep", action="store_true",
                        help="Import but do not delete the files.")
    args = parser.parse_args()

    report = import_from_downloads(
        get_default_db_path(),
        downloads_dir=args.downloads_dir,
        delete=not args.keep,
        dry_run=args.dry_run,
    )
    output_json(report)


if __name__ == "__main__":
    main()
