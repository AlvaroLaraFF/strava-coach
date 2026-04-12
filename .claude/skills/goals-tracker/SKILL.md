---
name: goals-tracker
description: >
  Set, list and track training goals (distance/time/elevation per week, month
  or year, optionally per sport). Use when the user mentions goals, targets,
  yearly distance, monthly km, "voy a llegar a".
allowed-tools: Bash(python3 *), Read
---

# goals-tracker

## Sub-commands

Add a new goal:
```bash
python3 .../goals-tracker/scripts/goals.py add --metric distance --period year --sport Run --target 1500
```
- `--metric`: distance (km), time (minutes), elevation (m)
- `--period`: week, month, year
- `--sport`: Run, Ride, Swim, or omit for all sports
- `--target`: number in the metric's units

List + progress:
```bash
python3 .../goals-tracker/scripts/goals.py list
```

## Present

For each active goal: name, target, current value, % progress, ETA at current
pace, projection vs target. Highlight green (on track), yellow (close), red
(behind).

If the user wants to add a goal, ask for the four parameters with
AskUserQuestion (metric, period, sport, target) when any are missing.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` / `StravaAuthError` | Invoke **strava-setup**, retry |
| `No activities` / `No data` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.