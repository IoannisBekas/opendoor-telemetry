"""Shared HTTP layer: token-bucket rate limiting, retry, conditional GET cache.

Every source module borrows a client from here so politeness limits are
enforced in one place.

Host policies enforced:
  * data.sec.gov / www.sec.gov -- SEC caps automated access at 10 req/s and
    requires a descriptive User-Agent with a contact email.
  * www.opendoor.com -- 1 req/s by choice. robots.txt disallows /api/
    (except /api/agent/v1/); DISALLOWED_PREFIXES below encodes that, and
    get() refuses to fetch a blocked path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

# Mirrors https://www.opendoor.com/robots.txt (fetched 2026-09-20).
# We only ever need /properties/, /homes/ and /sitemaps/, but encode the
# blocklist so a future caller cannot accidentally hit an internal endpoint.
OPENDOOR_DISALLOWED_PREFIXES = (
    "/customers/", "/offers/", "/buyer/offers/", "/unsubscribed/", "/access",
    "/style/", "/templates/", "/market-chart/", "/register", "/account",
    "/reset-password", "/auth/", "/session/", "/seller-dashboard/",
    "/seller-offer/", "/seller-lead/", "/admin", "/broker", "/on-site",
    "/vendor", "/seller", "/api/", "/offer/api", "/ice-cream/api",
    "/trade/api", "/trade/socket", "/_", "/cloudflare_worker/",
    "/partner-api-proxy/", "/cosmos-testing-path", "/cosmos-delete-cache",
    "/mobile-login", "/token", "/mail",
)
OPENDOOR_ALLOWED_EXCEPTIONS = ("/api/agent/v1",)


class RateLimiter:
    """Simple thread-safe token bucket expressed as a minimum request interval."""

    def __init__(self, rate_per_sec: float) -> None:
        self._min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval


class ConditionalCache:
    """On-disk ETag / Last-Modified store for conditional GETs.

    Keeps bulk downloads (Redfin trackers are 111MB-1.5GB) and unchanged
    EDGAR filings from being re-fetched.
    """

    def __init__(self, cache_dir: Path) -> None:
        self.dir = cache_dir / "http"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:24]

    def meta_path(self, url: str) -> Path:
        return self.dir / f"{self._key(url)}.meta.json"

    def body_path(self, url: str) -> Path:
        return self.dir / f"{self._key(url)}.body"

    def load_meta(self, url: str) -> dict[str, Any]:
        p = self.meta_path(url)
        if p.exists():
            try:
                return json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def save(self, url: str, response: httpx.Response, body: bytes | None = None) -> None:
        meta = {
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
            "content_length": response.headers.get("content-length"),
            "fetched_at": time.time(),
        }
        self.meta_path(url).write_text(json.dumps(meta))
        if body is not None:
            self.body_path(url).write_bytes(body)

    def conditional_headers(self, url: str) -> dict[str, str]:
        meta = self.load_meta(url)
        headers: dict[str, str] = {}
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]
        return headers


class PoliteClient:
    """httpx client wrapper with rate limiting, retry and conditional caching."""

    def __init__(
        self,
        rate_per_sec: float,
        user_agent: str,
        *,
        timeout: float = 60.0,
        max_retries: int = 4,
        respect_opendoor_robots: bool = False,
    ) -> None:
        settings = get_settings()
        self.limiter = RateLimiter(rate_per_sec)
        self.cache = ConditionalCache(settings.cache_dir)
        self.max_retries = max_retries
        self.respect_opendoor_robots = respect_opendoor_robots
        self.client = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=timeout,
            follow_redirects=True,
        )

    # -- robots -------------------------------------------------------
    @staticmethod
    def _is_blocked(url: str) -> bool:
        path = httpx.URL(url).path
        if any(path.startswith(ok) for ok in OPENDOOR_ALLOWED_EXCEPTIONS):
            return False
        return any(path.startswith(bad) for bad in OPENDOOR_DISALLOWED_PREFIXES)

    # -- requests -----------------------------------------------------
    def get(self, url: str, *, conditional: bool = False, **kwargs: Any) -> httpx.Response:
        if self.respect_opendoor_robots and self._is_blocked(url):
            raise PermissionError(f"robots.txt disallows this path, refusing to fetch: {url}")

        headers = dict(kwargs.pop("headers", {}) or {})
        if conditional:
            headers.update(self.cache.conditional_headers(url))

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self.limiter.acquire()
            try:
                resp = self.client.get(url, headers=headers, **kwargs)
            except httpx.TransportError as exc:  # network blip
                last_exc = exc
                backoff = 2**attempt
                log.warning("transport error on %s (%s); retrying in %ss", url, exc, backoff)
                time.sleep(backoff)
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                backoff = float(resp.headers.get("Retry-After", 2**attempt))
                log.warning("HTTP %s on %s; backing off %.1fs", resp.status_code, url, backoff)
                time.sleep(backoff)
                continue

            return resp

        raise RuntimeError(f"exhausted {self.max_retries} retries for {url}") from last_exc

    def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def head(self, url: str, **kwargs: Any) -> httpx.Response:
        self.limiter.acquire()
        return self.client.head(url, follow_redirects=True, **kwargs)

    def stream(self, url: str, **kwargs: Any):
        """Context manager yielding a streaming response (for bulk downloads)."""
        self.limiter.acquire()
        return self.client.stream("GET", url, **kwargs)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# -- factories --------------------------------------------------------
def sec_client() -> PoliteClient:
    s = get_settings()
    return PoliteClient(s.sec_rate_limit, s.sec_user_agent)


def opendoor_client() -> PoliteClient:
    s = get_settings()
    # Identify honestly; Opendoor publishes these listings in its own sitemap.
    ua = f"OpendoorTelemetryResearch/1.0 (+contact via {_contact_from(s.sec_user_agent)})"
    return PoliteClient(s.opendoor_rate_limit, ua, respect_opendoor_robots=True)


def generic_client(rate_per_sec: float = 4.0) -> PoliteClient:
    s = get_settings()
    return PoliteClient(rate_per_sec, s.sec_user_agent)


def _contact_from(user_agent: str) -> str:
    for token in user_agent.split():
        if "@" in token:
            return token
    return "unknown"
