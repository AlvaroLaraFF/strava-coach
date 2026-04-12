---
name: ride-tss-load
description: >
  Compute power-based TSS for each ride and show the cycling-specific load
  history. Use when the user asks "TSS for my rides", "intensity factor",
  "normalized power per ride".
allowed-tools: Bash(python3 *), Read
---

# ride-tss-load

For each ride with a watts stream:
- Normalized Power (rolling 30s, ^4)
- Intensity Factor (NP / FTP)
- TSS = `(duration_s * NP * IF) / (FTP * 3600) * 100`
- Variability Index (NP / avg watts)

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/ride-tss-load/scripts/ride_tss.py --days 30 --ftp 250
```

## Present

Table per ride: date, duration, NP, IF, TSS, VI. Add the weekly cumulative
TSS row at the bottom.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `streams` / `watts streams` / `Sync first` | Invoke **strava-sync** `--level streams --sport Ride --limit 30`, retry |
| `No rides` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.