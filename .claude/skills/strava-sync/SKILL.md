---
name: strava-sync
description: >
  Pull data from Strava into the local SQLite cache. Three levels: summary
  (fast, just activity list), details (per-activity full payload — unlocks
  best_efforts, splits, weighted_average_watts), and streams (per-second
  time series — unlocks NP, TSS, decoupling, power curve). Use when the
  user asks to sync, update, refresh, "pull my latest activities", or when
  another skill complains "Sync first".
allowed-tools: Bash(python3 *), Read
---

# strava-sync

Three sync levels, each one a superset of the previous:

| Level | Endpoint(s) | Unlocks | Speed |
|---|---|---|---|
| `summary` | `/athlete/activities` | basic distance/time/HR/watts | seconds |
| `details` | `/activities/{id}` per activity | best_efforts, splits, NP, full HR | ~0.7s/activity |
| `streams` | `/activities/{id}/streams` per activity | per-second power/HR/GPS | ~0.7s/activity |

The script throttles each request to stay below Strava's 100 req / 15 min
rate limit, and sleeps + retries automatically on 429.

## When to use which

- **First-time setup or weekly refresh**: `--level summary` (auto-incremental: full history on first run, only new activities after that)
- **Before using run-pr-tracker / run-race-predictor**: `--level details`
- **Before using run-decoupling / ride-power-curve / ride-tss-load**: `--level streams --sport Ride`
- **One-shot full upgrade**: `--level all` (slow on big histories)

## Run

```bash
# Quick: refresh activity list (auto-incremental: first run = full history, then only new)
python3 .claude/skills/strava-sync/scripts/sync.py --level summary

# Force full re-sync of all history (ignores incremental logic)
python3 .claude/skills/strava-sync/scripts/sync.py --level summary --full

# Upgrade existing activities to detailed payloads (best_efforts, splits)
python3 .claude/skills/strava-sync/scripts/sync.py --level details --limit 50

# Pull streams for runs (for decoupling skill)
python3 .claude/skills/strava-sync/scripts/sync.py --level streams --sport Run --limit 20

# Pull athlete zones (HR + power)
python3 .claude/skills/strava-sync/scripts/sync.py --level zones

# Everything (slow)
python3 .claude/skills/strava-sync/scripts/sync.py --level all
```

## Pre-flight

Token must exist (run strava-setup wizard first). The script verifies it and
exits with a clear error otherwise.

**Note on the `zones` level**: fetching `/athlete/zones` requires the
`profile:read_all` scope. The default scope was widened in the setup wizard,
but tokens issued before this change must be re-authorized:

```bash
python3 .claude/skills/strava-setup/scripts/setup_oauth.py
```

(re-runs the OAuth flow with the new scope; same Strava app, no new credentials).

## Present

Show a compact summary of what was synced: counts of new activities, upgraded
to detailed, streams fetched, errors. If a downstream skill triggered this
sync ("Sync first"), tell the user they can now retry that skill.
