---
name: matched-activities
description: >
  Group repeats of the same route by polyline similarity and show pace
  progression on each. Use when the user asks "same route", "matched runs",
  "have I improved on this loop".
allowed-tools: Bash(python3 *), Read
---

# matched-activities

Decodes summary polylines, simplifies them, and groups activities whose
start/end points and length match within tolerance. For each group, plots
pace over time.

## Run

```bash
python3 .claude/skills/matched-activities/scripts/matched.py --days 365 --sport Run --min-occurrences 3
```

## Present

For each match group with ≥3 occurrences: route signature (start lat/lng + km),
list of dates with paces, slope of improvement (s/km per month).

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `No <Sport> activities` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.