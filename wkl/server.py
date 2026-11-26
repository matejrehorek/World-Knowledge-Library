"""A small JSON API and the reading room (web UI), on the standard library alone."""

from __future__ import annotations

import json
import mimetypes
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import __version__, serapeum
from .catalogue import meta
from .founding import found
from .harbor import fetch_metadata
from .library import Library, LibraryError, NotFound

STATIC = Path(__file__).parent / "static"
MAX_BODY = 25 * 1024 * 1024
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}

Route = tuple[str, re.Pattern, Callable[..., Any]]


class Api:
    """Maps HTTP routes onto Library methods."""

    def __init__(self, lib: Library):
        self.lib = lib
        self.routes: list[Route] = []
        r = self.route
        r("GET", r"/api/meta", lambda q, b: meta() | {"version": __version__, "path": lib.path})
        r("GET", r"/api/stats", lambda q, b: lib.stats())
        r("GET", r"/api/scrolls", self.search)
        r("POST", r"/api/scrolls", self.create)
        r("GET", r"/api/scrolls/(\d+)", lambda q, b, i: lib.get_scroll(i))
        r("PATCH", r"/api/scrolls/(\d+)", self.update)
        r("DELETE", r"/api/scrolls/(\d+)", lambda q, b, i: lib.delete_scroll(i) or {"ok": True})
        r("GET", r"/api/scrolls/(\d+)/revisions", lambda q, b, i: lib.revisions(i))
        r("POST", r"/api/revisions/(\d+)/restore", lambda q, b, i: lib.restore_revision(i))
        r("POST", r"/api/scrolls/(\d+)/marginalia", lambda q, b, i: lib.add_marginalia(
            i, b.get("body", ""), quote=b.get("quote", ""), kind=b.get("kind", "note")))
        r("DELETE", r"/api/marginalia/(\d+)", lambda q, b, i: lib.delete_marginalia(i) or {"ok": True})
        r("POST", r"/api/scrolls/(\d+)/remember", lambda q, b, i: lib.remember(i, True))
        r("DELETE", r"/api/scrolls/(\d+)/remember", lambda q, b, i: lib.remember(i, False))
        r("GET", r"/api/pharos", lambda q, b: lib.due(limit=int(q.get("limit", 50))))
        r("POST", r"/api/pharos/(\d+)", lambda q, b, i: lib.review(i, int(b.get("grade", -1))))
        r("GET", r"/api/titles", lambda q, b: lib.titles(q.get("q", ""), int(q.get("limit", 12))))
        r("GET", r"/api/random", lambda q, b: lib.random_scroll(q.get("status") or None))
        r("GET", r"/api/graph", lambda q, b: lib.graph())
        r("GET", r"/api/tags", lambda q, b: lib.list_tags())
        r("POST", r"/api/tags/rename", lambda q, b: lib.rename_tag(b.get("from", ""), b.get("to", ""))
          or {"ok": True})
        r("GET", r"/api/wings", lambda q, b: lib.list_wings())
        r("POST", r"/api/wings", lambda q, b: lib.create_wing(
            b.get("name", ""), b.get("description", ""), b.get("emblem", "")))
        r("PATCH", r"/api/wings/(\d+)", lambda q, b, i: lib.update_wing(i, **b))
        r("DELETE", r"/api/wings/(\d+)", lambda q, b, i: lib.delete_wing(i) or {"ok": True})
        r("POST", r"/api/harbor/fetch", lambda q, b: fetch_metadata(b.get("url", "")))
        r("GET", r"/api/serapeum/export", lambda q, b: serapeum.export_json(lib))
        r("POST", r"/api/serapeum/import", lambda q, b: serapeum.import_json(lib, b))
        r("POST", r"/api/founding", lambda q, b: {"added": found(lib)})

    def route(self, method: str, pattern: str, handler: Callable[..., Any]) -> None:
        self.routes.append((method, re.compile(f"^{pattern}$"), handler))

    def dispatch(self, method: str, path: str, query: dict, body: dict) -> tuple[int, Any]:
        allowed = False
        for m, pattern, handler in self.routes:
            match = pattern.match(path)
            if not match:
                continue
            allowed = True
            if m != method:
                continue
            args = [int(g) for g in match.groups()]
            try:
                return 200, handler(query, body, *args)
            except NotFound as exc:
                return 404, {"error": str(exc)}
            except (LibraryError, ValueError, TypeError, KeyError) as exc:
                return 400, {"error": str(exc) or exc.__class__.__name__}
        return (405, {"error": "Method not allowed"}) if allowed else (404, {"error": "Not found"})

    # handlers that need a little unpacking
    def search(self, q: dict, b: dict) -> dict:
        return self.lib.search(q.get("q", ""), kind=q.get("kind") or None,
                               status=q.get("status") or None, wing=q.get("wing") or None,
                               tag=q.get("tag") or None, sort=q.get("sort", ""),
                               limit=int(q.get("limit", 50)), offset=int(q.get("offset", 0)))

    @staticmethod
    def _split(b: dict) -> tuple[dict, dict]:
        extra = {k: b[k] for k in ("tags", "wing") if k in b}
        fields = {k: v for k, v in b.items() if k not in ("tags", "wing", "remember")}
        return fields, extra

    def create(self, q: dict, b: dict) -> dict:
        fields, extra = self._split(b)
        title = fields.pop("title", "")
        fields.pop("created_at", None)
        return self.lib.add_scroll(title, remember=bool(b.get("remember")), **fields, **extra)

    def update(self, q: dict, b: dict, i: int) -> dict:
        fields, extra = self._split(b)
        for key in ("id", "created_at", "updated_at", "finished_at"):
            fields.pop(key, None)
        return self.lib.update_scroll(i, **fields, **extra)


def make_handler(api: Api, *, loopback: bool, quiet: bool) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"WorldKnowledgeLibrary/{__version__}"

        def log_message(self, fmt: str, *args: Any) -> None:
            if not quiet:
                sys.stderr.write("  %s %s\n" % (self.log_date_time_string(), fmt % args))

        # -------------------------------------------------- safety checks
        def _host_ok(self) -> bool:
            # Defends against DNS rebinding when serving on the loopback interface.
            if not loopback:
                return True
            host = (self.headers.get("Host") or "").strip().lower()
            host = re.sub(r":\d+$", "", host)
            return host in LOOPBACK_HOSTS

        def _origin_ok(self) -> bool:
            # Other websites must not be able to write to your library.
            origin = self.headers.get("Origin")
            if not origin:
                return True
            return urlparse(origin).netloc.lower() == (self.headers.get("Host") or "").lower()

        # ------------------------------------------------------ responses
        def _send(self, status: int, payload: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def _json(self, status: int, data: Any, extra: dict | None = None) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8",
                       {"Cache-Control": "no-store"} | (extra or {}))

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (STATIC / rel).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():
                target = STATIC / "index.html"
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
                ctype += "; charset=utf-8"
            csp = ("default-src 'self'; img-src 'self' data: https:; style-src 'self' "
                   "'unsafe-inline' https://fonts.googleapis.com; font-src 'self' "
                   "https://fonts.gstatic.com; script-src 'self'; frame-ancestors 'none'")
            self._send(200, target.read_bytes(), ctype,
                       {"Content-Security-Policy": csp, "Cache-Control": "no-cache"})

        # ------------------------------------------------------- dispatch
        def _handle(self) -> None:
            if not self._host_ok():
                return self._json(403, {"error": "Unexpected Host header"})
            url = urlparse(self.path)
            if not url.path.startswith("/api/"):
                if self.command not in ("GET", "HEAD"):
                    return self._json(405, {"error": "Method not allowed"})
                return self._static(url.path)
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            body: Any = {}
            if self.command in ("POST", "PATCH", "PUT", "DELETE"):
                if not self._origin_ok():
                    return self._json(403, {"error": "Cross-origin writes are not allowed"})
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._json(413, {"error": "Request too large"})
                if length:
                    if "application/json" not in (self.headers.get("Content-Type") or ""):
                        return self._json(415, {"error": "Send JSON"})
                    try:
                        body = json.loads(self.rfile.read(length).decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        return self._json(400, {"error": "Malformed JSON"})
                    if not isinstance(body, dict):
                        return self._json(400, {"error": "Expected a JSON object"})
            status, data = api.dispatch(self.command if self.command != "HEAD" else "GET",
                                        url.path, query, body)
            extra = {}
            if url.path == "/api/serapeum/export" and status == 200:
                stamp = data["exported_at"][:10]
                extra["Content-Disposition"] = (
                    f'attachment; filename="world-knowledge-library-{stamp}.json"')
            self._json(status, data, extra)

        do_GET = do_HEAD = do_POST = do_PATCH = do_PUT = do_DELETE = _handle

    return Handler


def serve(lib: Library, host: str = "127.0.0.1", port: int = 8331, *, quiet: bool = False,
          open_browser: bool = False) -> None:
    loopback = host in ("127.0.0.1", "localhost", "::1")
    handler = make_handler(Api(lib), loopback=loopback, quiet=quiet)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{'localhost' if loopback else host}:{httpd.server_port}/"
    print(f"\n  𓂀  The World Knowledge Library is open at {url}")
    print(f"     Catalogue: {lib.path}")
    print("     Press Ctrl+C to close the doors.\n")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  The doors are closed. Knowledge keeps.\n")
    finally:
        httpd.server_close()

