---
name: strava-coach
description: >
  Query Strava and propose training sessions. Use when the user wants to see
  their recent activities, global Strava statistics, or receive training
  proposals based on their history.
allowed-tools: Bash(python3 *), Read, AskUserQuestion
---

# /strava-coach

Skill to query Strava data and propose training plans. Detects user intent and executes the corresponding branch.

## Pre-flight check

Before doing anything, verify the setup is complete:

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from strava.db import load_token
from strava.client import get_default_db_path
import os, time
errors = []
if not os.environ.get('STRAVA_CLIENT_ID'): errors.append('MISSING_CLIENT_ID')
if not os.environ.get('STRAVA_CLIENT_SECRET'): errors.append('MISSING_CLIENT_SECRET')
token = load_token(get_default_db_path())
if not token: errors.append('NO_TOKEN')
elif token['expires_at'] < time.time(): errors.append('TOKEN_EXPIRED')
print(','.join(errors) if errors else 'OK')
"
```

- If output is `OK`, proceed to intent detection.
- If there are errors, tell the user: "Setup is not complete. Run `/strava-setup` first to configure everything step by step." and stop.

---

## Intent detection

Analyze what the user asked for:
- If they mention "activities", "latest", "recent", "what did I do", "workouts" → **Branch A**
- If they mention "statistics", "totals", "summary", "how much", "stats" → **Branch B**
- If they mention "propose", "train", "plan", "sessions", "next week", "what should I do" → **Branch C**
- If unclear, ask the user with AskUserQuestion.

---

## Branch A — Recent activities

### Step 1: Determine filters
Ask the user if they want to filter by sport or number of activities, or use defaults (last 20, all sports).

### Step 2: Sync and query
```bash
python3 .claude/skills/strava-coach/scripts/list_activities.py --sync --limit 20
```

If the user requested a specific sport, add `--sport-type Run` (or Ride, Swim, etc.).
If they requested a date range, add `--days 30`.

### Step 3: Display results
Parse the JSON output. Show a formatted table with columns: Date, Type, Name, Distance, Duration, Pace/Speed, HR.

If the JSON contains `"success": false`, show the error to the user. If it's an authentication error, tell them to run `/strava-setup`.

---

## Branch B — Global statistics

### Step 1: Download statistics
```bash
python3 .claude/skills/strava-coach/scripts/get_stats.py --refresh
```

### Step 2: Display summary
Parse the JSON and present:
- **Year to date (YTD)**: distance by sport (running, cycling, swimming)
- **All-time totals**: cumulative distance by sport
- **Last 30 days**: total activities, distance, time, weekly frequency, sport breakdown

---

## Branch C — Propose training sessions

### Step 1: Sync recent activities
First make sure the database is up to date:
```bash
python3 .claude/skills/strava-coach/scripts/list_activities.py --sync --limit 50 --days 60
```

### Step 2: Ask for goal
If the user didn't specify a goal, ask with AskUserQuestion:
- Prepare for a race (5K, 10K, half marathon, marathon)
- Improve speed/pace
- Maintain fitness / general health
- Lose weight
- Other (free text)

### Step 3: Get analysis data
```bash
python3 .claude/skills/strava-coach/scripts/propose_sessions.py --days 30 --goal "GOAL" --next-days 7
```

### Step 4: Generate proposal
Using the JSON data (weekly loads, pattern analysis, recent activities), **reason as a sports coach** and generate a weekly plan that includes:

- For each day of the upcoming week: session type, estimated duration, intensity (easy/moderate/hard/rest), exercise description
- Respect the user's current frequency and volume (don't increase more than 10% weekly)
- Include at least 2 rest or active recovery days
- If HR data is available, use training zones (Z1-Z5)
- Adapt to the stated goal

Present the plan as a table: Day | Type | Duration | Intensity | Description.

---

## Error handling

| Error | Action |
|-------|--------|
| `"success": false` with auth error | Tell the user to run `/strava-setup` |
| `"success": false` with API error | Show the Strava error message |
| No activities in DB | Suggest using `--sync` to download |
