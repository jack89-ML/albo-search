"""Minimal HTTP client built on the standard library.

Keeps a cookie jar, sends a desktop browser user agent and retries with
exponential backoff on transient failures. No third-party dependencies.
"""

from __future__ import annotations

import http.cookiejar
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import UpstreamBlocked

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class HttpClient:
    def __init__(self, ua: str = DEFAULT_UA, timeout: float = 20.0,
                 retries: int = 3, delay: float = 1.5):
        jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))
        self._ua = ua
        self._timeout = timeout
        self._retries = retries
        self._delay = delay

    def _request(self, method: str, url: str, data: bytes | None,
                 headers: dict[str, str], referer: str | None):
        hdrs = {"User-Agent": self._ua, "Accept-Language": "it-IT,it;q=0.9"}
        if referer:
            hdrs["Referer"] = referer
        hdrs.update(headers)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        return self._opener.open(req, timeout=self._timeout)

    def _run(self, method: str, url: str, data: bytes | None,
             headers: dict[str, str], referer: str | None) -> bytes:
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                with self._request(method, url, data, headers, referer) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 429, 503):
                    last = exc
                else:
                    raise UpstreamBlocked(f"HTTP {exc.code} from {url}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
            if attempt < self._retries - 1:
                time.sleep(self._delay * (2 ** attempt))
        raise UpstreamBlocked(f"request failed after {self._retries} attempts: {last}")

    def get(self, url: str, headers: dict[str, str] | None = None,
            referer: str | None = None) -> bytes:
        return self._run("GET", url, None, headers or {}, referer)

    def post(self, url: str, data: dict[str, str],
             headers: dict[str, str] | None = None,
             referer: str | None = None) -> bytes:
        body = urllib.parse.urlencode(data).encode()
        hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
        hdrs.update(headers or {})
        return self._run("POST", url, body, hdrs, referer)

    def post_raw(self, url: str, raw: str,
                 headers: dict[str, str] | None = None,
                 referer: str | None = None) -> bytes:
        hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
        hdrs.update(headers or {})
        return self._run("POST", url, raw.encode(), hdrs, referer)
