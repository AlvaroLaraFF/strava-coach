---
name: weather-correlation
description: >
  Cross-reference recent runs/rides with historical weather (temperature,
  humidity, wind) from Open-Meteo to find correlations with performance.
  Use when the user asks "do I run worse in the heat", "weather impact",
  "temperature vs pace".
allowed-tools: Bash(python3 *), Read
---

# weather-correlation

For each recent activity, queries the free Open-Meteo Archive API
(no key required) using the activity's start coordinates and timestamp,
then computes correlation between temperature and pace/HR.

## Run

```bash
python3 .claude/skills/weather-correlation/scripts/weather.py --days 60 --sport Run
```

## Present

Per-activity table: date, temp (°C), pace, HR. Then a one-line correlation
verdict ("each +5°C costs ~10s/km", or "no clear correlation").

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `No <Sport> activities` / `No data` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.