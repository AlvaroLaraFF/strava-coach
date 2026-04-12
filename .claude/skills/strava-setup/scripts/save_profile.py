#!/usr/bin/env python3
"""Save or update the user profile in the local database."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from strava.client import get_default_db_path, output_error, output_json
from strava.db import init_db, load_token, load_user_profile, save_user_profile


def main() -> None:
    p = argparse.ArgumentParser(description="Save user profile to the local DB")
    p.add_argument("--name", type=str, help="user display name")
    p.add_argument("--height", type=float, help="height in cm")
    p.add_argument("--weight", type=float, help="weight in kg")
    p.add_argument("--gender", type=str, choices=["M", "F"], help="M or F")
    p.add_argument("--birth-date", type=str, help="birth date YYYY-MM-DD")
    args = p.parse_args()

    if not any([args.name, args.height, args.weight, args.gender, args.birth_date]):
        output_error("No profile fields provided. Use --name, --height, --weight, --gender.")

    try:
        db = get_default_db_path()
        init_db(db)

        token = load_token(db)
        if not token:
            output_error("No token found. Run strava-setup first.")
        athlete_id = token["athlete_id"]

        profile = {}
        if args.name:
            profile["name"] = args.name
        if args.height:
            profile["height_cm"] = args.height
        if args.weight:
            profile["weight_kg"] = args.weight
        if args.gender:
            profile["gender"] = args.gender
        if args.birth_date:
            profile["birth_date"] = args.birth_date

        save_user_profile(db, athlete_id, profile)
        saved = load_user_profile(db, athlete_id)

        output_json({
            "message": "Profile saved",
            "profile": {
                "athlete_id": saved["athlete_id"],
                "name": saved.get("name"),
                "height_cm": saved.get("height_cm"),
                "weight_kg": saved.get("weight_kg"),
                "gender": saved.get("gender"),
                "birth_date": saved.get("birth_date"),
            },
        })
    except Exception as e:
        output_error(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
