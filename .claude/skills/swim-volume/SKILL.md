---
name: swim-volume
description: >
  Show swim volume per week and per month, plus session count. Use when the
  user asks "how much do I swim", "swim volume", "metres in the pool".
allowed-tools: Bash(python3 *), Read
---

# swim-volume

Aggregates swim distance and time over the local history.

## Run

```bash
python3 .claude/skills/swim-volume/scripts/swim_volume.py --weeks 12
```

## Present

Two tables: weekly and monthly. Each row: distance (m), time, sessions.
End with the average and a one-line trend (increasing / steady / decreasing).

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `No swims` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.