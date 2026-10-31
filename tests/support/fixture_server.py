"""Local HTTP server for scraper tests (FR-30): serves `tests/fixtures/html/` over loopback.

A stdlib `ThreadingHTTPServer` on a thread. It answers `/robots.txt` (allow-all unless told
otherwise), can delay a response or answer a chosen status per route, and records every request.

Tests point the sources at it with `with_base_url(SOURCES, server.url)`.
"""

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import Self
from urllib.parse import parse_qs, quote, urlsplit

from take_jobs.infrastructure.scraping.spiders.infojobs import FRAGMENT_PATH

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "html"

ROBOTS_TXT = b"User-agent: *\nAllow: /\n"


@dataclass(frozen=True, slots=True)
class Route:
    """How the server answers one request target (`path?query`, or just `path`)."""

    body: bytes = b""
    status: int = 200
    delay_s: float = 0.0
    # The real vagas.com follow-up pages answer 403 without this header.
    require_xhr: bool = False
    content_type: str = "text/html; charset=utf-8"
    # With a 30x `status`: where to send the client.
    location: str | None = None

    @classmethod
    def fixture(cls, name: str, **kwargs: object) -> Self:
        return cls(body=(FIXTURES / name).read_bytes(), **kwargs)  # type: ignore[arg-type]


def fragment_target(listing_target: str) -> str:
    """Route key of an Infojobs list-fragment request for the listing `path?query` given.

    The spider sends the full listing URL (with the server's own origin) inside `url=`, so the
    server reduces that URL to `path?query` before matching; this builds the same key.
    """
    return f"{FRAGMENT_PATH}?url={quote(listing_target, safe='')}"


def _route_target(target: str) -> str:
    """The key a request target is matched against (fragment requests lose their origin)."""
    parts = urlsplit(target)
    if parts.path != FRAGMENT_PATH:
        return target
    inner = urlsplit(parse_qs(parts.query).get("url", [""])[0])
    return fragment_target(f"{inner.path}?{inner.query}" if inner.query else inner.path)


@dataclass(frozen=True, slots=True)
class Hit:
    target: str
    headers: Mapping[str, str]


@dataclass
class FixtureServer:
    routes: Mapping[str, Route] = field(default_factory=dict)
    robots_txt: bytes = ROBOTS_TXT
    hits: list[Hit] = field(default_factory=list)
    first_listing_hit: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        server = self
        self._lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                server._handle(self)

            def log_message(self, format: str, *args: object) -> None:
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def hit_count(self) -> int:
        with self._lock:
            return len(self.hits)

    def listing_hits(self) -> list[Hit]:
        with self._lock:
            return [hit for hit in self.hits if hit.target != "/robots.txt"]

    def start(self) -> Self:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        target = handler.path
        with self._lock:
            self.hits.append(Hit(target, dict(handler.headers.items())))
        if target == "/robots.txt":
            self._send(handler, 200, self.robots_txt, "text/plain")
            return
        self.first_listing_hit.set()
        key = _route_target(target)
        route = self.routes.get(key) or self.routes.get(key.split("?", 1)[0])
        if route is None:
            self._send(handler, 404, b"not found", "text/plain")
            return
        if route.delay_s:
            time.sleep(route.delay_s)
        if route.require_xhr and handler.headers.get("X-Requested-With") != "XMLHttpRequest":
            self._send(handler, 403, b"forbidden", "text/plain")
            return
        self._send(handler, route.status, route.body, route.content_type, route.location)

    @staticmethod
    def _send(
        handler: BaseHTTPRequestHandler,
        status: int,
        body: bytes,
        content_type: str,
        location: str | None = None,
    ) -> None:
        try:
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            if location is not None:
                handler.send_header("Location", location)
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client gave up (e.g. the crawl child was killed)


def python_routes(*, delay_s: float = 0.0) -> dict[str, Route]:
    """The `python` term on both sites, as captured live on 2026-10-30.

    vagas.com: page 1, then the XHR follow-up (the last page). Infojobs: page 1 as HTML, pages 2
    and 3 as list-fragment JSON with unseen ids, then the end-of-list answer (page 4), so the walk
    ends on "no unseen ids" (rule 17) after four pages. Page 2 is not a repeat of page 1: the
    plain `?page=2` HTML URL is not served at all.
    """

    def fragment(name: str) -> Route:
        return Route.fixture(name, delay_s=delay_s, content_type="application/json")

    return {
        "/vagas-de-python": Route.fixture("vagas_python_p1.html", delay_s=delay_s),
        "/vagas-de-python?pagina=2&q=python": Route.fixture(
            "vagas_python_p2_xhr.html", delay_s=delay_s, require_xhr=True
        ),
        "/vagas-de-emprego-python.aspx?page=1": Route.fixture(
            "infojobs_python_p1.html", delay_s=delay_s
        ),
        fragment_target("/vagas-de-emprego-python.aspx?page=2"): fragment(
            "infojobs_python_p2_fragment.json"
        ),
        fragment_target("/vagas-de-emprego-python.aspx?page=3"): fragment(
            "infojobs_python_p3_fragment.json"
        ),
        fragment_target("/vagas-de-emprego-python.aspx?page=4"): fragment(
            "infojobs_fragment_eof.json"
        ),
    }


def journey_routes() -> dict[str, Route]:
    """The synthetic journey pages for the E2E tests (terms `desenvolvedor` and `programador`).

    vagas.com lists the same "Desenvolvedor Backend Java" job (same id) for both terms, and
    "Programador de CNC" for `programador` only. Infojobs answers both terms with an empty
    listing, so every combination succeeds and only vagas.com contributes jobs.
    """
    empty = Route.fixture("empty_listing.html")
    return {
        "/vagas-de-desenvolvedor": Route.fixture("journey_vagas_desenvolvedor.html"),
        "/vagas-de-programador": Route.fixture("journey_vagas_programador.html"),
        "/vagas-de-emprego-desenvolvedor.aspx?page=1": empty,
        "/vagas-de-emprego-programador.aspx?page=1": empty,
    }
