---
name: readiness-today
description: >
  Tell the user whether they should train hard, train easy, or rest today,
  based on their current TSB, ACWR and recent load. Use when the user asks
  "can I train hard today", "am I ready", "should I rest".
allowed-tools: Bash(python3 *), Read
---

# readiness-today

Single-number readiness recommendation derived from current form (TSB), acute:chronic
ratio and the load of the last 48 hours.

## Pre-flight check

Token must exist (run strava-setup wizard otherwise).

## Pre-flight: read snapshot for flags

```bash
python3 .claude/skills/athlete-snapshot/scripts/read_snapshot.py
```

Extract `ftp_w`, `hr_max_bpm`, `hr_rest_bpm` from the snapshot and pass as
`--ftp`, `--hr-max`, `--hr-rest`. If no snapshot, use defaults.

## Run

```bash
python3 .claude/skills/readiness-today/scripts/readiness.py
```

Optional: `--ftp`, `--hr-max`, `--hr-rest` to override defaults.

## Present the result

Show the recommendation prominently (GO HARD / MODERATE / EASY / REST), plus the
three numbers that drove it. End with one sentence of justification — DON'T
hedge: pick one verdict.

## Post-run: update snapshot

```bash
python3 .claude/skills/athlete-snapshot/scripts/update_snapshot.py --source readiness-today --acwr <ACWR> --tsb <TSB>
```

Replace placeholders with values from script output. Show alerts if any.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` / `StravaAuthError` | Invoke **strava-setup**, retry |
| `No activities` / `Sync first` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.