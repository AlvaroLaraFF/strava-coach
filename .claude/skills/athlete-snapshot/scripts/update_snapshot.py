#!/usr/bin/env python3
"""Write a partial or full athlete snapshot and generate change alerts."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.client import get_default_db_path, output_error, output_json
from strava.db import get_latest_snapshot, init_db, load_token, upsert_athlete_snapshot

# --- Alert thresholds -------------------------------------------------------

_ALERT_RULES = {
    "ftp_w": {
        "abs_delta": 5,
        "msg_up": "FTP subio {delta:.0f}W ({old:.0f} -> {new:.0f})",
        "msg_down": "FTP bajo {delta:.0f}W ({old:.0f} -> {new:.0f})",
    },
    "vdot": {
        "abs_delta": 1.0,
        "msg_up": "VDOT subio {delta:.1f} ({old:.1f} -> {new:.1f})",
        "msg_down": "VDOT bajo {delta:.1f} ({old:.1f} -> {new:.1f})",
    },
    "threshold_pace_min_km": {
        "abs_delta": 0.10,
        # Lower pace = faster = improvement
        "msg_up": "Ritmo umbral empeoro {delta:.2f} min/km ({old:.2f} -> {new:.2f})",
        "msg_down": "Ritmo umbral mejoro {delta:.2f} min/km ({old:.2f} -> {new:.2f})",
    },
    "ctl": {
        "abs_delta": 5,
        "msg_up": "Fitness (CTL) subio {delta:.1f} puntos ({old:.1f} -> {new:.1f})",
        "msg_down": "Fitness (CTL) bajo {delta:.1f} puntos ({old:.1f} -> {new:.1f})",
    },
    "tsb": {
        "boundary": [(-10, "fatigada"), (10, "fresca")],
    },
    "acwr": {
        "boundary": [(1.3, "elevada"), (1.5, "peligrosa")],
    },
    "monotony": {
        "boundary": [(2.0, "alta"), (2.5, "muy alta")],
    },
    "avg_decoupling_pct": {
        "boundary": [(5, "moderado"), (8, "pobre")],
    },
    "avg_cadence_spm": {
        "abs_delta": 3,
        "msg_up": "Cadencia subio {delta:.0f} spm ({old:.0f} -> {new:.0f})",
        "msg_down": "Cadencia bajo {delta:.0f} spm ({old:.0f} -> {new:.0f})",
    },
    "lthr_bpm": {
        "abs_delta": 3,
        "msg_up": "LTHR subio {delta:.0f} bpm ({old:.0f} -> {new:.0f})",
        "msg_down": "LTHR bajo {delta:.0f} bpm ({old:.0f} -> {new:.0f})",
    },
    "hr_max_bpm": {
        "abs_delta": 3,
        "msg_up": "HR max subio {delta:.0f} bpm ({old:.0f} -> {new:.0f})",
        "msg_down": "HR max bajo {delta:.0f} bpm ({old:.0f} -> {new:.0f})",
    },
}


def _check_boundary_alert(metric: str, old_val, new_val, boundaries):
    """Check if the new value crossed a boundary that the old value didn't."""
    if old_val is None or new_val is None:
        return None
    for threshold, label in boundaries:
        old_above = old_val >= threshold
        new_above = new_val >= threshold
        if new_above and not old_above:
            return {
                "metric": metric,
                "old": round(old_val, 2),
                "new": round(new_val, 2),
                "direction": "up",
                "message": f"{metric} cruzo umbral {threshold} -> zona {label} ({old_val:.2f} -> {new_val:.2f})",
            }
        if old_above and not new_above:
            return {
                "metric": metric,
                "old": round(old_val, 2),
                "new": round(new_val, 2),
                "direction": "down",
                "message": f"{metric} bajo de umbral {threshold} ({old_val:.2f} -> {new_val:.2f})",
            }
    return None


def generate_alerts(previous: dict | None, current_metrics: dict) -> list[dict]:
    """Compare current metrics against previous snapshot and return alerts."""
    alerts = []
    if not previous:
        return alerts

    for metric, rule in _ALERT_RULES.items():
        new_val = current_metrics.get(metric)
        old_val = previous.get(metric)
        if new_val is None or old_val is None:
            continue

        if "boundary" in rule:
            alert = _check_boundary_alert(metric, old_val, new_val, rule["boundary"])
            if alert:
                alerts.append(alert)
            continue

        delta = new_val - old_val
        abs_threshold = rule.get("abs_delta", 0)
        if abs(delta) >= abs_threshold:
            direction = "up" if delta > 0 else "down"
            msg_tpl = rule.get(f"msg_{direction}", "")
            alerts.append({
                "metric": metric,
                "old": round(old_val, 2),
                "new": round(new_val, 2),
                "direction": direction,
                "message": msg_tpl.format(old=old_val, new=new_val, delta=abs(delta)),
            })

    return alerts


# --- CLI ---------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Update athlete snapshot with partial metrics")
    p.add_argument("--source", type=str, default="manual", help="Skill that produced these metrics")
    p.add_argument("--ftp-w", type=float)
    p.add_argument("--hr-max-bpm", type=float)
    p.add_argument("--hr-rest-bpm", type=float)
    p.add_argument("--vdot", type=float)
    p.add_argument("--threshold-pace-min-km", type=float)
    p.add_argument("--css-m-s", type=float)
    p.add_argument("--weight-kg", type=float)
    p.add_argument("--ctl", type=float)
    p.add_argument("--atl", type=float)
    p.add_argument("--tsb", type=float)
    p.add_argument("--acwr", type=float)
    p.add_argument("--monotony", type=float)
    p.add_argument("--strain", type=float)
    p.add_argument("--lthr-bpm", type=float)
    p.add_argument("--avg-decoupling-pct", type=float)
    p.add_argument("--avg-cadence-spm", type=float)
    args = p.parse_args()

    # Build metrics dict from provided args only
    arg_map = {
        "ftp_w": args.ftp_w,
        "hr_max_bpm": args.hr_max_bpm,
        "hr_rest_bpm": args.hr_rest_bpm,
        "vdot": args.vdot,
        "threshold_pace_min_km": args.threshold_pace_min_km,
        "css_m_s": args.css_m_s,
        "weight_kg": args.weight_kg,
        "lthr_bpm": args.lthr_bpm,
        "ctl": args.ctl,
        "atl": args.atl,
        "tsb": args.tsb,
        "acwr": args.acwr,
        "monotony": args.monotony,
        "strain": args.strain,
        "avg_decoupling_pct": args.avg_decoupling_pct,
        "avg_cadence_spm": args.avg_cadence_spm,
    }
    metrics = {k: v for k, v in arg_map.items() if v is not None}

    if not metrics:
        output_error("No metrics provided. Pass at least one --<metric> flag.")

    try:
        db = get_default_db_path()
        init_db(db)

        token = load_token(db)
        if not token:
            output_error("No token found. Run strava-setup first.")
        athlete_id = token["athlete_id"]

        previous = get_latest_snapshot(db, athlete_id)
        alerts = generate_alerts(previous, metrics)

        row_id = upsert_athlete_snapshot(db, athlete_id, args.source, metrics)

        snapshot = get_latest_snapshot(db, athlete_id)

        output_json({
            "snapshot": {k: snapshot[k] for k in snapshot if k not in ("id", "athlete_id")},
            "alerts": alerts,
            "previous_captured_at": previous.get("captured_at") if previous else None,
            "row_id": row_id,
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
