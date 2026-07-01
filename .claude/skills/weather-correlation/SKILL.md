---
name: weather-correlation
description: >
  Cross-reference activities with environmental data from Open-Meteo (free,
  no key) to find correlations with performance. Invoked in two contexts:
  (a) the user asks an explicit environmental question (heat, allergies,
  pollen, pollution, "do I run worse on bad-air days");
  (b) auto-triggered after `session-analysis` or weekly-closure to
  factor environmental conditions into the qualitative read before
  memory is written. Picks the right internal mode and window from
  the invocation context — callers do not need to know the script names.
allowed-tools: Bash(python3 *), Read
---

# weather-correlation

## How to pick the mode

The skill has two internal scripts. Decide based on the invocation
context — do not ask the user.

| Context | Run | Why |
|---|---|---|
| User explicitly asks about heat / temperature only | `weather.py` (Mode 1) | Cheap, single-variable verdict |
| Any allergy / pollen / pollution / air quality question | `air_quality.py` (Mode 2) | Full env vector + HR residual |
| Post `session-analysis` (auto-triggered) | `air_quality.py` (Mode 2) | Need pollen + PM to disambiguate fatigue vs environment |
| Post weekly-closure (auto-triggered) | `air_quality.py` (Mode 2) | Same reason, plus week-level review |
| Unclear or first time in window | `air_quality.py` (Mode 2) | Superset; covers temperature too |

Default to Mode 2 unless the user's question is unambiguously about
heat alone. Mode 2's cache makes it cheap on repeat calls — there is
no good reason to bias toward Mode 1.

## Window selection

| Caller intent | `--days` |
|---|---|
| Single recent session lookup | 30 |
| Weekly closure (last ISO week) | 14 |
| User explores patterns ("am I worse in the heat", "does pollen affect me") | 90 |
| Full season baseline / first run | 180 |

If the user names a window, honour it. Otherwise pick from the table.

## Mode 1 — Temperature vs pace (legacy)

```bash
python3 .claude/skills/weather-correlation/scripts/weather.py --days 60 --sport Run
```

Per-activity table: date, temp (°C), pace, HR. Then a one-line correlation
verdict ("each +5°C costs ~10s/km", or "no clear correlation"). Use when
the user asks specifically about heat impact and nothing else.

## Mode 2 — Air quality + pollen + temperature (preferred)

```bash
python3 .claude/skills/weather-correlation/scripts/air_quality.py --days 90
```

For every activity in the window that carries HR + distance + GPS start
coordinates, fetches hourly air quality (PM10, PM2.5, ozone, NO2, SO2,
European AQI), six pollen species (alder, birch, grass, mugwort, olive,
ragweed — CAMS Europe, grains/m³) and ambient temperature at the activity
start hour. Results are cached locally in the `env_hourly` table keyed by
(lat_grid 2dp, lng_grid 2dp, hour_utc), so repeated runs only hit the API
for new locations or extended windows.

### Body metric: HR residual (not raw HR)

For each sport with ≥3 sessions, the script fits a per-sport OLS
regression `avg_hr = α + β · pace_min_km` and computes
`hr_residual_bpm = actual_avg_hr − predicted_avg_hr` for each activity.

This is the right body signal because raw HR is dominated by effort:
faster sessions naturally have higher HR. The residual answers
"given how fast you ran, was your HR higher or lower than usual?"
A residual of +6 bpm means: at that pace, you'd normally hold X bpm,
but on that day you held X+6 — which is the classic signature of
"the body had to work harder than the pace says it should".

### Clinical / regulatory thresholds (not personal percentiles)

| Variable | low / good | moderate | high / unhealthy | very high / very unhealthy |
|---|---|---|---|---|
| grass_pollen (grains/m³) | <20 | 20–50 | 50–200 | >200 |
| olive_pollen | <10 | 10–50 | 50–200 | >200 |
| birch, alder, mugwort, ragweed | <10 | 10–50 | 50–200 | >200 |
| pm2_5 (μg/m³, 24h proxy) | <15 (WHO) | 15–25 | 25–50 | >50 |
| pm10 (μg/m³) | <45 (WHO) | 45–100 | 100–150 | >150 |
| ozone (μg/m³, hour proxy) | <100 | 100–160 | 160–240 | >240 |

These buckets come from CAMS Europe (pollen) and WHO 2021 air-quality
guidelines (PM, ozone). They are population-level thresholds, not
personalised — the same number means the same thing across users.

### Output schema

`rows` carries one entry per activity with the body data + env values
+ a `env_flags` list naming any variable that hit `high`/`unhealthy`
or worse. `correlations.<sport>.per_variable` reports Pearson r between
each env variable and the HR residual, with strength label
(`STRONG ≥0.5`, `MODERATE 0.3-0.5`, `WEAK 0.15-0.3`, `NONE <0.15`).
`threshold_buckets.<sport>.<variable>.<label>` reports the mean HR
residual conditioned on each clinical bucket, with sample count.
`top_flagged_days` lists activities that hit ≥2 high thresholds at
once — the candidates where a single day combined multiple stressors.

### Present — branch by invocation context

**A) Auto-triggered after `session-analysis` (single-session lookup)**

The caller already has the body data and needs only the environmental
verdict for one specific session. Do NOT dump the full correlational
analysis — that's noise here. Instead:

1. Look up the row in `rows` matching the session (by `strava_id` or
   `date`).
2. Render ONE compact line per relevant variable that reached at
   least `moderate`, or simply "env clean" if everything is in `low`/`good`.
   Format: `grass_pollen: 35 grains/m³ (moderate) · pm2_5: 18 μg/m³ (moderate) · others clean`.
3. State the session's `hr_residual_bpm` and frame it: "HR residual
   −2 bpm — below expected for the pace, NOT consistent with an
   environmental stressor pulling HR up".
4. Close with a single coach-line: does the environmental data
   support, contradict, or stay silent on the session-analysis
   verdict? This is what the caller will fold into their memory
   write.

**B) Auto-triggered after weekly-closure (multi-session review)**

Render the 4–7 sessions of the closed week as a compact table:
`date · session_type · hr_residual · env_flags`. Highlight any row
with `env_flags` non-empty. Close with one line per week:
"environmental conditions across the week were [clean / mixed /
challenged]; sessions [N] / [N] flagged".

**C) Explicit user question about environment / patterns**

The full picture:

1. **One-line verdict per sport**: which env variable (if any) shows
   the cleanest signal in *this* user's data. Cite r and n.
2. **Per-activity table** (top 10 by date, descending): date, sport,
   pace, avg HR, HR residual, grass pollen, olive pollen, PM2.5,
   ozone, temp.
3. **Threshold buckets table** for the variables that reached at
   least `moderate` in the sample: mean HR residual per bucket with n.
4. **Caveats**: state the sample size explicitly. Below ~30 sessions
   per sport, treat correlations as noise. Below ~10 per bucket, do
   not draw conclusions about that bucket. Note collinearity: in
   spring, pollen and temperature rise together — a "pollen effect"
   may partly be a heat effect, and vice versa.

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `No activities` / `Sync first` / `No activity had usable GPS` | Invoke **strava-sync** `--level summary`, retry |
| anything else | Surface |

Chain at most ONCE.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching
notes. **Never store raw numeric values** (those are recomputable from
the cache and the DB). Only write if the observation is NEW or CHANGED
vs existing memory. Examples of what to save:

- "PM2.5 shows weak positive correlation with HR residual on runs —
  worth re-checking once sample size doubles."
- "Pollen signal is noisy because grass season overlaps with the
  athlete's fitness gain block; not separable yet."
- "Single high-PM2.5 day produced a clear HR spike — flag this when
  planning quality sessions on city-air days."

See CLAUDE.md → Memory protocol.
