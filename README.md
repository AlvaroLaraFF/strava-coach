# strava-coach

An AI-powered personal endurance coach built on [Claude Code](https://claude.com/claude-code) and the Strava API. Ask questions about your training — fitness, fatigue, race readiness, PRs, pace zones, power curves, swim efficiency — and get data-driven, coach-quality answers instantly.

## Philosophy

**Data lives in the database. Opinions live in memory. Everything else is computed on the fly.**

- Raw activity data is synced once from Strava into a local SQLite cache and never duplicated.
- Sports-science formulas (TRIMP, NP, TSS, CTL/ATL/TSB, Riegel, VDOT, GAP, ACWR...) are pure functions that recompute from the raw data every time — no stale snapshots.
- Claude Code's native memory system stores only qualitative coaching observations: patterns, tendencies, preferences, validated decisions. Never raw numbers.
- Every skill auto-chains to sync or setup when data is missing, so you never hit a dead end.
- Natural language is the interface. Slash commands work but aren't required.

## What you can ask

| Category | Example questions | Skills that answer |
|---|---|---|
| **Fitness & form** | "how is my form?", "can I train hard today?" | training-load, readiness-today |
| **Overtraining** | "am I overtrained?", "should I back off?" | overtraining-check |
| **Training pattern** | "am I 80/20?", "am I consistent?" | polarization-check, consistency |
| **Running** | "predict my 10K", "my PRs", "pace zones", "cadence" | run-race-predictor, run-pr-tracker, run-pace-zones, run-cadence-form, run-decoupling |
| **Cycling** | "my power curve", "what's my FTP?", "TSS per ride" | ride-power-curve, ride-ftp-estimate, ride-tss-load, ride-climbing |
| **Swimming** | "my SWOLF", "CSS pace", "swim volume" | swim-swolf, swim-css, swim-volume |
| **Triathlon** | "combined load", "am I balanced across sports?" | tri-combined-load, tri-discipline-balance |
| **Goals & log** | "weekly summary", "my goal for the year", "shoe mileage" | weekly-log, goals-tracker, gear-mileage |
| **Advanced** | "do I run worse in heat?", "have I improved on this route?" | weather-correlation, matched-activities |
| **Visualization** | "show me a heatmap of where I train" | personal-heatmap |
| **Maintenance** | "sync my activities", "refresh memory" | strava-sync, memory-consolidate |

27 skills total. Each one has its own Python CLI script that outputs JSON, so they also work without Claude Code.

## Requirements

- Python 3.10+
- `requests` (installed automatically by the setup wizard)
- A Strava account and API application (free — https://www.strava.com/settings/api)
- [Claude Code](https://claude.com/claude-code) for the AI coaching layer

## Setup

Open this project in Claude Code and say:

> set up strava-coach

The setup wizard checks Python, installs dependencies, initializes the database, walks you through creating a Strava API app, and completes the OAuth flow. One-time, ~2 minutes.

## Architecture

```
strava-coach/
├── strava/                     # Shared Python library
│   ├── client.py               #   Strava API client (OAuth2, retry, rate limiting)
│   ├── db.py                   #   SQLite schema (11 tables) + helpers
│   ├── analytics.py            #   Pure-function sports-science formulas (~25 algorithms)
│   └── sync.py                 #   Incremental sync orchestration
│
├── .claude/skills/             # 27 Claude Code skills
│   ├── strava-setup/           #   First-time wizard
│   ├── strava-sync/            #   Three-level data sync (summary → details → streams)
│   ├── memory-consolidate/     #   Session-start memory audit
│   ├── training-load/          #   CTL/ATL/TSB (Performance Management Chart)
│   ├── readiness-today/        #   Today's training verdict
│   ├── run-race-predictor/     #   5K/10K/HM/M predictions (Riegel + VDOT)
│   ├── ride-power-curve/       #   Mean-max power curve
│   ├── swim-swolf/             #   SWOLF efficiency trend
│   └── ... (18 more)           #   One skill per question type
│
├── scripts/                    # Legacy root scripts (still functional)
├── CLAUDE.md                   # Project guide for Claude Code
├── .env.example                # Template for Strava credentials
└── requirements.txt
```

Each skill folder contains:
- `SKILL.md` — instructions for Claude Code (when to activate, how to present, error recovery chain, memory protocol)
- `metadata.json` — tags and description
- `scripts/` — Python CLI(s) that do the computation and output JSON

## Data flow

```
Strava API  ──sync──►  SQLite DB  ──query──►  analytics.py  ──JSON──►  Claude Code
(source of truth)      (local cache)           (pure formulas)          (interprets,
                                                                         coaches,
                                                                         remembers)
```

- **Numeric data** flows left-to-right and is recomputed every time.
- **Qualitative memory** (opinions, patterns, coaching notes) is written by Claude Code into `memory/*.md` files after each interaction.
- **Zero duplication** between the database and memory. Memory never stores raw values.

## Sync levels

| Level | What it fetches | Speed | Unlocks |
|---|---|---|---|
| `summary` | Activity list from `/athlete/activities` | seconds | Most skills |
| `details` | Full payload per activity (`/activities/{id}`) | ~0.7s/activity | PRs, splits, cadence |
| `streams` | Per-second time series (`/activities/{id}/streams`) | ~0.7s/activity | Power curve, decoupling, TSS |
| `zones` | Athlete HR + power zones | instant | Personalized zone analysis |

Sync is automatic — skills invoke it when they need data that isn't cached yet.

## Credentials & privacy

- Credentials live in `.env` (git-ignored). **Never commit this file.**
- OAuth tokens are stored in `strava_coach.db` (also git-ignored) and refreshed automatically.
- All data stays local — nothing is sent anywhere except the Strava API itself.
- Memory files are stored under `~/.claude/projects/` (outside the repo, never committed).

## License

MIT
