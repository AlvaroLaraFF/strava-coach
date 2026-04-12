---
name: run-decoupling
description: >
  Compute aerobic decoupling (Pa:Hr) on long runs to assess aerobic base
  quality. Use when the user asks "is my aerobic base solid", "am I drifting",
  "decoupling", "cardiac drift".
allowed-tools: Bash(python3 *), Read
---

# run-decoupling

Pulls streams for the user's recent long runs and computes Pa:Hr decoupling
between the first and second halves. <5% = solid aerobic base, 5-8% =
acceptable, >8% = poor base / under-trained.

## Run

```bash
python3 .claude/skills/run-decoupling/scripts/decoupling.py --min-minutes 60 --max-runs 5
```

The script syncs streams on demand for any qualifying run that doesn't have
them yet, so the first run can take 30-60 seconds depending on history.

## Present

Table with: date, duration, decoupling %, verdict per run. Then an overall
trend line if there are at least 3 runs.

## Post-run: update snapshot

```bash
python3 .claude/skills/athlete-snapshot/scripts/update_snapshot.py --source run-decoupling --avg-decoupling-pct <AVG_DECOUPLING>
```

Replace `<AVG_DECOUPLING>` with the average decoupling % from the output.
Show alerts if any.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `streams` / `speed+HR` / `No usable` | Invoke **strava-sync** `--level streams --sport Run --limit 20`, retry |
| `No runs` / `No activities` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.