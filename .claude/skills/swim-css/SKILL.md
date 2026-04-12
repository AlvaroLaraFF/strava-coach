---
name: swim-css
description: >
  Estimate Critical Swim Speed (CSS) from a 400m / 200m time-trial pair, and
  derive training pace targets. Use when the user asks about CSS, swim
  threshold, target pace per 100m.
allowed-tools: Bash(python3 *), Read, AskUserQuestion
---

# swim-css

CSS = `200 / (T400 - T200)` (m/s). The user provides their best 400m and 200m
times (in seconds or M:SS) — either as flags or via AskUserQuestion.

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/swim-css/scripts/swim_css.py --t400 6:20 --t200 2:55
```

## Present

CSS in m/s and pace per 100m, plus suggested training paces:
- CSS+5s/100m = endurance
- CSS = threshold
- CSS-3s/100m = VO2max intervals

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.