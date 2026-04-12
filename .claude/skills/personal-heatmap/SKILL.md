---
name: personal-heatmap
description: >
  Generate a personal heatmap of every place the user has trained, from
  activity polylines. Use when the user asks for a heatmap, "where have I
  ridden", "show me my routes on a map".
allowed-tools: Bash(python3 *), Read
---

# personal-heatmap

Reads `summary_polyline` from each activity in the local DB, decodes them, and
renders a single self-contained HTML file with a Leaflet heatmap layer.

## Run

```bash
python3 .claude/skills/personal-heatmap/scripts/heatmap.py --output ~/strava_heatmap.html
```

Optional: `--sport Run`, `--days 365`.

## Present

Tell the user where the file was saved and that they can open it in any
browser. Show the JSON summary (number of activities, points plotted,
bounding box).

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` / `StravaAuthError` | Invoke **strava-setup**, retry |
| `No activities` / `No GPS data` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.