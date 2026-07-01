#!/usr/bin/env python3
"""Read-only local JSON API for strava-coach + optional static SPA serving.

Only GET/OPTIONS are routed — there are no write handlers, so the API is
structurally incapable of mutating the DB. Run:

    python3 webapp/backend/server.py --port 8000
    python3 webapp/backend/server.py --serve-static webapp/frontend/dist --port 8000
"""
import argparse
import json
import mimetypes
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from webapp.backend import service  # noqa: E402


def _q(query: dict, key: str, default=None, cast=None):
    vals = query.get(key)
    if not vals:
        return default
    v = vals[0]
    if cast is None:
        return v
    try:
        return cast(v)
    except (ValueError, TypeError):
        return default


# (compiled path regex, handler(match, query) -> data). Order matters: the
# more specific /streams route must precede the bare activity route.
ROUTES = [
    (re.compile(r"^/api/health/?$"), lambda m, q: service.health()),
    (re.compile(r"^/api/profile/?$"), lambda m, q: service.profile()),
    (re.compile(r"^/api/dashboard/?$"), lambda m, q: service.dashboard()),
    (re.compile(r"^/api/activities/(-?\d+)/streams/?$"),
     lambda m, q: service.streams(int(m.group(1)), target=_q(q, "downsample", 1200, int))),
    (re.compile(r"^/api/activities/(-?\d+)/?$"),
     lambda m, q: service.activity_detail(int(m.group(1)))),
    (re.compile(r"^/api/activities/?$"),
     lambda m, q: service.activities(days=_q(q, "days", 120, int),
                                     sport=_q(q, "sport"),
                                     limit=_q(q, "limit", 200, int))),
    (re.compile(r"^/api/session-analysis/?$"),
     lambda m, q: service.session_analysis(date=_q(q, "date"),
                                           strava_id=_q(q, "strava_id", None, int))),
    (re.compile(r"^/api/calendar/?$"),
     lambda m, q: service.calendar(start=_q(q, "start"), end=_q(q, "end"))),
    (re.compile(r"^/api/compare/?$"),
     lambda m, q: service.compare(a=_q(q, "a", None, int), b=_q(q, "b", None, int))),
    (re.compile(r"^/api/evolution/?$"),
     lambda m, q: service.evolution(days=_q(q, "days", 365, int))),
    (re.compile(r"^/api/prs/?$"), lambda m, q: service.prs()),
    (re.compile(r"^/api/hr-zones/?$"), lambda m, q: service.hr_zones()),
    (re.compile(r"^/api/weekly-log/?$"),
     lambda m, q: service.weekly_log(weeks=_q(q, "weeks", 12, int))),
]

STATIC_DIR: str | None = None


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "stravacoach-webapi/1.0"

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path
        query = parse_qs(parts.query)

        if path.startswith("/api/"):
            return self._handle_api(path, query)
        return self._handle_static(path)

    def _handle_api(self, path: str, query: dict):
        for pattern, handler in ROUTES:
            m = pattern.match(path)
            if not m:
                continue
            try:
                data = handler(m, query)
                return self._send_json({"success": True, "data": data})
            except KeyError as e:
                return self._send_json({"success": False, "error": str(e)}, 404)
            except (ValueError, TypeError) as e:
                return self._send_json({"success": False, "error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                return self._send_json(
                    {"success": False, "error": f"{type(e).__name__}: {e}"}, 500)
        return self._send_json({"success": False, "error": "not found"}, 404)

    def _handle_static(self, path: str):
        if not STATIC_DIR:
            return self._send_json({"success": False, "error": "static serving disabled"}, 404)
        rel = unquote(path).lstrip("/") or "index.html"
        candidate = os.path.normpath(os.path.join(STATIC_DIR, rel))
        # Prevent path traversal outside the static dir.
        if not candidate.startswith(os.path.abspath(STATIC_DIR)):
            return self._send_json({"success": False, "error": "forbidden"}, 403)
        if not os.path.isfile(candidate):
            candidate = os.path.join(STATIC_DIR, "index.html")  # SPA fallback
            if not os.path.isfile(candidate):
                return self._send_json({"success": False, "error": "not built"}, 404)
        ctype = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
        with open(candidate, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # No do_POST/PUT/DELETE: the API is read-only by construction.


def run(host: str = "127.0.0.1", port: int = 8711, static_dir: str | None = None):
    """Start the blocking server. Used by main() and by webapp/run.py."""
    global STATIC_DIR
    if static_dir:
        STATIC_DIR = os.path.abspath(static_dir)
    httpd = ThreadingHTTPServer((host, port), ApiHandler)
    where = f"http://{host}:{port}"
    print(f"strava-coach API on {where}"
          + (f" (serving {STATIC_DIR})" if STATIC_DIR else " (API only)"), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


def main():
    parser = argparse.ArgumentParser(description="strava-coach read-only web API")
    parser.add_argument("--port", type=int, default=8711)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--serve-static", default=None,
                        help="Directory with the built SPA to serve on non-/api paths")
    args = parser.parse_args()
    run(host=args.host, port=args.port, static_dir=args.serve_static)


if __name__ == "__main__":
    main()
