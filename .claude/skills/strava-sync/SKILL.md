---
name: strava-sync
description: >
  Bring new activity data into the local SQLite cache. Data-in is now
  file-based: the athlete exports an activity from their watch/Strava into
  their Downloads folder, and this skill imports it (and deletes the file).
  The old Strava API sync no longer exists — Strava moved API access behind a
  paid subscription. Use when the user asks to sync, update, refresh, "pull my
  latest activities", "how did my session go" (needs today's run), or when
  another skill complains "Sync first" / "No activity found".
allowed-tools: Bash(python3 *), Read
---

# strava-sync — file-based ingestion

**The Strava API is gone.** Since ~2026-07-01 Strava requires a paid
subscription for API access; the app is `Inactive` and any API call returns
`403`. We do **not** scrape or automate login (that breaks Strava's Terms —
see the `feedback_no_strava_scraping` memory). Instead, data comes in from
files the athlete exports **by hand**, which this skill imports.

Supported files: **TCX / GPX** (and `.gz`). A TCX (or the watch's original
FIT, once supported) also carries **laps**, which powers interval/fartlek
detection. FIT is not parsed yet (needs a vetted dependency).

## The canonical ingestion flow (follow in order)

**1. Import whatever is already in Downloads.**

```bash
python3 .claude/skills/strava-sync/scripts/import_downloads.py
```

This scans the Downloads folder (auto-detects `~/Downloads` / `~/Descargas`),
imports every `.tcx`/`.gpx` into the DB (activities + streams + laps +
per-km `splits_metric`), and **deletes each file once imported**. A file that
fails to parse is left in place; an activity already in the DB (same start
timestamp) is reported as a `duplicate` and not re-inserted.

Read `action_needed` in the JSON to decide what happens next:

| `action_needed` | Meaning | Do |
|---|---|---|
| `none` | New activities imported (or already present) | Proceed / retry the caller skill |
| `export_then_import` | No activity files in Downloads | Go to step 2 |
| `review_failures` | Files were there but all failed to parse | Show `failed[]` to the user |
| `configure_downloads_dir` | Downloads folder not found | Ask the user, pass `--downloads-dir` |

**2. Only if `export_then_import` — open the browser and wait for the user.**

```bash
python3 .claude/skills/strava-sync/scripts/open_export.py
# or, for a specific activity page:
python3 .claude/skills/strava-sync/scripts/open_export.py --activity-id <id>
```

`open_export.py` only *opens* the page in the user's browser (like a
bookmark). It does not log in, navigate, or download anything — the athlete
does that. After opening it, **tell the user to export the activity (··· →
Export GPX, or add `/export_tcx` to the URL) and reply once the file has
downloaded. Then wait for their confirmation.**

**3. When the user confirms the download, re-run step 1.** The file is now in
Downloads, so `import_downloads.py` imports it and deletes it, and
`action_needed` becomes `none`.

## Flags

```bash
python3 .claude/skills/strava-sync/scripts/import_downloads.py --dry-run   # preview, no writes/deletes
python3 .claude/skills/strava-sync/scripts/import_downloads.py --keep      # import but don't delete
python3 .claude/skills/strava-sync/scripts/import_downloads.py --downloads-dir /path
```

Run `--dry-run` first the very first time, so the user sees what will be
imported (and deleted) before it happens.

## Present

Summarise: how many activities imported, any duplicates skipped, any files
that failed, and which files were deleted. If a downstream skill triggered
this ("Sync first" / "No activity found"), tell the user you can now retry it.
If you had to open the browser, keep the message short — the ball is in the
user's court to export and confirm.

## Notes

- Streams and laps are populated **at import time** from the file, so the old
  per-activity `ensure_streams` / `ensure_laps` API top-ups are no longer
  needed for imported activities.
- Athlete zones (`/athlete/zones`) can no longer be fetched; use whatever is
  already cached in `athlete_zones`.
- `--sync` on other skills (`session-analysis`, `training-plan`, ...) now runs
  this same Downloads import internally (best-effort, non-interactive). If the
  data still isn't there afterwards, do the open-browser-and-wait step above.
