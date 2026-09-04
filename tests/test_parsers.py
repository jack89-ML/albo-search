"""Parser tests against offline fixtures (no network)."""

import pathlib
import unittest

from albo_search import cassaforense, sferabit
from albo_search.errors import ParseFailure
from albo_search.http import HttpClient

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class _FakeHttp(HttpClient):
    """Injected responses; real parsing code, fake transport."""

    def __init__(self, body: bytes):
        self._body = body

    def get(self, url, headers=None, referer=None):
        return self._body

    def post_raw(self, url, raw, headers=None, referer=None):
        return self._body

    def post(self, url, data, headers=None, referer=None):
        return self._body


class SferabitParserTest(unittest.TestCase):
    def test_results_parsed(self):
        outcome = sferabit.search(_FakeHttp(_fixture("sferabit_results.html")),
                                  1080, "Rossi", limit=25)
        self.assertEqual(outcome.found, 3)
        self.assertEqual(outcome.total, 3)
        names = [r.name for r in outcome.records]
        self.assertIn("ROSSI MARIO", names)
        self.assertEqual(outcome.records[0].extra.get("category"), "Avvocati")

    def test_surname_filter_applied(self):
        """Stray non-matching rows on the page are ignored."""
        html = b"""<table>
<tr><td colspan="5">1-20 di 3 nominativi trovati</td></tr>
<tr><td><a>apri</a></td><td>Avvocati</td><td>ROSSI MARIO</td><td>x</td><td>y</td></tr>
<tr><td><a>apri</a></td><td>Avvocati</td><td>ROSSI ANNA</td><td>x</td><td>y</td></tr>
<tr><td><a>apri</a></td><td>Avvocati</td><td>BIANCHI PAOLO</td><td>x</td><td>y</td></tr>
</table>"""
        outcome = sferabit.search(_FakeHttp(html), 1080, "Rossi", limit=25)
        self.assertEqual(outcome.found, 2)
        self.assertEqual(outcome.total, 3)
        self.assertNotIn("BIANCHI", [r.name for r in outcome.records])

    def test_empty_is_verified_negative(self):
        outcome = sferabit.search(_FakeHttp(_fixture("sferabit_empty.html")),
                                  1080, "Rossi", limit=25)
        self.assertEqual(outcome.found, 0)
        self.assertTrue(outcome.verified_empty)

    def test_total_without_rows_raises(self):
        html = b"<table><tr><td>1-20 di 7 nominativi trovati</td></tr></table>"
        with self.assertRaises(ParseFailure):
            sferabit.search(_FakeHttp(html), 1080, "Rossi", limit=25)


class CassaForenseParserTest(unittest.TestCase):
    def test_results_parsed(self):
        html = _fixture("cassaforense_results.html").decode()
        records, empty = cassaforense.parse_fragment(html, "Rossi")
        self.assertEqual(len(records), 2)
        self.assertEqual(empty, "")
        self.assertIn("ROSSI MARIO", [r.name for r in records])

    def test_text_layout_parsed(self):
        html = _fixture("cassaforense_text_results.html").decode()
        records, empty = cassaforense.parse_fragment(html, "Rossi")
        self.assertEqual(len(records), 2)
        self.assertEqual(empty, "")
        names = [r.name for r in records]
        self.assertIn("ROSSI ALBERTO", names)
        self.assertNotIn("BIANCHI PAOLO", names)
        self.assertEqual(records[0].extra.get("order"), "BOLOGNA")

    def test_empty_message_detected(self):
        html = _fixture("cassaforense_empty.html").decode()
        records, empty = cassaforense.parse_fragment(html, "Rossi")
        self.assertEqual(records, [])
        self.assertTrue(empty)

    def test_unrelated_html_yields_no_records_no_empty(self):
        records, empty = cassaforense.parse_fragment(
            "<html><body>nothing relevant</body></html>", "Rossi")
        self.assertEqual(records, [])
        self.assertEqual(empty, "")


if __name__ == "__main__":
    unittest.main()
