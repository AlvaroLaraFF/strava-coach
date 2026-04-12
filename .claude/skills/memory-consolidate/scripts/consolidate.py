#!/usr/bin/env python3
"""Audit memory bank for vague / aged / opinion-needs-refresh entries.

CRITICAL: this script does NOT cross-reference memory against numeric DB
values. Memory is qualitative narrative only — opinions, interactions,
progressions, training state, preferences. Numeric data lives in the DB and
is recomputed on demand. The audit here is about FRESHNESS OF NARRATIVE,
not value consistency.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.client import output_error, output_json


MEMORY_DIR = os.path.expanduser(
    "~/.claude/projects/-home-alfernandez-PycharmProjects-strava-coach/memory"
)
SESSION_STATE = os.path.join(MEMORY_DIR, ".session_state.json")
AGED_DAYS = 14
NUMERIC_PATTERN = re.compile(
    r"(\b\d+\s*(km|m|bpm|w|spm|kg|min|s|%|°c)\b|\b\d+:\d{2}\b|\bFTP\s*\d+|\b5K\b.*\d)",
    re.IGNORECASE,
)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    fm = {}
    for line in fm_block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, body


def list_memories() -> list[dict]:
    out = []
    if not os.path.isdir(MEMORY_DIR):
        return out
    for fname in sorted(os.listdir(MEMORY_DIR)):
        if not fname.endswith(".md") or fname == "MEMORY.md":
            continue
        path = os.path.join(MEMORY_DIR, fname)
        try:
            with open(path) as fh:
                content = fh.read()
        except OSError:
            continue
        fm, body = parse_frontmatter(content)
        out.append({
            "filename": fname,
            "path": path,
            "type": fm.get("type", "unknown"),
            "name": fm.get("name", fname),
            "description": fm.get("description", ""),
            "body": body,
            "mtime": datetime.fromtimestamp(os.path.getmtime(path), timezone.utc),
            "size": len(body),
        })
    return out


def detect_data_smell(body: str) -> int:
    """Count numeric leaks in a memory body — they shouldn't be there."""
    return len(NUMERIC_PATTERN.findall(body))


def main() -> None:
    try:
        memories = list_memories()
        now = datetime.now(timezone.utc)

        findings: list[dict] = []
        by_type: dict[str, int] = {}

        for mem in memories:
            by_type[mem["type"]] = by_type.get(mem["type"], 0) + 1
            age_days = (now - mem["mtime"]).days

            # Aged narrative — opinions decay
            if age_days >= AGED_DAYS and mem["type"] in ("project", "user"):
                findings.append({
                    "type": "aged",
                    "file": mem["filename"],
                    "memory_type": mem["type"],
                    "age_days": age_days,
                    "name": mem["name"],
                    "suggestion": "Ask the user one short question to confirm or refresh the narrative.",
                })

            # Vague — too short to be useful
            if mem["size"] < 80 and mem["type"] != "reference":
                findings.append({
                    "type": "vague",
                    "file": mem["filename"],
                    "memory_type": mem["type"],
                    "name": mem["name"],
                    "suggestion": "Memory is too thin — either drop it or ask the user for context to flesh it out.",
                })

            # Data smell — memory contains numeric values it shouldn't
            data_hits = detect_data_smell(mem["body"])
            if data_hits >= 3:
                findings.append({
                    "type": "data_smell",
                    "file": mem["filename"],
                    "memory_type": mem["type"],
                    "name": mem["name"],
                    "numeric_mentions": data_hits,
                    "suggestion": "This memory looks like it stores raw values. Rewrite it as qualitative narrative — values belong in the DB.",
                })

        # Open questions — opinion topics that should always exist but don't
        files = [m["filename"] for m in memories]
        if not any("athlete_profile" in f or "user_" in f for f in files):
            findings.append({
                "type": "missing_topic",
                "file": "user_athlete_profile.md (suggested)",
                "memory_type": "user",
                "suggestion": "No user profile memory exists. Ask the user about their primary sport, current goal, training preferences.",
            })

        # Session state
        prev_state = None
        if os.path.isfile(SESSION_STATE):
            try:
                with open(SESSION_STATE) as fh:
                    prev_state = json.load(fh)
            except (OSError, json.JSONDecodeError):
                pass
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(SESSION_STATE, "w") as fh:
            json.dump({"last_consolidation_at": now.isoformat()}, fh)

        output_json({
            "memory_dir": MEMORY_DIR,
            "memory_count": len(memories),
            "by_type": by_type,
            "memories": [
                {
                    "filename": m["filename"],
                    "type": m["type"],
                    "name": m["name"],
                    "description": m["description"],
                    "age_days": (now - m["mtime"]).days,
                    "size_chars": m["size"],
                }
                for m in memories
            ],
            "findings": findings,
            "previous_consolidation_at": prev_state.get("last_consolidation_at") if prev_state else None,
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
