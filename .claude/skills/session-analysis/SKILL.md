---
name: session-analysis
description: >
  Deep narrative analysis of a single training session: auto-narrative,
  per-km splits, HR drift, cadence, elevation profile + GAP, slowdown
  explainer, similar-session baseline, PR detection, plan comparison.
  Use when the user asks "analyze today's run", "how did my session go",
  "session detail", "per-km splits", "desglose por km", "qué tal mi sesión".
allowed-tools: Bash(python3 *), Read
---

# session-analysis

Takes a date or strava_id and produces a deep dive into a single activity.
Output is a JSON with:

- `narrative`: 4–8 ready-made English bullets summarising the run; the assistant translates them to the user's conversation language at presentation time
- `summary`: distance, duration, avg pace, avg/max HR, calories, device
- `splits`: per-km table with pace, HR, elevation delta, cadence, HR + pace zone
- `pace_shape`: classifies the run as `progressive`, `fade`, `u_shape`, `surge`, `even`
- `hr_drift`: first-half vs second-half HR + pace
- `pace_stats`: avg, std-dev, fastest/slowest km, negative split flag
- `zone_distribution`: km count per HR-zone (Karvonen) or pace-zone fallback
- `elevation`: total gain/loss, time-in-bucket (uphill/flat/downhill), GAP, steepest grade
- `slowdown`: which kms ran significantly slower than the median and the most likely cause for each (uphill, cardiac drift, cadence drop, intrinsic)
- `similar_sessions`: median pace/HR of the last 10 same-sport runs at ±20% distance, plus the delta of this session vs that baseline + rank in the band
- `most_similar`: full per-km analysis (summary + splits + drift + shape) of the single most-comparable past run (±15% distance, weighted score on distance/elevation/recency, with same-session_type bonus when a planned context exists)
- `side_by_side`: km-by-km comparison rows between this session and `most_similar` — pace, HR, elevation, cadence, plus a `headline` with delta distance/duration/pace/HR/elevation
- `prs`: any best_efforts where this run reached top-5 all-time (with `is_pr_today` flag)
- `plan_comparison`: actual vs planned duration / distance / HR range / pace range
- `interval_breakdown`: rep / recovery / warmup / cooldown segments for sessions with structure (fartlek / intervals / tempo). Built from watch laps when the lap pattern is clearly bimodal; falls back to per-second streams + planned blocks when not. Includes an `aggregate` block (avg rep pace / HR / cadence + trends) that powers the cross-session view.
- `recent_intervals`: rep-aggregated comparison against the user's recent interval sessions (lap-based detection over the last 120 days, up to 5 sessions). Each row carries the session date, n_reps, avg rep pace, avg rep HR, avg rep cadence; `delta_vs_previous` summarises this session against the most recent prior interval session.

## Run

```bash
# By date (picks the most recent activity on that day)
python3 .claude/skills/session-analysis/scripts/session_analysis.py --date 2026-04-26

# By Strava ID (unambiguous)
python3 .claude/skills/session-analysis/scripts/session_analysis.py --strava-id 18248717632

# With auto-sync before analysis
python3 .claude/skills/session-analysis/scripts/session_analysis.py --date 2026-04-26 --sync

# Wider window for similar-session baseline (default 90 days)
python3 .claude/skills/session-analysis/scripts/session_analysis.py --strava-id <id> --similar-window 180
```

## Detecting interval / fartlek structure (CRITICAL — read before evaluating)

**Sessions with structure must NEVER be evaluated using per-km auto-splits.**
A 1 km auto-split aggregates one 3-minute Z4 rep with a 2-minute jog
recovery into a single Z3-looking row. The structure disappears, and so
does any honest verdict on the session.

The script detects interval structure automatically from watch laps —
the laps the athlete pressed on the device. Detection runs whenever lap
data is available, regardless of whether the planned session declared
work blocks. The trigger is purely the shape of the lap pace
distribution.

`interval_breakdown.source` is one of:

- `"laps"` — primary path. Built from `activity_laps` (or the laps
  embedded in the activity's raw_json when the dedicated table is
  empty).
- `"streams"` — legacy fallback. Used only when the planned session
  carries `session_type` in {fartlek, interval, tempo} AND has work
  blocks AND the lap-based path didn't fire.

### Lap-based detection — when does it fire?

A session is classified as an interval session iff ALL of the following
hold simultaneously:

1. **Bimodal pace distribution.** Sorted lap paces show a gap of at
   least 1.5 min/km between two clusters. The gap must sit in the
   central portion of the distribution so each cluster holds at least
   ~20% of the laps. This rules out "one slow km in an otherwise
   continuous run".
2. **Rep cluster vs recovery cluster ratio.** The rep cluster average
   pace must be at most 80% of the recovery cluster average — i.e.
   reps are meaningfully faster than recoveries, not just slightly
   faster. Filters out walk-jog sessions where both clusters are slow.
3. **Rep paces are tight as a cluster.** The coefficient of variation
   of the rep paces must be ≤ 15%. A "rep cluster" with paces from
   6:46 to 12:15 is not a coherent rep set — it's a session that
   started running and ended walking.
4. **Rep pace is fast in absolute terms.** Anchored on the athlete's
   threshold pace from their snapshot (rep avg ≤ threshold × 1.10).
   Without a snapshot, the script falls back to a generic running
   ceiling of 7:30/km. A "rep" slower than threshold isn't a rep.
5. **Rep duration consistency.** The CV of rep durations is ≤ 60%.
   Real reps are roughly the same length; wildly different durations
   point to a hike or auto-lap noise.
6. **Minimum reps.** At least 3 detected rep candidates.

When the planned session is itself a fartlek/interval/tempo, the rep
threshold is taken from the plan's `pace_fast_min_km × 1.10` instead of
the bimodal heuristic — the plan declared rep pace explicitly, so we
trust it.

### What the breakdown contains

When `source == "laps"`:

```
{
  "source": "laps",
  "aggregate": {
    "n_reps": 5,
    "avg_rep_pace_min_km": 5.011,
    "avg_rep_pace_str": "5:00",
    "avg_rep_hr": 168.1,
    "avg_rep_max_hr": 177.2,
    "avg_rep_cadence": 84.8,
    "avg_rep_duration_s": 182,
    "rep_threshold_pace_min_km": 5.5,
    "cadence_trend": "ascending",
    "hr_trend": "ascending",
    "pace_trend": "descending",
    "reps_reached_hr_target": 5,
    "target_hr_min": 170
  },
  "warmup":   [...],
  "reps":     [...],   # 1 row per rep, with hr_peak_verdict when target known
  "recoveries":[...],  # 1 row per gap between reps
  "cooldown": [...]
}
```

`reps[*]` and `recoveries[*]` rows include lap_index, name, pace,
avg_hr, max_hr, avg_cadence, duration_str, distance_m, elevation_gain_m.
Reps additionally carry `rep_num` and (when planned context exists)
`hr_peak_verdict` ∈ {`reached`, `below`} plus `target_hr_min`.

## Cross-session comparison: `recent_intervals`

When the focal session is detected as an interval session (i.e.
`interval_breakdown.aggregate` is present), the script also runs the
same lap-based detection over the last 120 days of activities and
keeps up to 5 prior sessions that pass the same trigger conditions.

The `recent_intervals.rows` array is ordered oldest-first → newest,
with the focal session appended at the end as `(this session)`. Each
row carries n_reps, avg rep pace, avg rep HR, avg rep cadence, avg
rep duration. `delta_vs_previous` compares the focal session against
the most recent prior entry.

This is the right view for progression in interval training:
per-km splits hide the structure, and the legacy `similar_sessions`
median (which mixes session types) doesn't tell you whether your reps
got faster or your HR settled. Anchor progression on
`recent_intervals.delta_vs_previous` whenever it exists.

## Present (order matters)

1. **Narrative first**: render the bullets in `narrative` as the lead
   paragraph. They are the executive summary — show them verbatim.
2. **Interval breakdown** (PRIMARY view when
   `interval_breakdown.reps` is present): one row per detected rep —
   `# | duration | distance | pace | HR avg | HR peak | cadence | HR peak verdict`.
   Follow with a recovery-gaps table —
   `after rep | duration | HR at end | duration vs target`.
   Include warmup and cooldown laps as a brief framing line above the
   table. **Do NOT lead with per-km splits for interval sessions** —
   they hide the structure (a 3-min Z4 push buried in a 1 km split
   looks moderate).
3. **Recent intervals progression**: render `recent_intervals.rows` as
   a small table — `date | n_reps | avg rep pace | avg rep HR | avg
   rep cadence`. Lead with `delta_vs_previous` as a one-liner ("vs
   last interval session on YYYY-MM-DD: rep pace +X s/km, HR +Y bpm,
   cadence +Z spm"). This is the cleanest progression signal for
   interval training.
4. **Per-km splits table** (PRIMARY for easy / long / steady runs,
   secondary for intervals): km, pace, avg HR, max HR, elev Δ, cadence,
   HR-zone.
5. **Pace shape + HR drift**: one short paragraph combining `pace_shape`
   and `hr_drift`. Flag drift > 5%. For interval sessions, note that
   per-km drift mixes work and recoveries and is therefore not
   informative — anchor drift assessment on the rep HR trend instead.
6. **Slowdown breakdown**: render the worst 2–3 splits from
   `slowdown.slow_splits` as `Km X (Δ +Y s/km vs median) → cause: …`.
   If `slowdown.n_slow == 0`, skip this section silently — there's
   nothing to explain.
7. **Elevation profile** (only if `elevation.buckets` is present):
   total gain/loss, distribution uphill / flat / downhill, GAP vs actual
   pace, steepest grade and where it was. Skip if the activity is flat
   (`total_gain_m < 30 m` AND no terrain cost).
8. **Side-by-side closest match**: render `side_by_side` as a paired
   table — `Km | this pace | other pace | Δ s/km | this HR | other HR
   | Δ HR | this elev | other elev`. Above the table, summarise the
   `headline`: dates, age in days, distance/elevation match quality,
   and the global deltas (pace, HR, elevation). For continuous runs
   this is the primary progression signal — it compares like-for-like.
   For interval sessions, prefer `recent_intervals` over this section
   because the side-by-side compares per-km values that mix reps and
   recoveries.
9. **Similar-session baseline**: render `similar_sessions` as a
   one-liner — "median over N similar runs (distance band X–Y km) is
   Z/km — this session is N s/km {faster | slower | in line}, HR delta
   D bpm". Then state the rank in the band. This is a secondary signal
   (mixes session types); always anchor on the side-by-side first
   (continuous runs) or `recent_intervals` (interval sessions).
10. **PR section**: if `prs` is non-empty, lead with all-time PRs first,
    then top-5 placements. Mention total attempts to give context ("PR
    on 1 mile out of 93 historical attempts").
11. **Plan comparison** (if `plan_comparison` present): actual vs planned
    for duration, distance, HR range, pace range, with verdicts. For
    interval sessions, anchor the interpretation on the interval
    breakdown — global pace/HR averages mislead.
12. **Zone distribution**: brief — count of kms per Z1-Z5.

## Evaluating an interval session (REQUIRED logic)

Apply these rules (consistent with `feedback_hr_zones_primary` and
`feedback_intervals_use_laps`):

- **HR is the primary target.** If `hr_peak_verdict == "reached"`, the rep
  is successful — regardless of pace. A rep with HR peak inside target
  but pace faster than the planned range is NOT a deviation; it is the
  physiologically necessary consequence of reaching HR target in a short
  window (HR takes 30–45 s to respond).
- **Pace is informational in intervals ≤ 90 s.** Only flag pace if the
  athlete dropped below the pace_slow end (never pushed) or hit
  sprint-maximum (different session type).
- **Extended recoveries are self-regulation, not failure.** If recoveries
  grew longer than planned *and* HR did drop below the recovery ceiling
  before the next rep, the athlete protected the work. Flag the opposite.
- **Anchor verdicts on the rep aggregate, not on global averages.** A
  fartlek's avg HR (mixing reps and recoveries) will look moderate even
  when reps maxed out Z4. Use `interval_breakdown.aggregate` and the
  per-rep verdicts; never say "did not complete the plan" just because
  global avg pace or duration diverged.
- **Read trends across reps.** Cadence ascending and HR holding (not
  drifting up uncontrollably) within reps are signs the athlete is
  controlling the session. Cadence descending and HR climbing rep over
  rep are signs of fatigue / under-recovery.

## Reading the slowdown output

Each entry in `slowdown.slow_splits` carries one or more `reasons`. They
are not mutually exclusive — a single split can be flagged for both
`uphill` and `cardiac_drift`. When presenting:

- Lead with the dominant cause. Order by inherent severity:
  `uphill` (geography) > `cardiac_drift` (physiology) >
  `cadence_drop` (form) > `intrinsic` (effort).
- If `intrinsic` is the only cause, say so plainly: nothing external
  explains the drop — it was effort or willpower. Do not invent reasons.
- If `elevation.gap_pace` exists, cross-reference: a split flagged
  `uphill` whose GAP is in line with the median is "the hill, not you".

## On error: auto-recovery chain

| Error contains | Action |
|---|---|
| `No token` | Invoke **strava-setup**, retry |
| `No activity found` | Invoke **strava-sync** `--level summary`, retry with `--sync` |
| `splits_metric not available` | Invoke **strava-sync** `--level details --limit 5`, retry |
| `streams not cached` (in `interval_breakdown.error` or `elevation.source == "summary_only"`) | Invoke **strava-sync** `--level streams --limit 5`, retry |
| anything else | Surface |

Chain at most ONCE.

If `interval_breakdown` is null but the session is supposed to be a
fartlek/interval (planned session_type or user description), check
that laps are stored for the activity. Laps are pulled by
`strava-sync --level details` into the activity's raw_json, but the
dedicated `activity_laps` table is only populated by skills that call
`ensure_laps()` explicitly. If neither path has the laps, fetch them
with `ensure_laps()` and re-run.

## After presenting: persist to memory (MANDATORY)

Save a qualitative observation to memory — opinions, patterns, coaching
notes. **Never store raw numeric values** (those are recomputable from
the DB). Only write if the observation is NEW or CHANGED vs existing
memory. See CLAUDE.md → Memory protocol.

## Then: propose a plan revision (when applicable)

Per CLAUDE.md → Post-session-analysis protocol, after the memory write
silently call `training-plan list` for the current ISO week. If there
are remaining `planned` sessions for this week, close the turn with a
one-line proposal to revise the rest of the week.
