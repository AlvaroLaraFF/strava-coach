#!/usr/bin/env python3
"""Critical Swim Speed estimator."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.analytics import css_estimate
from strava.client import output_error, output_json


def parse_time(s: str) -> float:
    if ":" in s:
        m, sec = s.split(":")
        return int(m) * 60 + float(sec)
    return float(s)


def fmt_pace_per_100(speed_m_s: float) -> str:
    if not speed_m_s:
        return "-"
    seconds_per_100 = 100 / speed_m_s
    m = int(seconds_per_100 // 60)
    s = int(seconds_per_100 - m * 60)
    return f"{m}:{s:02d}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--t400", required=True, help="400m time as M:SS or seconds")
    p.add_argument("--t200", required=True, help="200m time as M:SS or seconds")
    args = p.parse_args()

    try:
        t400 = parse_time(args.t400)
        t200 = parse_time(args.t200)
        if t400 <= t200:
            output_error("400m time must be greater than 200m time.")
        css = css_estimate(t400, t200)
        if not css:
            output_error("Could not compute CSS.")

        css_pace_100 = 100 / css
        endurance = css_pace_100 + 5
        vo2 = css_pace_100 - 3
        def fmt(x):
            m = int(x // 60)
            s = int(x - m * 60)
            return f"{m}:{s:02d}"

        output_json({
            "css_m_per_s": round(css, 3),
            "css_pace_per_100m": fmt(css_pace_100),
            "training_paces_per_100m": {
                "endurance": fmt(endurance),
                "threshold": fmt(css_pace_100),
                "vo2max": fmt(vo2),
            },
            "input": {"t400_s": t400, "t200_s": t200},
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
