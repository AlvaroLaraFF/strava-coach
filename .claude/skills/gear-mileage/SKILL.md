---
name: gear-mileage
description: >
  Show cumulative mileage on each piece of gear (shoes, bikes). Use when the
  user asks how many km their shoes / bike have, gear status, when to retire.
allowed-tools: Bash(python3 *), Read
---

# gear-mileage

Aggregates distance per gear_id from the local activity history and queries
Strava once per gear to get the official name and lifetime distance.

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/gear-mileage/scripts/gear_mileage.py
```

## Present

Markdown table: `Gear | Type | Distance (km) | Activities | Status`. Status
flags shoes >700 km as "REPLACE SOON", >1000 km as "RETIRE NOW".

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` / `StravaAuthError` | Invoke **strava-setup**, retry |
| `No activities` / `No gear_id` / `No data` | Invoke **strava-sync** `--level details --limit 50`, retry |
| anything else | Surface |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.