"""Anagrafe parsing, tested without a browser.

The DOM walk stays in `search`; everything that decides *what* a row means is
pure and exercised here (it used to be reachable only through Playwright).
"""

import unittest

from albo_search import anagrafe


class NormTest(unittest.TestCase):
    def test_whitespace_is_collapsed(self):
        self.assertEqual(anagrafe._norm("  Rossi \n\t Mario  "), "Rossi Mario")


class FieldMapTest(unittest.TestCase):
    def test_headers_are_mapped_to_canonical_fields(self):
        mapping = anagrafe._field_map(["Cognome", "Nome", "Data di nascita",
                                       "Note"])
        self.assertEqual(mapping, {0: "cognome", 1: "nome", 2: "data_nascita"})

    def test_unknown_headers_are_dropped(self):
        self.assertEqual(anagrafe._field_map(["Cognome", "Colore preferito"]),
                         {0: "cognome"})


class ExtractFieldTest(unittest.TestCase):
    def test_label_value_is_read(self):
        body = "Professione: Avvocato\nTitolo di studio: Laurea"
        self.assertEqual(anagrafe._extract_field(body, "Professione"), "Avvocato")
        self.assertEqual(anagrafe._extract_field(body, "Titolo di studio"), "Laurea")

    def test_missing_label_is_empty(self):
        self.assertEqual(anagrafe._extract_field("niente", "Professione"), "")


class SelectHitsTest(unittest.TestCase):
    ROWS = [
        {"cells": ["Cognome", "Nome", "Data di nascita"], "href": None},
        {"cells": ["ROSSI", "MARIO", "12/03/1970"], "href": "InfoAnagrafica?id=1"},
        {"cells": ["ROSSI", "ANNA", "01/01/1980"], "href": "InfoAnagrafica?id=2"},
        {"cells": ["BIANCHI", "LUCA", "02/02/1982"], "href": "InfoAnagrafica?id=3"},
        {"cells": [], "href": None},
    ]

    def test_surname_is_required(self):
        hits = anagrafe.select_hits(self.ROWS, "Rossi")
        self.assertEqual([h["cells"][1] for h in hits], ["MARIO", "ANNA"])

    def test_header_row_does_not_match_a_real_surname(self):
        # The filter is a plain surname token: a header row is only matched by
        # a nonsense query ("Cognome"), and the portal never returns its own
        # header among the result rows.
        headers = [{"cells": ["Cognome", "Nome", "Data di nascita"], "href": None}]
        self.assertEqual(anagrafe.select_hits(headers, "Rossi"), [])

    def test_place_filter_is_applied(self):
        rows = [{"cells": ["ROSSI", "MARIO", "FIRENZE"], "href": "x"},
                {"cells": ["ROSSI", "ANNA", "MILANO"], "href": "y"}]
        hits = anagrafe.select_hits(rows, "Rossi", luogo="firenze")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["href"], "x")

    def test_link_is_preserved(self):
        hits = anagrafe.select_hits(self.ROWS, "Rossi")
        self.assertEqual(hits[0]["href"], "InfoAnagrafica?id=1")


class BuildRecordTest(unittest.TestCase):
    def test_mapping_drives_the_fields(self):
        name, extra = anagrafe.build_record(
            ["ROSSI", "MARIO", "12/03/1970"],
            {0: "cognome", 1: "nome", 2: "data_nascita"})
        self.assertEqual(name, "ROSSI MARIO")
        self.assertEqual(extra["data_nascita"], "12/03/1970")

    def test_positional_fallback_when_the_header_is_unreadable(self):
        name, extra = anagrafe.build_record(
            ["ROSSI", "MARIO", "M", "12/03/1970", "FIRENZE"], {})
        self.assertEqual(name, "ROSSI MARIO")
        self.assertEqual(extra["luogo"], "FIRENZE")
        self.assertEqual(extra["sesso"], "M")

    def test_short_row_keeps_the_first_cell_as_name(self):
        name, extra = anagrafe.build_record(["ROSSI MARIO"], {})
        self.assertEqual(name, "ROSSI MARIO")
        self.assertEqual(extra, {})

    def test_mapping_without_names_falls_back_to_the_whole_row(self):
        name, _extra = anagrafe.build_record(["X", "Y"], {0: "ente", 1: "carica"})
        self.assertEqual(name, "X Y")


if __name__ == "__main__":
    unittest.main()
