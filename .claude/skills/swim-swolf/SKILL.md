---
name: swim-swolf
description: >
  Compute SWOLF (swimming efficiency = stroke time + stroke count per length)
  and show the trend over recent swims. Use when the user asks about SWOLF,
  swim efficiency, "am I more efficient in the pool".
allowed-tools: Bash(python3 *), Read
---

# swim-swolf

For pool swims, syncs the lap data on demand and computes SWOLF per lap, then
averages per session.

## Run

```bash
python3 .claude/skills/swim-swolf/scripts/swim_swolf.py --days 60
```

## Present

Per-session average SWOLF, plus a trend line: improving (lower SWOLF) or
declining. Reference values: <30 elite, 30-40 trained, 40-50 recreational,
>50 beginner.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `lap data` / `No swims with usable lap data` | Invoke **strava-sync** `--level details --limit 30`, retry (laps will be lazy-fetched on next run) |
| `No swims` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.