"""Pure row parsing for the Iscrivo adapter (no browser involved)."""

import unittest

from albo_search import iscrivo


class ParseRowsTest(unittest.TestCase):
    def test_matching_row_becomes_a_record(self):
        rows = [
            ["Nominativo", "Indirizzo", "Trovati 3 nominativi"],   # header
            ["AVV. ROSSI MARIO", "Via Roma 1 - FIRENZE", "Apri"],
            ["AVV. BIANCHI LUCA", "Via Verdi 2 - FIRENZE", "Apri"],
        ]
        records = iscrivo.parse_rows(rows, "Rossi", scope="http://x")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertIn("ROSSI", record.name)
        self.assertEqual(record.source, "ISCRIVO")
        self.assertEqual(record.scope, "http://x")
        self.assertIn("Via Roma", record.extra["details"])

    def test_surname_matching_is_case_insensitive(self):
        records = iscrivo.parse_rows([["avv. rossi mario", "Firenze"]], "ROSSI")
        self.assertEqual(len(records), 1)

    def test_headers_pagers_and_containers_are_skipped(self):
        rows = [
            ["Nominativo", "Indirizzo"],
            ["p 1 p"],
            ["x" * 500 + " ROSSI"],
            ["Avv. Rossi Uno e Avv. Rossi Due", "Firenze"],
            [],
        ]
        self.assertEqual(iscrivo.parse_rows(rows, "Rossi"), [])

    def test_duplicate_rows_are_collapsed(self):
        row = ["AVV. ROSSI MARIO", "Firenze"]
        self.assertEqual(len(iscrivo.parse_rows([row, list(row)], "Rossi")), 1)

    def test_limit_is_respected(self):
        rows = [[f"AVV. ROSSI {index}", "Firenze"] for index in range(10)]
        self.assertEqual(len(iscrivo.parse_rows(rows, "Rossi", limit=3)), 3)

    def test_row_without_the_surname_is_ignored(self):
        self.assertEqual(iscrivo.parse_rows([["AVV. BIANCHI LUCA", "Roma"]],
                                            "Rossi"), [])


class ReactiveWaitTest(unittest.TestCase):
    def test_wait_uses_the_page_function_and_tolerates_timeouts(self):
        calls = {}

        class Page:
            def wait_for_function(self, script, timeout=None):
                calls["script"] = script
                calls["timeout"] = timeout

        iscrivo.wait_for_results(Page(), 9000)
        self.assertIn("Nessun", calls["script"])
        self.assertEqual(calls["timeout"], 3000)

    def test_timeout_does_not_raise(self):
        class Page:
            def wait_for_function(self, script, timeout=None):
                raise RuntimeError("timeout")

        iscrivo.wait_for_results(Page(), 9000)   # must not propagate

    def test_page_without_wait_support_is_tolerated(self):
        class LegacyPage:
            pass

        iscrivo.wait_for_results(LegacyPage(), 9000)
