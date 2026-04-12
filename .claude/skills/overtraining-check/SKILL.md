---
name: overtraining-check
description: >
  Detect overtraining risk via ACWR, monotony and strain. Use when the user
  asks "am I overtraining", "should I back off", "is my load too high".
allowed-tools: Bash(python3 *), Read
---

# overtraining-check

Three-metric overtraining screen based on Foster's training load model:
- **ACWR** (Acute:Chronic Workload Ratio): >1.5 = injury danger zone
- **Monotony**: >2.0 = repetitive load (recovery lacking)
- **Strain**: weekly load × monotony — high values predict illness/injury

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/overtraining-check/scripts/overtraining.py
```

## Present

Traffic-light verdict (RED / YELLOW / GREEN) on top, three metric values below,
and one concrete recommendation (e.g., "drop next week's load by 30%", or
"keep going, current load is sustainable").

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