"""Minimal HTTP client built on the standard library.

Keeps a cookie jar, sends a desktop browser user agent, decodes responses with
the charset the server declares and retries transient failures with jittered
exponential backoff. Retries apply to idempotent methods only: a POST to a
stateful JSF form must never be replayed silently (it would submit twice).

No third-party dependencies.
"""

from __future__ import annotations

import http.cookiejar
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import RegistryError, UpstreamBlocked

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Refuse anything that is not a plain web request: a sources.json pointing at
# file:// or another scheme must not turn the client into a file reader.
ALLOWED_SCHEMES = ("http", "https")

# Upper bound on a single response body: a hostile or broken endpoint must not
# be able to exhaust memory.
DEFAULT_MAX_BYTES = 25 * 1024 * 1024

_CHARSET_RE = re.compile(r"charset\s*=\s*['\"]?([\w.:-]+)", re.I)
_DECODE_CHAIN = ("utf-8", "iso-8859-1", "windows-1252")


def declared_charset(content_type: str | None) -> str | None:
    """Charset advertised in a Content-Type header, if any."""
    if not content_type:
        return None
    match = _CHARSET_RE.search(content_type)
    return match.group(1) if match else None


def decode_body(body: bytes, charset: str | None) -> str:
    """Decode with the declared charset, then a safe fallback chain.

    Italian institutional portals still serve ISO-8859-1 pages: decoding them
    as UTF-8 with ``errors='replace'`` mangles accented surnames.
    """
    candidates = ([charset] if charset else []) + list(_DECODE_CHAIN)
    for candidate in candidates:
        try:
            return body.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


class HttpClient:
    def __init__(self, ua: str = DEFAULT_UA, timeout: float = 20.0,
                 retries: int = 3, delay: float = 1.5,
                 max_bytes: int = DEFAULT_MAX_BYTES):
        jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))
        self._ua = ua
        self._timeout = timeout
        self._retries = retries
        self._delay = delay
        self._max_bytes = max_bytes

    # --- internals -------------------------------------------------------
    def _request(self, method: str, url: str, data: bytes | None,
                 headers: dict[str, str], referer: str | None):
        if urllib.parse.urlsplit(url).scheme not in ALLOWED_SCHEMES:
            raise RegistryError(
                f"refusing to open a non-http(s) URL: {url.split(':', 1)[0]}:…")
        hdrs = {"User-Agent": self._ua, "Accept-Language": "it-IT,it;q=0.9"}
        if referer:
            hdrs["Referer"] = referer
        hdrs.update(headers)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        return self._opener.open(req, timeout=self._timeout)

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError) -> float | None:
        """Seconds requested by a 429/503 Retry-After header, when numeric."""
        raw = exc.headers.get("Retry-After") if exc.headers else None
        if not raw:
            return None
        try:
            return max(0.0, min(60.0, float(raw.strip())))
        except (TypeError, ValueError):
            return None      # HTTP-date form: fall back to the backoff curve

    def _run(self, method: str, url: str, data: bytes | None,
             headers: dict[str, str], referer: str | None) -> tuple[bytes, str | None]:
        retryable = method.upper() == "GET"
        attempts = self._retries if retryable else 1
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                with self._request(method, url, data, headers, referer) as resp:
                    body = resp.read(self._max_bytes + 1)
                    if len(body) > self._max_bytes:
                        raise UpstreamBlocked(
                            f"response larger than {self._max_bytes} bytes "
                            f"from {url}")
                    return body, declared_charset(resp.headers.get("Content-Type"))
            except urllib.error.HTTPError as exc:
                transient = exc.code in (403, 429, 503)
                if not transient or not retryable:
                    raise UpstreamBlocked(f"HTTP {exc.code} from {url}") from exc
                last = exc
                pause = self._retry_after(exc)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if not retryable:
                    raise UpstreamBlocked(f"request failed: {exc}") from exc
                last = exc
                pause = None
            if attempt < attempts - 1:
                base = pause if pause is not None else self._delay * (2 ** attempt)
                time.sleep(base + random.uniform(0, self._delay * 0.3))
        raise UpstreamBlocked(f"request failed after {attempts} attempts: {last}")

    # --- public API (bytes) ---------------------------------------------
    def get(self, url: str, headers: dict[str, str] | None = None,
            referer: str | None = None) -> bytes:
        return self._run("GET", url, None, headers or {}, referer)[0]

    def post(self, url: str, data: dict[str, str],
             headers: dict[str, str] | None = None,
             referer: str | None = None) -> bytes:
        body = urllib.parse.urlencode(data).encode()
        hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
        hdrs.update(headers or {})
        return self._run("POST", url, body, hdrs, referer)[0]

    def post_raw(self, url: str, raw: str,
                 headers: dict[str, str] | None = None,
                 referer: str | None = None) -> bytes:
        hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
        hdrs.update(headers or {})
        return self._run("POST", url, raw.encode(), hdrs, referer)[0]

    # --- public API (decoded text) --------------------------------------
    def get_text(self, url: str, headers: dict[str, str] | None = None,
                 referer: str | None = None) -> tuple[str, str | None]:
        """GET and decode using the charset declared by the server."""
        body, charset = self._run("GET", url, None, headers or {}, referer)
        return decode_body(body, charset), charset

    def post_text(self, url: str, data: dict[str, str],
                  headers: dict[str, str] | None = None,
                  referer: str | None = None) -> tuple[str, str | None]:
        body = urllib.parse.urlencode(data).encode()
        hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
        hdrs.update(headers or {})
        raw, charset = self._run("POST", url, body, hdrs, referer)
        return decode_body(raw, charset), charset

    def post_raw_text(self, url: str, raw: str,
                      headers: dict[str, str] | None = None,
                      referer: str | None = None) -> tuple[str, str | None]:
        hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
        hdrs.update(headers or {})
        body, charset = self._run("POST", url, raw.encode(), hdrs, referer)
        return decode_body(body, charset), charset
