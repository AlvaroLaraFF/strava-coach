---
name: ride-climbing
description: >
  Climbing analysis for cyclists: VAM (vertical meters per hour), W/kg on
  climbs, hardest climbs in the period. Use when the user asks "how do I climb",
  "my climbs", "VAM", "watts per kilo".
allowed-tools: Bash(python3 *), Read
---

# ride-climbing

For each ride: total elevation, average grade implied (elev/distance), and
VAM. If the user provides their weight and the ride has power, compute W/kg
for the ride and rank climbs by W/kg.

## Run

```bash
python3 .claude/skills/ride-climbing/scripts/climbing.py --days 90 --weight-kg 72
```

## Present

Top 5 rides by VAM, plus an aggregate: average VAM, max VAM, and trend
(improving / steady / declining) compared to the previous 90 days.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `No rides` / `No climby rides` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.