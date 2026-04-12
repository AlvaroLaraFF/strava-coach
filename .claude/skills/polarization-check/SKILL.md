---
name: polarization-check
description: >
  Check whether the user follows the 80/20 polarized training principle —
  most time at easy intensity, a small slice hard, very little moderate.
  Use when the user asks "am I 80/20", "polarized", "training distribution".
allowed-tools: Bash(python3 *), Read
---

# polarization-check

Buckets the last 30 days of training time into easy / moderate / hard zones
based on average HR per activity, then compares against the 80/20 rule.

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/polarization-check/scripts/polarization.py --hr-max 190
```

## Present

Show three percentages and a verdict: POLARIZED (≥75% easy, ≤10% moderate),
PYRAMIDAL, THRESHOLD-HEAVY, or UNDEFINED. Add one suggestion for rebalancing
if not polarized.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` / `StravaAuthError` | Invoke **strava-setup**, retry |
| `No activities` / `Sync first` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface to the user |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.