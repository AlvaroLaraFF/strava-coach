---
name: training-plan
description: >
  Persist a confirmed weekly training plan (one row per session with target
  HR range and pace range) and measure adherence against actual activities.
  Use when the user says "my plan this week", "what's on today", "save this
  plan", "how am I doing vs plan", "plan adherence", "did I complete this
  week", or any equivalent in Spanish.
allowed-tools: Bash(python3 *), Read
---

# training-plan

Stores the agreed plan in the `planned_sessions` SQLite table and
cross-references it with `activities` to compute execution. Every session
row must carry an HR range (bpm) and a pace range (min/km) — this is a
hard rule from project memory: no plan is ever presented or persisted
without both axes.

Phases used throughout: `correction | base | quality | taper | freeform`.

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

If `NO_TOKEN`, run the `strava-setup` skill first.

## Sub-commands

Add a single session:

```bash
python3 .claude/skills/training-plan/scripts/training_plan.py add \
  --date 2026-04-15 --sport Run --session-type tempo --phase correction \
  --duration 45 --distance 8 --hr-min 155 --hr-max 170 \
  --pace-fast 5.00 --pace-slow 5.20 --description "15min tempo + recovery"
```

Bulk-insert a whole week from stdin JSON (this is the main entry point
after the user confirms a weekly plan in conversation):

```bash
cat <<'JSON' | python3 .claude/skills/training-plan/scripts/training_plan.py \
    add-bulk --replace-range 2026-04-13 2026-04-19
[
  {"plan_date":"2026-04-14","sport_type":"Run","session_type":"easy",
   "phase":"correction","duration_min":40,"distance_km":7,
   "hr_min_bpm":135,"hr_max_bpm":150,
   "pace_fast_min_km":5.45,"pace_slow_min_km":6.15,
   "description":"easy zone-2 shakeout"}
]
JSON
```

`--replace-range START END` deletes any existing planned sessions in the
closed interval before inserting, so re-confirming a modified week is a
single call. Omit it when adding a fresh plan.

List sessions in a window (defaults to the current ISO week) and
auto-match past-dated rows with real activities:

```bash
python3 .claude/skills/training-plan/scripts/training_plan.py list \
  --start 2026-04-13 --end 2026-04-19
```

Review adherence in a window (same matcher plus aggregates):

```bash
python3 .claude/skills/training-plan/scripts/training_plan.py review \
  --start 2026-04-06 --end 2026-04-12
```

Update or delete a single session:

```bash
python3 .claude/skills/training-plan/scripts/training_plan.py update --id 12 --duration 50
python3 .claude/skills/training-plan/scripts/training_plan.py delete --id 12
```

## Required fields per session (hard-enforced)

Every session passed to `add` or `add-bulk` must carry:

- `plan_date` (`YYYY-MM-DD`)
- `sport_type` (`Run`, `Ride`, `Swim`, `WeightTraining`, `Rest`, ...)
- `session_type` (`easy`, `tempo`, `interval`, `long`, `fartlek`,
  `recovery`, `race`, `strength`, `rest`)
- `hr_min_bpm` and `hr_max_bpm` (both integers, min < max)
- `pace_fast_min_km` and `pace_slow_min_km` (decimal min/km, fast < slow)

Rest/strength sessions may pass zeros or sentinel values — the validator
still requires the keys to be present. If the user has no reference pace
yet for a given intensity, pass a wide provisional range, never omit one
of the two axes.

## Structured blocks (REQUIRED for any session with internal structure)

Any session that is not a single steady effort — warmups, intervals,
fartlek, tempo with recovery, progression runs, long runs with finish
surges — MUST be persisted with its `blocks` array. The session-level
HR and pace ranges stay as the envelope for the Strava matcher; the
blocks carry the actual targets the athlete reads on the watch.

Each block is an object with:

- `block_type` — one of `warmup | work | recovery | cooldown | steady | rest`
- `repeat_count` — integer ≥ 1 (for interval blocks, the number of reps)
- `duration_min` and/or `distance_km` — at least one must be present
  (exception: `rest` may omit both)
- `hr_min_bpm` / `hr_max_bpm` — integers, min < max
- `pace_fast_min_km` / `pace_slow_min_km` — decimal min/km, fast < slow
- `execution_notes` — free-text instructions for the athlete (optional
  but strongly recommended — e.g. "let HR drop below 141 before the
  next rep")

Block ordering follows array position. For interval workouts, typically:
one `warmup`, N `work`/`recovery` pairs with `repeat_count` on each, one
`cooldown`. Do NOT hide a fartlek as a single `steady` block — that
defeats the point of the table.

Example — fartlek with warmup, 6×(1min Z4 + 2min Z1), cooldown:

```json
{
  "plan_date": "2026-04-17",
  "sport_type": "Run",
  "session_type": "fartlek",
  "phase": "correction",
  "duration_min": 40,
  "distance_km": 6.5,
  "hr_min_bpm": 130,
  "hr_max_bpm": 184,
  "pace_fast_min_km": 5.50,
  "pace_slow_min_km": 7.33,
  "description": "6x(1min Z4 + 2min Z1), warmup/cooldown 10min",
  "blocks": [
    {"block_type": "warmup", "repeat_count": 1,
     "duration_min": 10,
     "hr_min_bpm": 130, "hr_max_bpm": 145,
     "pace_fast_min_km": 6.75, "pace_slow_min_km": 7.33,
     "execution_notes": "Start ~7:15, progress to ~6:50 by the end"},
    {"block_type": "work", "repeat_count": 6,
     "duration_min": 1,
     "hr_min_bpm": 169, "hr_max_bpm": 184,
     "pace_fast_min_km": 5.50, "pace_slow_min_km": 5.97,
     "execution_notes": "Push to upper Z4 (175+ bpm) by end of the minute, not a sprint"},
    {"block_type": "recovery", "repeat_count": 6,
     "duration_min": 2,
     "hr_min_bpm": 126, "hr_max_bpm": 141,
     "pace_fast_min_km": 7.00, "pace_slow_min_km": 7.50,
     "execution_notes": "HR must drop below 150 before next rep; extend to 3min if needed"},
    {"block_type": "cooldown", "repeat_count": 1,
     "duration_min": 10,
     "hr_min_bpm": 130, "hr_max_bpm": 145,
     "pace_fast_min_km": 7.00, "pace_slow_min_km": 7.33,
     "execution_notes": "Relax, finish without spiking HR"}
  ]
}
```

For a pure easy run, a single `steady` block is fine but usually
unnecessary — the session-level range already describes it.

## When Claude agrees a plan with the user

1. Generate the weekly proposal and present it as a table with columns
   `Day | Sport | Type | Phase | Duration | Distance | HR | Pace | Description`
   (Spanish labels in the chat are fine; the JSON payload is English).
2. After the user confirms ("ok", "save it", "go ahead", or any equivalent affirmation in any language), serialise
   the table to a JSON array and pipe it to `add-bulk`. Do NOT ask for
   permission — the `feedback_plan_persistence` memory already authorises
   persistence of confirmed plans.
3. If the user modifies a week already stored, call `add-bulk` with
   `--replace-range <monday> <sunday>` and the updated JSON.
4. After persistence succeeds, write a qualitative `project` memory entry
   (e.g. "week 2026-W16 plan confirmed, focus on correction phase — first
   week adding a tempo session"). Never dump numbers into memory.

## Present `list` output

For each session render a header line with
`Date · Sport · Type · Phase · Duration · Distance · Status`.

Immediately below, render a **block table** (only omit this for sessions
with zero blocks persisted):

`Block | × | Duration | Distance | HR range | Pace range | Notes`

Every zone reference in the prose around the table MUST be accompanied
by its numeric range (e.g. "Z4 (169–184 bpm, 5:30–5:58 min/km)"), so
the athlete can execute from the watch without cross-referencing
anything else.

For past-dated rows already matched, append a small adherence table:
`duration_delta_min`, `hr_avg_vs_range`, `pace_avg_vs_range`.

## Present `review` output

Headline line first: `Adherence: X/Y sessions (Z%)`. Then a breakdown
per `phase` and per `session_type` with completion count and average
deltas. Close with one qualitative sentence — is the user executing the
plan as agreed, or drifting?

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` / `NO_TOKEN` | Invoke **strava-setup**, retry |
| `No activities` / `Sync first` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

Only chain ONCE.

## After presenting (mandatory)

Write a qualitative memory entry about what the adherence data says —
never numbers. Examples:

- After `review`: "User completed the first correction week fully; HR
  ranges were inside target on all easy runs. Pattern holds."
- After `add-bulk`: "Week 2026-W16 confirmed; first week with a tempo
  session — watch for HR drift."

Only write if the observation is NEW or CHANGED since the last entry.
