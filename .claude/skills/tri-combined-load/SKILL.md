---
name: tri-combined-load
description: >
  Compute a combined CTL/ATL/TSB across run, ride and swim for triathletes.
  Use when the user asks "my combined load", "triathlon training load", "total
  TSS across sports".
allowed-tools: Bash(python3 *), Read
---

# tri-combined-load

Same PMC engine as `training-load` but explicitly merging the three triathlon
disciplines into a single daily load number, with breakdown per sport.

Swim: TRIMP (HR-based) since swims rarely have power.
Bike: power-based TSS when watts available, else TRIMP.
Run: rTSS estimate from pace + threshold pace, else TRIMP.

## Pre-flight: read snapshot for flags

```bash
python3 .claude/skills/athlete-snapshot/scripts/read_snapshot.py
```

Extract `ftp_w`, `hr_max_bpm`, `hr_rest_bpm` from the snapshot and pass as
`--ftp`, `--hr-max`, `--hr-rest`. If no snapshot, use defaults.

## Run

```bash
python3 .claude/skills/tri-combined-load/scripts/tri_load.py --days 90
```

## Present

Today's combined CTL/ATL/TSB plus a stacked breakdown per sport. Highlight
which sport contributes the most to current ATL.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `No tri-relevant activities` / `Sync first` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.