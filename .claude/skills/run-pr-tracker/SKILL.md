---
name: run-pr-tracker
description: >
  Track personal records over standard distances (400m, 1k, 1mi, 5k, 10k, 15k,
  HM, M) and flag PRs that have gone stale. Use when the user asks "my PRs",
  "personal records", "best times", "have I improved at 10k".
allowed-tools: Bash(python3 *), Read
---

# run-pr-tracker

Reads the `best_efforts` table populated from the raw_json of each Run
activity (Strava ships this per activity automatically).

## Run

```bash
python3 .claude/skills/run-pr-tracker/scripts/pr_tracker.py
```

## Present

Table: `Distance | PR Time | Pace | Date | Age (days)`. Flag PRs older than
180 days as STALE in a follow-up note, with a one-line suggestion ("attempt a
fresh 5k effort").

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` / `StravaAuthError` | Invoke **strava-setup**, retry |
| `best_efforts` / `Sync first` / `Sync runs first` | Invoke **strava-sync** `--level details --limit 50`, retry |
| `No activities` / `No runs` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.