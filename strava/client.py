"""Strava API client with automatic OAuth2 token management."""

import json
import os
import sys
import time

import requests

from strava.db import load_token, save_token


def load_dotenv() -> None:
    """Load variables from .env file in the project root (if it exists).

    Only sets variables that are not already present in the environment,
    so explicit exports always take precedence.
    """
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )
    if not os.path.isfile(env_path):
        return
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if sep:
                os.environ.setdefault(key.strip(), value.strip())


class StravaConfigError(Exception):
    pass


class StravaAuthError(Exception):
    pass


class StravaAPIError(Exception):
    pass


# ---------------------------------------------------------------------------
# Output helpers (shared pattern across all scripts)
# ---------------------------------------------------------------------------

def output_json(data) -> None:
    """Print a success JSON response to stdout."""
    print(json.dumps({"success": True, "data": data}, ensure_ascii=False))


def output_error(message: str) -> None:
    """Print an error JSON response to stdout and exit with code 1."""
    print(json.dumps({"success": False, "error": message}, ensure_ascii=False))
    sys.exit(1)


def get_default_db_path() -> str:
    """Return the default database path next to the strava/ package."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "strava_coach.db",
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class StravaClient:
    BASE_URL = "https://www.strava.com/api/v3"
    TOKEN_URL = "https://www.strava.com/oauth/token"

    def __init__(self, db_path: str):
        load_dotenv()
        self.client_id = os.environ.get("STRAVA_CLIENT_ID")
        self.client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise StravaConfigError(
                "Missing STRAVA_CLIENT_ID and/or STRAVA_CLIENT_SECRET environment variables."
            )
        self._db = db_path
        self._token_cache: dict | None = None

    # --- Token management ---

    def _load_token(self) -> dict:
        if self._token_cache:
            return self._token_cache
        token = load_token(self._db)
        if not token:
            raise StravaAuthError(
                "No token found. Run: python3 scripts/setup_oauth.py"
            )
        self._token_cache = token
        return token

    def _ensure_valid_token(self) -> str:
        token = self._load_token()
        if token["expires_at"] < time.time() + 60:
            token = self._refresh_token(token["refresh_token"], token["athlete_id"])
        return token["access_token"]

    def _refresh_token(self, refresh_token: str, athlete_id: int) -> dict:
        resp = requests.post(
            self.TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            raise StravaAuthError(
                f"Token refresh failed ({resp.status_code}): {resp.text}"
            )
        data = resp.json()
        token_data = {
            "athlete_id": athlete_id,
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at": data["expires_at"],
        }
        save_token(self._db, token_data)
        self._token_cache = token_data
        return token_data

    # --- HTTP ---

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        access_token = self._ensure_valid_token()
        for attempt in range(3):
            resp = requests.get(
                f"{self.BASE_URL}{path}",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params or {},
                timeout=15,
            )
            if resp.status_code == 401:
                raise StravaAuthError("Invalid or expired token after refresh.")
            if resp.status_code == 429:
                if attempt == 2:
                    raise StravaAPIError("Rate limit exceeded after 3 attempts.")
                time.sleep(60)
                continue
            if resp.status_code != 200:
                raise StravaAPIError(
                    f"Strava API error {resp.status_code}: {resp.text[:300]}"
                )
            return resp.json()
        raise StravaAPIError("unreachable")

    # --- Public methods ---

    def get_athlete(self) -> dict:
        return self._get("/athlete")

    def get_activities(
        self,
        per_page: int = 30,
        page: int = 1,
        before: int | None = None,
        after: int | None = None,
    ) -> list:
        params = {"per_page": per_page, "page": page}
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        return self._get("/athlete/activities", params)

    def get_activity(self, activity_id: int) -> dict:
        return self._get(f"/activities/{activity_id}")

    def get_athlete_stats(self, athlete_id: int) -> dict:
        return self._get(f"/athletes/{athlete_id}/stats")

    def get_streams(
        self,
        activity_id: int,
        keys: list[str] | None = None,
    ) -> dict:
        if keys is None:
            keys = [
                "time", "distance", "latlng", "altitude",
                "velocity_smooth", "heartrate", "cadence",
                "watts", "temp", "moving", "grade_smooth",
            ]
        return self._get(
            f"/activities/{activity_id}/streams",
            {"keys": ",".join(keys), "key_by_type": "true"},
        )

    def get_laps(self, activity_id: int) -> list:
        return self._get(f"/activities/{activity_id}/laps")

    def get_activity_zones(self, activity_id: int) -> list:
        return self._get(f"/activities/{activity_id}/zones")

    def get_athlete_zones(self) -> dict:
        return self._get("/athlete/zones")

    def get_gear(self, gear_id: str) -> dict:
        return self._get(f"/gear/{gear_id}")
