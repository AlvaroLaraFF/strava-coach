# strava-coach — project guide for Claude Code

This file is loaded automatically into every Claude Code session in this
repository. It defines the personal-trainer assistant built on top of the
Strava API, the catalog of skills available, the data layer, and — **very
importantly** — the memory protocol you must follow when interacting with the
user about their training.

---

## Project purpose

`strava-coach` turns the user's Strava history into a personal endurance
coach. It pulls activities (and on-demand: streams, laps, athlete zones) into
a local SQLite database and exposes a catalog of focused skills that answer
specific training questions: fitness/fatigue/form, race predictions, FTP,
power curve, swim efficiency, training balance, etc.

The user should be able to ask questions in natural language ("am I
overtrained?", "how is my fitness?", "predict my 10k") and the right skill
should activate automatically — slash commands are not required.

---

## Skill catalog

27 skills total. Each skill has its own folder under `.claude/skills/<name>/`
with a `SKILL.md`, a `metadata.json`, and a `scripts/` subfolder containing
the Python CLI(s) it invokes. All scripts output JSON via the standard
`output_json()` / `output_error()` helpers in `strava/client.py`.

### Infrastructure

| Skill | Purpose |
|---|---|
| **strava-setup** | First-time setup wizard: Python check, dependencies, OAuth flow with Strava. Run once. |
| **strava-sync** | Pull data into the local DB. Three levels: `summary` (fast list), `details` (per-activity full payload — best_efforts, splits, weighted_average_watts), `streams` (per-second time series), plus `zones` (athlete HR/power zones). |
| **athlete-snapshot** | Compute and store a time-series physiological profile (FTP, VDOT, threshold pace, HR zones, CTL/ATL/TSB, ACWR, etc.). Tracks evolution and alerts on significant changes. |
| **memory-consolidate** | Audit and refresh the project memory bank against live data. **Auto-invoked at session start** and on user request. |

### Cross-sport analytics

| Skill | Answers |
|---|---|
| **training-load** | What is my current CTL/ATL/TSB (Performance Management Chart)? |
| **readiness-today** | Should I train hard, easy or rest today? |
| **overtraining-check** | Am I overtraining? ACWR + monotony + strain (Foster). |
| **weekly-log** | Calendar-style weekly log grouped by sport. |
| **consistency** | Streaks, frequency, weekly volume variability. |
| **polarization-check** | Am I following the 80/20 polarized model? |
| **goals-tracker** | Set and track distance/time/elevation goals per period. |
| **gear-mileage** | Distance per shoe / bike with retirement alerts. |
| **personal-heatmap** | Render a Leaflet heatmap of all training locations. |

### Run-specific

| Skill | Answers |
|---|---|
| **run-race-predictor** | Predict 5k / 10k / HM / M times (Riegel + VDOT). |
| **run-pr-tracker** | All-time PRs over standard distances with stale-PR alerts. |
| **run-pace-zones** | Z1–Z5 pace zones from threshold + recent distribution. |
| **run-decoupling** | Pa:Hr aerobic decoupling on long runs (base quality). |
| **run-cadence-form** | Cadence and stride length trend. |

### Ride-specific

| Skill | Answers |
|---|---|
| **ride-power-curve** | Mean-max power curve (1s → 1h). |
| **ride-ftp-estimate** | FTP from MMP-20 × 0.95 + WAP percentile. |
| **ride-climbing** | VAM, W/kg, hardest climbs in a window. |
| **ride-tss-load** | Power-based TSS / NP / IF / VI per ride. |

### Swim-specific

| Skill | Answers |
|---|---|
| **swim-swolf** | SWOLF efficiency trend per pool swim. |
| **swim-css** | Critical Swim Speed from a 400m / 200m time-trial pair. |
| **swim-volume** | Weekly / monthly volume and session count. |

### Triathlon

| Skill | Answers |
|---|---|
| **tri-combined-load** | Combined CTL/ATL/TSB across all three disciplines. |
| **tri-discipline-balance** | Time distribution per sport and gap detection. |

### Advanced

| Skill | Answers |
|---|---|
| **weather-correlation** | Cross-reference activities with Open-Meteo to test heat impact. |
| **matched-activities** | Group repeats of the same route and show pace progression. |

### Routing intent → skill

You should pick the correct skill from natural language without forcing the
user to know slash commands. Examples:

| User says | Activate |
|---|---|
| "how is my form / fitness" | training-load |
| "should I train hard today / can I push" | readiness-today |
| "am I overtrained" | overtraining-check |
| "what did I do this week / weekly summary" | weekly-log |
| "for what time am I ready / 10k predictor" | run-race-predictor |
| "my PRs / personal bests" | run-pr-tracker |
| "my pace zones / easy pace" | run-pace-zones |
| "my power curve / best 20 min" | ride-power-curve |
| "what's my FTP" | ride-ftp-estimate |
| "my SWOLF / swim efficiency" | swim-swolf |
| "sync / refresh / pull from Strava" | strava-sync |
| "refresh metrics / how have my metrics changed / my profile" | athlete-snapshot |
| "refresh memory / what do you remember about me" | memory-consolidate |

If multiple skills could plausibly answer, pick the **most specific** one and
mention briefly that you can also run the others.

---

## Data layer

```
strava/
├── client.py          # Strava API client + token refresh + 429 retry
├── db.py              # SQLite schema + helpers
├── analytics.py       # Pure-function formulas (TRIMP, NP, TSS, GAP, Riegel, etc.)
└── sync.py            # Bulk sync orchestration (summary/details/streams/zones)
```

### Tables

| Table | Purpose |
|---|---|
| `oauth_tokens` | Persisted OAuth2 access + refresh tokens, auto-refreshed |
| `activities` | Per-activity summary fields + raw_json blob |
| `athlete_stats` | YTD / all-time totals snapshots |
| `activity_streams` | Per-second time-series JSON (per activity, lazy) |
| `activity_laps` | Lap data (per activity, lazy) |
| `athlete_zones` | Configured HR + power zones (single row per athlete) |
| `best_efforts` | Normalized PRs over standard run distances |
| `daily_load` | Per-day training load (for PMC reuse) |
| `goals` | User-set goals (metric, period, sport, target) |
| `user_profile` | Optional athlete info: name, height, weight, gender |
| `athlete_snapshots` | Time-series physiological profile. Each row = timestamped snapshot of key metrics (FTP, VDOT, threshold pace, HR zones, CTL/ATL/TSB, ACWR, monotony, strain, decoupling, cadence). Append-only with merge — partial updates carry forward previous values. |

### Snapshot protocol — dynamic athlete profile

The `athlete_snapshots` table tracks variable physiological metrics over time.
Analytics outputs are still recomputable on demand, but snapshots serve two
purposes:

1. **Pre-flight flag source** — skills that accept `--ftp`, `--hr-max`,
   `--hr-rest`, `--threshold-pace` read the latest snapshot via
   `.claude/skills/athlete-snapshot/scripts/read_snapshot.py` instead of using generic defaults.
2. **Change detection** — after each skill run, `.claude/skills/athlete-snapshot/scripts/update_snapshot.py`
   compares the new values against the previous snapshot and generates alerts
   when metrics cross significant thresholds.

**Pre-flight (before running a skill that takes physiological flags):**
```
python3 .claude/skills/athlete-snapshot/scripts/read_snapshot.py  →  extract values  →  pass as CLI flags
```

**Post-run (after presenting skill results):**
```
python3 .claude/skills/athlete-snapshot/scripts/update_snapshot.py --source <skill> --<metric> <value> ...
```
If the response contains `alerts`, show them to the user prominently.

**Full refresh:**
```
python3 .claude/skills/athlete-snapshot/scripts/full_refresh_snapshot.py --days 90
```
Recomputes all metrics in one pass. Used by the `athlete-snapshot` skill.

Qualitative observations about the user's progression ("you've been
overreaching since early April") still belong in **memory files**, not in the
database. The snapshot stores numbers; memory stores coaching opinions.

---

## Session start protocol — MANDATORY

**On the FIRST substantive user message of a new conversation about
strava-coach** (heuristic: no prior assistant turns about this project visible
in the history), invoke the **memory-consolidate** skill BEFORE addressing
the user's request. The skill will:

1. Audit every memory file for age, vagueness, and data leaks (numeric values that shouldn't be in narrative)
2. Detect stale opinions, missing topics, entries that need the user's confirmation
3. Run a short HITL clarification with you using AskUserQuestion (only when
   findings are ambiguous — apply unambiguous fixes silently)
4. Update memory files in place
5. Touch `.session_state.json` so the same session doesn't re-trigger

After consolidation, proceed with the user's actual request. Total cost is
typically <2 seconds + at most 1–3 short questions if memory is dirty.

**The user can also trigger consolidation explicitly** by saying things like:
- "refresh memory"
- "review my profile"
- "what do you remember about me"

Recognise these as memory-consolidate intent and run the skill.

**Skip** the auto-trigger only when:
- The user's first message is a one-shot factual question that doesn't depend
  on stored profile (e.g., "what's the formula for TSS?", "list the skills")
- The user has explicitly opted out in this session ("don't consolidate now")
- `.session_state.json` shows last_consolidation_at within the last 12 hours

---

## Memory access by intent — read selectively

**Do NOT load all memories on every turn.** That's noisy and dilutes
relevance. Instead, read by type based on what the user is asking:

| User intent | Read these memory types | Example |
|---|---|---|
| Asking about training state, fitness, fatigue, today's plan | `project` (current state) + `user` (athlete profile for thresholds) | "how is my form?" |
| Asking about PRs, benchmarks, past achievements | `user` (stable facts) | "what's my 5K PR?" |
| Asking about project conventions, "how do we do X" | `feedback` (preferences/corrections) + `project` (decisions) | "should I use mocks here?" |
| Asking about external systems, links, tools | `reference` | "where is the Linear board?" |
| Asking general code/algorithm questions unrelated to user profile | NONE — just answer | "what's the Riegel formula?" |
| About to make a recommendation that depends on user benchmarks | `user` (for qualitative context) + **re-run the skill** for live values | "what should my Z2 pace be?" |

**Verification rule:** memory stores opinions, not data. When a recommendation
needs a numeric value (FTP, threshold pace, max HR, CTL), **re-run the
relevant skill** to get the live number from the DB. Never quote a numeric
value from memory — it may be stale. Memory tells you *how to frame* the
result; the skill tells you *what the result is*.

**Format for reading**: glob the `memory/` directory, parse frontmatter,
filter by `type:`. Don't dump full contents into context unless you actually
need them for this turn.

---

## Memory protocol — MANDATORY

This project uses Claude Code's native memory system (the `memory/` directory
under `~/.claude/projects/-home-alfernandez-PycharmProjects-strava-coach/`).
**You MUST save observations and conclusions to memory after every meaningful
interaction with the user about their training.** This is non-negotiable —
the user has explicitly asked for it to be insistent.

### What to save (qualitative only — NO raw data)

Memory is narrative, not a database mirror. **Never store raw numeric values
that are recomputable from the DB** (PRs, FTP, threshold pace, CTL numbers,
cadence averages). Those live in `activities`, `best_efforts`, etc. and the
skills recompute them on demand.

Save a memory entry every time you:

1. **Reach an opinion about the user's training state** — e.g. "user is
   overreached and needs to back off — stacking hard sessions after rest
   gaps is a recurring pattern" → save as `project` memory.
2. **Discover a qualitative fact about the user** — e.g. "user runs primarily,
   has no power meter, tends to run too fast on easy days, beginner-to-
   intermediate level" → save as `user` memory.
3. **Receive feedback or correction** — e.g. "user wants warnings when stale
   PRs are >180 days, not 90" → save as `feedback` memory.
4. **Make a decision the user validated** — e.g. "user agreed that for short
   races we anchor on the 5k effort, not 10k" → save as `feedback` memory.
5. **Detect a training plan, goal or intention** — e.g. "user is preparing a
   half marathon for 2026-06-15, has never raced before" → save as `project`
   memory.

### How to save

Each memory is a markdown file with frontmatter:

```markdown
---
name: <descriptive title>
description: <one-line hook for future relevance check>
type: <user|feedback|project|reference>
---

<content — for feedback/project, structure as: rule/fact + **Why:** + **How to apply:**>
```

Save to:
`~/.claude/projects/-home-alfernandez-PycharmProjects-strava-coach/memory/<filename>.md`

Then add a one-line index entry to `MEMORY.md` in that same directory:
`- [Title](file.md) — short hook`.

### Memory hygiene

- **Update**, don't duplicate. If a fact already exists in memory, edit the
  existing file rather than creating a new one.
- **Convert relative dates** ("next Thursday") to absolute dates
  ("2026-04-16") so memories remain meaningful.
- **Outdated opinions must be refreshed.** If the user's training pattern
  shifts (e.g., from overreached to fresh), update the memory.
- **If memory contains a numeric value** that you didn't remove yet, ignore
  it — re-run the skill to get the live value from the DB.
- **Check before recommending.** A memory that names a fact may be stale.
  Before acting on it, verify against the current data.

### Pattern: end every analytics interaction with a memory write

When you run a skill and present results to the user, your final action
(after presenting) should be to write a memory entry capturing the
**qualitative observation** — NOT the raw numbers. The data is recomputable;
the coach's opinion is not. Examples:

- After `training-load`: "User is currently overreached. Pattern: burst of
  hard sessions after a rest gap. Needs to learn progressive loading."
- After `run-race-predictor`: "User is in early/slow running shape. His 5K
  anchor puts him in the recreational tier. Don't suggest aggressive race
  goals yet."
- After `run-pace-zones`: "User runs almost everything at threshold effort.
  Needs to discover truly easy running — maybe suggest a heart-rate cap."
- After `polarization-check`: "Distribution is pyramidal, not polarized. Too
  much time in the moderate zone. This is consistent with the pace-zones
  finding."

**Only save if the observation is NEW or CHANGED.** Don't rewrite the same
memory if nothing shifted since the last run.

---

## Skill orchestration: chaining

Skills can and should invoke other skills when prerequisites aren't met.
Each `SKILL.md` includes a "On error: auto-recovery chain" section that maps
specific error messages to a follow-up skill invocation. The standard chain:

- `NO_TOKEN` / auth error → invoke **strava-setup**, then retry
- `Sync first` / no data → invoke **strava-sync** with the right `--level`,
  then retry
- Any other error → surface to the user

The Skill tool is the mechanism: `Skill(skill="strava-sync", args="--level details --limit 50")`.

You may chain at most ONCE per attempt, to avoid infinite loops.

---

## How to behave

- **Pick the most specific skill.** Don't run the legacy `strava-coach`
  3-branch skill if a focused one exists.
- **Don't ask for permission to invoke a sub-skill** (sync, setup) when
  recovery is needed — just chain and continue.
- **Use natural language activators.** The user shouldn't need to type
  `/skill-name`.
- **Always end an analytics interaction with a memory write** (see Memory
  protocol above).
- **Surface trends, not just snapshots.** When showing CTL today, also note
  the delta vs last week. Re-run with a wider `--days` window if needed.
- **Defaults are reasonable but not personal.** Skills accept HR-max, FTP,
  weight, threshold-pace as flags. The first time you learn the user's real
  values, note them qualitatively in memory (e.g. "user's HR-max is high for
  his age, probably needs re-testing") and pass the values on subsequent runs.
  Never store raw numbers in memory — pass them as CLI flags computed from
  the context of the conversation.
- **Memory is narrative, not a database.** Data lives in SQLite and is
  recomputed on demand. Memory stores only opinions, patterns, coaching
  notes, and validated decisions. See the Memory protocol section.

---

## Repository layout

```
strava-coach/
├── .claude/skills/         # 27 skills (each with SKILL.md, metadata.json, scripts/)
│   ├── athlete-snapshot/scripts/  # read/update/full_refresh snapshot (shared by many skills)
│   ├── strava-coach/scripts/      # list_activities, get_stats, propose_sessions
│   ├── strava-setup/scripts/      # setup_oauth, save_profile
│   ├── strava-sync/scripts/       # sync.py
│   └── <other-skill>/scripts/     # each analytics skill has its own script
├── strava/                 # Shared library (client, db, analytics, sync, snapshot)
├── strava_coach.db         # Local SQLite cache (gitignored)
├── .env                    # STRAVA_CLIENT_ID + STRAVA_CLIENT_SECRET (gitignored)
├── README.md
└── CLAUDE.md               # this file
```
