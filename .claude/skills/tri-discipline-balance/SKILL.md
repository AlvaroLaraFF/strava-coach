---
name: tri-discipline-balance
description: >
  Show how the user's training time and volume distribute across run, ride
  and swim, and flag underweighted disciplines. Use when the user asks "am I
  balanced", "discipline balance", "which sport am I neglecting".
allowed-tools: Bash(python3 *), Read
---

# tri-discipline-balance

Computes time, distance and session count per discipline over the chosen
window, expresses each as a percentage, and compares against typical
triathlon ratios.

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/tri-discipline-balance/scripts/balance.py --days 30
```

## Present

Three columns (run / ride / swim): time hours, % time, sessions, distance.
Then a verdict on which discipline is over- or under-weighted, with one-line
suggestion.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `No tri-relevant activities` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.