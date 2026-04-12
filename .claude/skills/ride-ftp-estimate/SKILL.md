---
name: ride-ftp-estimate
description: >
  Estimate the user's current FTP (Functional Threshold Power) from their
  recent cycling activities. Use when the user asks "what's my FTP", "FTP
  estimate", "threshold power".
allowed-tools: Bash(python3 *), Read
---

# ride-ftp-estimate

Combines two estimators and shows both:
- **20-min × 0.95** from the mean-max power curve over the last 90 days
- **95th percentile of weighted_average_watts** from rides ≥40 minutes

If the two estimates disagree by more than 15W, show a warning.

## Run

```bash
python3 /home/alfernandez/PycharmProjects/strava-coach/.claude/skills/ride-ftp-estimate/scripts/ftp_estimate.py --days 90
```

## Present

Two FTP numbers (one per method), the chosen estimate (the higher of the two),
and the activity each one came from.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `streams` / `Sync first` | Invoke **strava-sync** `--level streams --sport Ride --limit 25`, retry |
| `No rides` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching notes.
**Never store raw numeric values** (those are recomputable from the DB).
Only write if the observation is NEW or CHANGED vs existing memory.
See CLAUDE.md → Memory protocol.