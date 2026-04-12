---
name: memory-consolidate
description: >
  Audit and refresh the project's memory bank. Cross-references each user/project
  memory entry for age, vagueness, and data leaks. Detects stale opinions,
  missing topics, and entries that need user confirmation. Runs HITL clarification
  with the user to keep memory fresh. Use at the start of each new session AND
  whenever the user asks to review memory, refresh what you know about them,
  or update the memory bank.
allowed-tools: Bash(python3 *), Read, Write, Edit, AskUserQuestion
---

# memory-consolidate

This skill keeps the persistent memory bank for `strava-coach` aligned with
reality. Memory entries decay — the user's threshold pace shifts, new PRs
appear, FTP changes, sports get added. Without periodic consolidation,
recommendations drift from facts.

## When to run this skill

1. **Automatically at session start** — see CLAUDE.md → "Session start
   protocol". On the first substantive message of a new conversation about
   strava-coach, invoke this skill BEFORE addressing the user's request.
2. **On explicit request** — when the user asks to review memory, refresh
   what you know, or similar intent.
3. **Opportunistically** — if you notice a contradiction between memory and
   live data while running another skill, invoke this one to fix the entry.

## Run

```bash
python3 .claude/skills/memory-consolidate/scripts/consolidate.py
```

The script outputs a JSON report of findings, each tagged with a type:

| Finding type | Meaning |
|---|---|
| `stale` | Memory references a value that newer data contradicts |
| `missing` | DB has data that isn't reflected in any memory entry |
| `outdated` | Memory file's date is >14 days old and refers to a fast-changing topic |
| `orphan` | Memory references a file path / function that no longer exists |
| `ok` | Memory is consistent with current state |

## How to act on the report

1. **If `findings` is empty** — tell the user one short line ("memory is up to
   date — last consolidation: X") and proceed with their original request.

2. **If 1–3 findings** — apply them yourself without asking, EXCEPT when a
   value is ambiguous (e.g., the user might have set a new PR vs. the old one
   being correct). For unambiguous updates, just edit the memory file and
   tell the user one line about what changed.

3. **If ≥4 findings, OR any ambiguous one** — use **AskUserQuestion** to ask
   the user **at most 3 questions** to disambiguate. Group related findings
   into a single question. Examples:
   - "I see 4 new PRs in your DB that aren't in memory — should I add them to
     your athlete profile? (yes / no / show me)"
   - "Your training_state memory says TSB −25.5 from 2026-04-12 but today's
     CTL/ATL puts you at TSB +3. Should I overwrite or keep both?"
   - "I see Ride activities in your DB but no cycling section in your
     athlete profile — are you actively cycling, or were these one-offs?"

4. **After applying** — update `MEMORY.md` index if files were created or
   removed. Touch `.session_state.json` to record the consolidation timestamp
   so the same session doesn't re-trigger.

## Memory file conventions (keep when editing)

Each memory file at
`~/.claude/projects/-home-alfernandez-PycharmProjects-strava-coach/memory/<name>.md`
follows this frontmatter:

```markdown
---
name: <descriptive title>
description: <one-line hook>
type: <user|feedback|project|reference>
---

<content>
```

When updating:
- **Edit, don't duplicate.** If `user_athlete_profile.md` already exists, edit it. Don't create `user_athlete_profile_v2.md`.
- **Convert relative dates** ("last week" → "2026-04-05") on save.
- **For `project` memories that snapshot state**, the convention is
  `project_training_state_<YYYY_MM_DD>.md`. If today's snapshot doesn't yet
  exist, create one and remove the previous one once it's >14 days old (the
  raw data lives in the DB and is recomputable — memory files are for
  qualitative observations only).
- **Update `MEMORY.md` index** with one line per entry.

## Pre-flight

This skill always works (no token required) — it only reads local files and
the local SQLite DB.
