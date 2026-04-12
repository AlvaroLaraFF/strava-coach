---
name: run-race-predictor
description: >
  Predict race times for 5k / 10k / half marathon / marathon from the user's
  recent best efforts. Use when the user asks "for what time am I ready",
  "race predictor", "when can I run a sub-X".
allowed-tools: Bash(python3 *), Read
---

# run-race-predictor

Uses both:
- **Riegel formula** (`T2 = T1 * (D2/D1)^1.06`) anchored on the best recent effort
- **Daniels VDOT** when a 5k effort is available

Best efforts come from the local `best_efforts` table — backfilled from the
`raw_json` of each Run activity (Strava ships them per activity).

## Pre-flight

If `best_efforts` is empty, the script tries to backfill from stored activities
automatically.

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/run-race-predictor/scripts/race_predictor.py --recent-days 60
```

## Present

Show the anchor effort, then 4 predicted times (5k, 10k, HM, M) with both
methods side by side. Add VDOT if computed.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` / `StravaAuthError` | Invoke **strava-setup**, retry |
| `best_efforts` / `Sync first` / `No best_efforts` | Invoke **strava-sync** `--level details --limit 50`, retry |
| `No activities` / `No runs` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.