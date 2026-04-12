---
name: training-load
description: >
  Compute Performance Management Chart (CTL/ATL/TSB) from the user's training
  history. Use when the user asks about fitness, fatigue, form, training load,
  or how their condition is trending.
allowed-tools: Bash(python3 *), Read
---

# training-load

Computes the Banister Performance Management Chart over the local activity history:
- **CTL** (Chronic Training Load, 42-day EWMA) — fitness
- **ATL** (Acute Training Load, 7-day EWMA) — fatigue
- **TSB** (Training Stress Balance = CTL − ATL) — form

Daily load is derived from each activity using power-based TSS when watts are
available, otherwise a TRIMP-style HR score. Activities with neither are
counted as load=0.

## Pre-flight check

```bash
python3 -c "
import sys, time
sys.path.insert(0, '/home/alfernandez/PycharmProjects/strava-coach')
from strava.db import load_token
from strava.client import get_default_db_path
t = load_token(get_default_db_path())
print('OK' if t else 'NO_TOKEN')
"
```

If `NO_TOKEN`, tell the user to run the strava-setup wizard first.

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/training-load/scripts/training_load.py --days 120
```

Optional flags: `--days N` (window length, default 120), `--ftp <watts>`, `--hr-max <bpm>`, `--hr-rest <bpm>` to override the autodetected values.

## Present the result

Parse the JSON `data` block and show:
1. **Current state** — today's CTL, ATL, TSB with a one-line interpretation:
   - TSB > +10: very fresh / detrained
   - TSB +5 to +10: fresh, race ready
   - TSB −10 to +5: optimal training
   - TSB < −10: overreached, recovery needed
2. **7-day trend** — CTL change, ATL change
3. **Key dates** — fitness peak in window, lowest TSB

## On error: auto-recovery chain

If the script returns `"success": false`, interpret the error and chain:

| Error contains | Action |
|---|---|
| `No token` / `NO_TOKEN` / `StravaAuthError` | Invoke skill **strava-setup**, then re-run this script |
| `No activities` / `Sync first` / `No usable HR or power` | Invoke skill **strava-sync** with `--level summary`, then re-run this script |
| anything else | Show the error to the user |

Only chain ONCE — if the second attempt also fails, surface the error.
