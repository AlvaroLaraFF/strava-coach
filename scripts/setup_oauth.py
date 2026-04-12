#!/usr/bin/env python3
"""Initial OAuth2 flow to authorize the Strava app.

Usage:
    export STRAVA_CLIENT_ID=your_id
    export STRAVA_CLIENT_SECRET=your_secret
    python3 scripts/setup_oauth.py [--port 8080]
"""

import argparse
import os
import sys
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strava.db import init_db, save_token
from strava.client import get_default_db_path, load_dotenv, output_json, output_error


_captured_code: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    """Minimal HTTP server that captures the authorization code from Strava's redirect."""

    def do_GET(self):
        global _captured_code
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)

        if "code" in params:
            _captured_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h2>Authorization successful. You can close this window.</h2>"
            )
        else:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                f"<h2>Error: {error}</h2>".encode()
            )

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Strava OAuth2 setup")
    parser.add_argument("--port", type=int, default=8080, help="Callback port")
    parser.add_argument(
        "--scope",
        default="read,activity:read_all,profile:read_all",
        help="Strava scopes",
    )
    args = parser.parse_args()

    load_dotenv()
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        output_error(
            "Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET as environment variables."
        )

    redirect_uri = f"http://localhost:{args.port}"
    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&response_type=code"
        f"&scope={args.scope}"
    )

    print(f"\n1. Open this URL in your browser:\n\n   {auth_url}\n", flush=True)
    print(f"2. Authorize the app on Strava.", flush=True)
    print(f"3. Waiting for callback on {redirect_uri} ...\n", flush=True)

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    server = HTTPServer(("", args.port), _CallbackHandler)
    server.handle_request()

    if not _captured_code:
        output_error("No authorization code received.")

    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": _captured_code,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )

    if resp.status_code != 200:
        output_error(f"Token exchange failed ({resp.status_code}): {resp.text}")

    data = resp.json()
    athlete = data.get("athlete", {})

    token_data = {
        "athlete_id": athlete.get("id"),
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": data["expires_at"],
        "scope": args.scope,
    }

    db_path = get_default_db_path()
    init_db(db_path)
    save_token(db_path, token_data)

    output_json({
        "athlete_id": athlete.get("id"),
        "name": f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip(),
        "message": "Tokens stored successfully in the database.",
    })


if __name__ == "__main__":
    main()
