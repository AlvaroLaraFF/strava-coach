#!/usr/bin/env python3
"""Analyze activity history and generate structured data for training proposals.

Does NOT call the Claude API — it prepares structured data for the Claude Code
skill to reason about and generate training plans.

Usage:
    python3 scripts/propose_sessions.py [--days 30] [--goal "marathon"] [--next-days 7]
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strava.client import get_default_db_path, output_json, output_error
from strava.db import init_db, get_activities_range


def _parse_date(date_str: str) -> datetime:
    """Parse a Strava ISO date string."""
    if not date_str:
        return datetime.now(timezone.utc)
    clean = date_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(clean)
    except ValueError:
        return datetime.now(timezone.utc)


def _compute_weekly_loads(activities: list[dict]) -> list[dict]:
    """Group activities by week and compute load."""
    weeks: dict[str, dict] = defaultdict(lambda: {
        "activities": 0,
        "distance_km": 0.0,
        "time_min": 0.0,
        "sports": defaultdict(int),
    })

    for act in activities:
        dt = _parse_date(act.get("start_date", ""))
        week_key = dt.strftime("%Y-W%W")
        w = weeks[week_key]
        w["activities"] += 1
        w["distance_km"] += (act.get("distance") or 0) / 1000
        w["time_min"] += (act.get("moving_time") or 0) / 60
        sport = act.get("sport_type") or "Other"
        w["sports"][sport] += 1

    result = []
    for week_key in sorted(weeks.keys()):
        w = weeks[week_key]
        result.append({
            "week": week_key,
            "activities": w["activities"],
            "distance_km": round(w["distance_km"], 1),
            "time_min": round(w["time_min"], 0),
            "sports": dict(w["sports"]),
        })
    return result


def _analyze_patterns(activities: list[dict], weekly_loads: list[dict]) -> list[str]:
    """Detect patterns and generate hints for Claude."""
    hints = []

    if not activities:
        return ["No activities in the analyzed period."]

    # Volume trend
    if len(weekly_loads) >= 3:
        recent_3 = weekly_loads[-3:]
        dists = [w["distance_km"] for w in recent_3]
        if dists[-1] > dists[0] * 1.2:
            hints.append("ASCENDING volume trend over the last 3 weeks (+20%+).")
        elif dists[-1] < dists[0] * 0.8:
            hints.append("DESCENDING volume trend over the last 3 weeks (-20%+).")
        else:
            hints.append("Stable volume over the last 3 weeks.")

    # Dominant sport
    sport_counts: dict[str, int] = defaultdict(int)
    for act in activities:
        sport = act.get("sport_type") or "Other"
        sport_counts[sport] += 1
    dominant = max(sport_counts, key=sport_counts.get)
    hints.append(f"Dominant sport: {dominant} ({sport_counts[dominant]} of {len(activities)} sessions).")

    # Weekly frequency
    if weekly_loads:
        avg_sessions = sum(w["activities"] for w in weekly_loads) / len(weekly_loads)
        hints.append(f"Average frequency: {avg_sessions:.1f} sessions/week.")

    # Average HR if available
    hr_values = [a["average_hr"] for a in activities if a.get("average_hr")]
    if hr_values:
        avg_hr = sum(hr_values) / len(hr_values)
        hints.append(f"Overall average HR: {avg_hr:.0f} bpm.")

    # Rest days
    active_dates = set()
    for act in activities:
        dt = _parse_date(act.get("start_date", ""))
        active_dates.add(dt.date())
    if active_dates:
        total_days = (max(active_dates) - min(active_dates)).days + 1
        rest_days = total_days - len(active_dates)
        rest_pct = (rest_days / total_days * 100) if total_days > 0 else 0
        hints.append(f"Rest days: {rest_days}/{total_days} ({rest_pct:.0f}%).")

    return hints


def _recent_activities_summary(activities: list[dict], limit: int = 10) -> list[dict]:
    """Summary of the most recent activities."""
    result = []
    for act in activities[:limit]:
        dist_km = (act.get("distance") or 0) / 1000
        moving_min = (act.get("moving_time") or 0) / 60
        entry = {
            "date": (act.get("start_date") or "")[:10],
            "type": act.get("sport_type", ""),
            "distance_km": round(dist_km, 1),
            "duration_min": round(moving_min, 0),
        }
        if act.get("average_hr"):
            entry["avg_hr"] = round(act["average_hr"])
        if dist_km > 0 and act.get("sport_type") in ("Run", "TrailRun"):
            pace_secs = (act.get("moving_time") or 0) / dist_km
            p_min, p_sec = divmod(int(pace_secs), 60)
            entry["pace_min_km"] = f"{p_min}:{p_sec:02d}"
        result.append(entry)
    return result


def main():
    parser = argparse.ArgumentParser(description="Training proposal data")
    parser.add_argument("--days", type=int, default=30, help="Days of history to analyze")
    parser.add_argument("--goal", default=None, help="Goal: marathon, speed, health, weight loss...")
    parser.add_argument("--next-days", type=int, default=7, help="Days to plan ahead")
    args = parser.parse_args()

    try:
        db_path = get_default_db_path()
        init_db(db_path)

        activities = get_activities_range(db_path, days=args.days)
        weekly_loads = _compute_weekly_loads(activities)
        hints = _analyze_patterns(activities, weekly_loads)
        recent = _recent_activities_summary(activities)

        output_json({
            "period_days": args.days,
            "total_activities": len(activities),
            "goal": args.goal,
            "days_to_plan": args.next_days,
            "weekly_loads": weekly_loads,
            "recent_activities": recent,
            "analysis": hints,
        })

    except Exception as e:
        output_error(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
