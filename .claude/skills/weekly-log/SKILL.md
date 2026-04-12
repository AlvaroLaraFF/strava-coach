---
name: weekly-log
description: >
  Show a weekly training log: activities grouped by ISO week and sport, with
  totals for distance, time and elevation. Use when the user asks "what did I
  do this week", "weekly summary", "training log".
allowed-tools: Bash(python3 *), Read
---

# weekly-log

Calendar-style weekly view of the user's training.

## Run

```bash
python3 .claude/skills/weekly-log/scripts/weekly_log.py --weeks 8
```

`--weeks N` controls how many weeks back to show (default 8).

## Present

Render a markdown table: `Week | Activities | Run km | Ride km | Swim km | Other km | Time | Elev`.
Highlight weeks with distance > 1.3× the trailing 4-week average.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` / `StravaAuthError` | Invoke **strava-setup**, retry |
| `No activities` / `Sync first` / `No data` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface to the user |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.