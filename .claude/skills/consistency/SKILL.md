---
name: consistency
description: >
  Measure how consistent the user is with training: streaks, days per week,
  variability of weekly volume. Use when the user asks about consistency,
  streaks, frequency, "am I regular".
allowed-tools: Bash(python3 *), Read
---

# consistency

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/consistency/scripts/consistency.py --weeks 12
```

## Present

Show: current streak (consecutive days/weeks with at least one activity),
average days per week, coefficient of variation of weekly volume, and a
one-line verdict (HIGHLY CONSISTENT / CONSISTENT / IRREGULAR).

## On error: auto-recovery chain

If the script returns `"success": false`, chain BEFORE showing the error:

| Error contains | Action |
|---|---|
| `No token` / `NO_TOKEN` / `StravaAuthError` | Invoke skill **strava-setup**, then re-run |
| `No activities` / `Sync first` / `No data` | Invoke skill **strava-sync** with `--level summary`, then re-run |
| anything else | Surface to the user |

Chain at most ONCE per request.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.