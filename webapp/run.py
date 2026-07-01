#!/usr/bin/env python3
"""One command to build the React SPA and serve it + the read-only API from a
single local Python process, then open the browser.

    python3 webapp/run.py                # build if needed, serve, open browser
    python3 webapp/run.py --no-open      # don't open a browser
    python3 webapp/run.py --no-build     # serve the existing dist as-is
    python3 webapp/run.py --dev          # print dev-mode instructions and exit

Uses the system python3 (sys.executable) and npm; never touches the stale venv.
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FRONTEND = os.path.join(HERE, "frontend")
DIST = os.path.join(FRONTEND, "dist")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def build_frontend() -> None:
    npm = shutil.which("npm")
    if not npm:
        sys.exit("npm not found on PATH. Install Node.js 18+ to build the frontend.")
    if not os.path.isdir(os.path.join(FRONTEND, "node_modules")):
        print("Installing frontend dependencies (npm install)…", flush=True)
        subprocess.run([npm, "install"], cwd=FRONTEND, check=True)
    print("Building the frontend (npm run build)…", flush=True)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build + serve the strava-coach web app.")
    parser.add_argument("--port", type=int, default=8711)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-build", action="store_true", help="Serve the existing dist without rebuilding.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser.")
    parser.add_argument("--dev", action="store_true", help="Print dev-mode instructions and exit.")
    args = parser.parse_args()

    if args.dev:
        print("Dev mode (hot reload):\n"
              f"  1) python3 webapp/backend/server.py --port 8711\n"
              f"  2) cd webapp/frontend && npm run dev   # http://localhost:5173 (proxies /api)")
        return

    if not args.no_build:
        build_frontend()
    if not os.path.isdir(DIST):
        sys.exit(f"No build found at {DIST}. Run without --no-build first.")

    from webapp.backend import server

    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Opening {url}", flush=True)
    server.run(host=args.host, port=args.port, static_dir=DIST)


if __name__ == "__main__":
    main()
