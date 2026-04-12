---
name: run-cadence-form
description: >
  Show the user's running cadence trend and stride length progression. Use
  when the user asks about cadence, form, stride length, "am I running more
  efficiently".
allowed-tools: Bash(python3 *), Read
---

# run-cadence-form

Reads cadence from each recent Run and computes the trend. Average cadence on
Strava is reported as one-leg rpm — the script doubles it to steps/minute.

## Run

```bash
python3 .claude/skills/run-cadence-form/scripts/cadence.py --days 90
```

## Present

Show: average cadence (steps/min) for the period, change vs first vs last
month, average stride length (distance / step count). Add the recommended
cadence range (170-185 spm) and where the user falls.

## Post-run: update snapshot

```bash
python3 .claude/skills/athlete-snapshot/scripts/update_snapshot.py --source run-cadence-form --avg-cadence-spm <AVG_CADENCE>
```

Replace `<AVG_CADENCE>` with the average cadence in steps/min from the output.
Show alerts if any.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `No cadence data` / `No runs` / `Sync first` | Invoke **strava-sync** `--level details --limit 30`, retry |
| anything else | Surface |

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.