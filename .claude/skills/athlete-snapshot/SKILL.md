---
name: athlete-snapshot
description: >
  Compute and store a complete physiological profile snapshot, track metric
  evolution, and alert on significant changes. Use when the user asks to
  update their profile, refresh metrics, check how metrics have changed, or
  asks about their physiological state.
allowed-tools: Bash(python3 *), Read
---

# athlete-snapshot

Recomputes all variable physiological metrics from the local activity database
and writes a timestamped snapshot row to the `athlete_snapshots` table. Each
snapshot captures:

**Tier 1 — Input parameters** (used as flags by other skills):
- FTP (watts), HR max/rest (bpm), VDOT, threshold pace (min/km), CSS (m/s), weight (kg)

**Tier 2 — Load state** (fitness/fatigue/form):
- CTL, ATL, TSB, ACWR, monotony, strain

**Tier 3 — Trend markers**:
- Average aerobic decoupling (%), average running cadence (spm)

The script compares against the previous snapshot and generates **alerts**
when metrics cross significant thresholds.

## Pre-flight check

```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from strava.db import load_token
from strava.client import get_default_db_path
t = load_token(get_default_db_path())
print('OK' if t else 'NO_TOKEN')
"
```

If `NO_TOKEN`, tell the user to run the strava-setup wizard first.

## Run

```bash
python3 .claude/skills/athlete-snapshot/scripts/full_refresh_snapshot.py --days 90
```

Optional flags: `--days N` (analysis window, default 90).

## Present the result

Parse the JSON `data` block and show:

1. **Current profile snapshot** — table of all metrics with their values.
   Use `fmt_pace` for threshold_pace, format durations where applicable.

2. **Alerts** — if the `alerts` array is non-empty, present each alert
   prominently. Group by severity:
   - Critical: ACWR > 1.5, monotony > 2.5, TSB < -10
   - Notable: FTP change, VDOT change, threshold pace change, decoupling boundary cross
   - Info: cadence shift, CTL trend

3. **Comparison** — if `previous_captured_at` is not null, show a delta
   column (current vs previous) for metrics that changed.

4. **Overall trend** — one sentence: "Mejorando", "Manteniendo", or
   "Empeorando" based on the combination of CTL trend, VDOT, and decoupling.

## After presenting

Write a memory entry (project type) capturing the **qualitative observation**
about the user's current physiological state — NOT the raw numbers. Example:
"User's fitness is building steadily, threshold pace improving, decoupling
stable — good aerobic base development."

Only write if the observation is NEW or CHANGED since the last memory entry.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` / `NO_TOKEN` | Invoke skill **strava-setup**, then re-run |
| `No activities` / `Sync first` | Invoke skill **strava-sync** with `--level details`, then re-run |
| anything else | Show the error to the user |

Only chain ONCE.
