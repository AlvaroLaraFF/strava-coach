---
name: run-pace-zones
description: >
  Compute the user's pace zones (Z1-Z5) from threshold pace, and show how their
  recent runs distribute across them. Use when the user asks for their easy
  pace, threshold pace, marathon pace, "pace zones", "rhythm zones".
allowed-tools: Bash(python3 *), Read
---

# run-pace-zones

Derives pace zones using either:
- a user-provided threshold pace (`--threshold-pace 4:30`)
- or the auto-detected best 30+ minute effort from recent activities as a proxy

Then bins the average pace of recent Run activities into the resulting zones.

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/run-pace-zones/scripts/pace_zones.py --days 30
```

Optional: `--threshold-pace 4:30` to override.

## Present

Table with the 5 zones (recovery / easy / marathon / threshold / VO2max) and
their pace ranges. Then a second table with how many of the recent activities
fell in each zone, plus a verdict on whether the user is running enough easy.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `No recent runs` / `No activities` / `auto-detect threshold` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.