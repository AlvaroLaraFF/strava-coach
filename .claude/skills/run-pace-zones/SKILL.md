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

## Pre-flight: read snapshot for flags

```bash
python3 .claude/skills/athlete-snapshot/scripts/read_snapshot.py
```

Extract `threshold_pace_min_km` and `hr_max_bpm` from the snapshot. If
threshold pace is available, pass as `--threshold-pace` (convert from decimal
min/km to M:SS format). If no snapshot, let the script auto-detect.

## Run

```bash
python3 .claude/skills/run-pace-zones/scripts/pace_zones.py --days 30
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

## Post-run: update snapshot

```bash
python3 .claude/skills/athlete-snapshot/scripts/update_snapshot.py --source run-pace-zones --threshold-pace-min-km <THRESHOLD_PACE>
```

Replace `<THRESHOLD_PACE>` with the computed threshold pace in decimal min/km.
Show alerts if any.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.