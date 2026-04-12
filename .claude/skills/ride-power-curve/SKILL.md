---
name: ride-power-curve
description: >
  Build the user's mean-max power curve from cycling activities with watts.
  Use when the user asks for "my power curve", "best 5 minutes", "best 20 min",
  "MMP", "what's my critical power".
allowed-tools: Bash(python3 *), Read
---

# ride-power-curve

For each ride with a watts stream, computes the best rolling-mean power for
the standard windows (1s, 5s, 30s, 1min, 5min, 20min, 60min) and aggregates
the all-time best across activities.

Streams are synced on demand the first time you run this — large histories
may take a minute or two.

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/ride-power-curve/scripts/power_curve.py --days 180 --max-rides 30
```

## Present

Two columns: window | best watts. Mention which activity each best comes from.
End with the implied 20-min FTP (`0.95 * MMP_20min`).

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `watts stream` / `No streams` / `Sync first` | Invoke **strava-sync** `--level streams --sport Ride --limit 30`, retry |
| `No rides` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.