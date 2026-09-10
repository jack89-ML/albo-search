"""HTTP client behaviour: decoding, retry policy, guards (all offline)."""

import unittest
import urllib.error
from unittest import mock

from albo_search import http as http_mod
from albo_search.errors import RegistryError, UpstreamBlocked
from albo_search.http import HttpClient, decode_body, declared_charset


class Response:
    def __init__(self, body: bytes, content_type: str = "text/html; charset=utf-8"):
        self._body = body
        self.headers = {"Content-Type": content_type}

    def read(self, amount=None):
        return self._body if amount is None else self._body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Counts calls and replays a scripted sequence of outcomes."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def open(self, request, timeout=None):
        self.calls += 1
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = {"Retry-After": retry_after} if retry_after else None
    return urllib.error.HTTPError("https://x/y", code, "boom", headers, None)


class DecodingTest(unittest.TestCase):
    def test_declared_charset_is_used(self):
        self.assertEqual(declared_charset("text/html; charset=ISO-8859-1"),
                         "ISO-8859-1")
        self.assertEqual(declared_charset('text/html; charset="utf-8"'), "utf-8")
        self.assertIsNone(declared_charset("application/json"))

    def test_latin1_page_is_not_mangled(self):
        # the classic Italian portal case: "Rossi à" served as ISO-8859-1
        body = "Rossi \u00e0".encode("iso-8859-1")
        self.assertEqual(decode_body(body, "iso-8859-1"), "Rossi \u00e0")

    def test_unknown_charset_falls_back_without_crashing(self):
        self.assertEqual(decode_body(b"caf\xc3\xa9", "not-a-charset"), "caf\u00e9")
        self.assertEqual(decode_body(b"caf\xe9", None), "caf\u00e9")

    def test_get_text_reports_the_charset(self):
        client = HttpClient()
        client._opener = FakeOpener(Response(b"Rossi \xe0", "text/html; charset=ISO-8859-1"))
        text, charset = client.get_text("https://example.org/x")
        self.assertEqual(charset, "ISO-8859-1")
        self.assertEqual(text, "Rossi \u00e0")


class RetryPolicyTest(unittest.TestCase):
    def setUp(self):
        self.client = HttpClient(retries=3, delay=0.01)

    def test_get_retries_transient_errors(self):
        opener = FakeOpener(http_error(503), http_error(503), Response(b"ok"))
        self.client._opener = opener
        with mock.patch.object(http_mod.time, "sleep"):
            self.assertEqual(self.client.get("https://x/y"), b"ok")
        self.assertEqual(opener.calls, 3)

    def test_post_is_never_replayed(self):
        """A stateful JSF form must not be submitted twice."""
        opener = FakeOpener(http_error(503))
        self.client._opener = opener
        with mock.patch.object(http_mod.time, "sleep"):
            with self.assertRaises(UpstreamBlocked):
                self.client.post("https://x/y", {"a": "b"})
        self.assertEqual(opener.calls, 1)

    def test_retry_after_is_honoured(self):
        opener = FakeOpener(http_error(429, "7"), Response(b"ok"))
        self.client._opener = opener
        with mock.patch.object(http_mod.time, "sleep") as sleeper:
            self.client.get("https://x/y")
        self.assertGreaterEqual(sleeper.call_args[0][0], 7.0)

    def test_non_transient_error_is_not_retried(self):
        opener = FakeOpener(http_error(404))
        self.client._opener = opener
        with self.assertRaises(UpstreamBlocked):
            self.client.get("https://x/y")
        self.assertEqual(opener.calls, 1)

    def test_backoff_grows_and_is_jittered(self):
        opener = FakeOpener(http_error(503), http_error(503), Response(b"ok"))
        self.client._opener = opener
        with mock.patch.object(http_mod.time, "sleep") as sleeper:
            self.client.get("https://x/y")
        first, second = (call[0][0] for call in sleeper.call_args_list)
        self.assertGreater(second, first)          # exponential
        self.assertGreaterEqual(first, self.client._delay)


class GuardTest(unittest.TestCase):
    def test_non_http_scheme_is_refused(self):
        with self.assertRaises(RegistryError):
            HttpClient().get("file:///etc/passwd")

    def test_response_larger_than_the_cap_is_refused(self):
        client = HttpClient(max_bytes=10)
        client._opener = FakeOpener(Response(b"x" * 100))
        with self.assertRaises(UpstreamBlocked):
            client.get("https://x/y")
