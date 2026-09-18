"""CONAF register adapter: pure parsing, query validation, retry policy.

All offline: the transport is a stub that records what the adapter asked it to
send and replays canned responses.
"""

import pathlib
import unittest

from albo_search import config, conaf, output
from albo_search.errors import ParseFailure, RegistryError
from albo_search.http import HttpClient

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeClient(HttpClient):
    """Replays scripted responses and remembers every request body.

    Mirrors the real client's JSON API; only the transport is fake.
    """

    def __init__(self, *responses):
        self.responses = list(responses)
        self.bodies: list[dict] = []
        self.ids: list[dict] = []
        self.urls: list[str] = []
        self.idempotent: list[bool] = []

    def post_json_text(self, url, payload, headers=None, referer=None,
                       idempotent=False):
        self.urls.append(url)
        self.ids.append(dict(headers or {}))
        self.bodies.append(dict(payload))
        self.idempotent.append(idempotent)
        reply = self.responses[min(len(self.bodies) - 1, len(self.responses) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply, "utf-8"


class ParseTest(unittest.TestCase):
    def test_record_fields_are_mapped(self):
        records, total = conaf.parse_response(_fixture("conaf_results.json"),
                                              surname="ROSSI", limit=50)
        self.assertEqual(total, 3)          # register reports three rows
        self.assertEqual(len(records), 2)   # one of them is another surname
        first = records[0]
        self.assertEqual(first.source, "CONAF")
        self.assertEqual(first.name, "ROSSI MARIO")
        self.assertEqual(first.scope, "FI")
        self.assertEqual(first.extra["section"], "A")
        self.assertEqual(first.extra["title"], "Dottore Agronomo")
        self.assertEqual(first.extra["number"], "1234")
        self.assertEqual(first.extra["registered"], "2001-03-15")
        self.assertEqual(first.extra["birth"], "1970-05-02 BOLOGNA")
        self.assertEqual(first.extra["residence"], "VIA ROMA, 10 50123")
        self.assertEqual(first.extra["status"], "")
        self.assertEqual(first.extra["public_employee"], "")
        self.assertEqual(first.extra["subject_id"], "40123")

    def test_disciplinary_flags_become_status(self):
        records, _ = conaf.parse_response(_fixture("conaf_results.json"), limit=50)
        statuses = {r.name: r.extra["status"] for r in records}
        self.assertEqual(statuses["ROSSI ANNA"], "suspended")
        self.assertEqual(statuses["BIANCHI PAOLO"], "removed")
        self.assertEqual(statuses["ROSSI MARIO"], "")
        public = {r.name: r.extra["public_employee"] for r in records}
        self.assertEqual(public["ROSSI ANNA"], "yes")
        self.assertEqual(public["ROSSI MARIO"], "")

    def test_null_fields_do_not_leak_python_none(self):
        payload = ('{"returnedObject": [{"cognome": "VERDI", "nome": "LIA",'
                   ' "sezioneRichiesta": null, "capResidenza": null,'
                   ' "indirizzoResidenza": "VIA X, 1", "numeroCivico": null}]}')
        records, total = conaf.parse_response(payload)
        self.assertEqual(total, 1)
        self.assertEqual(records[0].name, "VERDI LIA")
        self.assertEqual(records[0].extra["section"], "")
        self.assertEqual(records[0].extra["residence"], "VIA X, 1")

    def test_limit_truncates_records_but_not_the_total(self):
        records, total = conaf.parse_response(_fixture("conaf_results.json"),
                                              limit=1)
        self.assertEqual(len(records), 1)
        self.assertEqual(total, 3)

    def test_surname_match_is_case_insensitive(self):
        records, total = conaf.parse_response(_fixture("conaf_results.json"),
                                              surname="rossi")
        self.assertEqual((len(records), total), (2, 3))

    def test_rows_that_are_not_objects_are_ignored(self):
        records, total = conaf.parse_response('{"returnedObject": ["x", null]}')
        self.assertEqual((records, total), ([], 0))

    def test_html_error_page_raises_instead_of_reporting_empty(self):
        with self.assertRaises(ParseFailure) as ctx:
            conaf.parse_response(_fixture("conaf_error.html"), surname="ROSSI")
        self.assertIn("non-JSON", str(ctx.exception))

    def test_api_level_error_raises(self):
        with self.assertRaises(RegistryError) as ctx:
            conaf.parse_response('{"error": "unauthorized", "httpStatus": 401}')
        self.assertIn("unauthorized", str(ctx.exception))

    def test_missing_payload_key_raises(self):
        with self.assertRaises(ParseFailure) as ctx:
            conaf.parse_response('{"error": null, "httpStatus": 200}')
        self.assertIn("returnedObject", str(ctx.exception))

    def test_non_object_payload_raises(self):
        with self.assertRaises(ParseFailure):
            conaf.parse_response("[1, 2, 3]")

    def test_returned_object_of_the_wrong_type_raises(self):
        with self.assertRaises(ParseFailure):
            conaf.parse_response('{"returnedObject": {"cognome": "ROSSI"}}')


class QueryTest(unittest.TestCase):
    def test_every_filter_key_is_always_sent(self):
        body = conaf.build_query(cognome="rossi")
        self.assertEqual(sorted(body), sorted(conaf.FIELDS))

    def test_filters_are_normalized(self):
        body = conaf.build_query(nome=" mario ", cognome="rossi",
                                 cf="rssmra70e02a944x", ordine="fi")
        self.assertEqual(body["nome"], "MARIO")
        self.assertEqual(body["cognome"], "ROSSI")
        self.assertEqual(body["cf"], "RSSMRA70E02A944X")
        self.assertEqual(body["ordineTerritorialeCompetente"], "FI")

    def test_a_query_without_an_identifier_is_refused(self):
        client = FakeClient(_fixture("conaf_empty.json"))
        with self.assertRaises(ValueError) as ctx:
            conaf.search(client)
        self.assertIn("--cognome", str(ctx.exception))
        self.assertEqual(client.bodies, [])       # refused before any request

    def test_order_only_lookup_is_refused(self):
        client = FakeClient(_fixture("conaf_results.json"))
        with self.assertRaises(ValueError):
            conaf.search(client, ordine="FI")
        self.assertEqual(client.bodies, [])

    def test_a_city_name_as_order_is_refused(self):
        """An unrecognised order filter is dropped upstream: refuse it here."""
        client = FakeClient(_fixture("conaf_results.json"))
        with self.assertRaises(ValueError) as ctx:
            conaf.search(client, cognome="ROSSI", ordine="FIRENZE")
        self.assertIn("province", str(ctx.exception))
        self.assertEqual(client.bodies, [])


class SearchFlowTest(unittest.TestCase):
    def test_successful_search_reports_scope_and_total(self):
        client = FakeClient(_fixture("conaf_results.json"))
        outcome = conaf.search(client, cognome="ROSSI", ordine="FI")
        self.assertEqual(outcome.source, "CONAF")
        self.assertEqual(outcome.scope, "FI")
        self.assertEqual(outcome.found, 2)
        self.assertEqual(outcome.total, 3)
        self.assertFalse(outcome.verified_empty)
        self.assertEqual(outcome.query, "ROSSI")

    def test_endpoint_origin_and_idempotency_are_wired(self):
        client = FakeClient(_fixture("conaf_results.json"))
        conaf.search(client, cognome="ROSSI")
        self.assertEqual(client.urls, [conaf.DEFAULT_ENDPOINT])
        self.assertEqual(client.ids[0]["Origin"], conaf.DEFAULT_ORIGIN)
        # a read-only query API, so a transient failure may be replayed
        self.assertEqual(client.idempotent, [True])

    def test_endpoint_can_be_overridden(self):
        client = FakeClient(_fixture("conaf_results.json"))
        conaf.search(client, cognome="ROSSI", endpoint="https://mirror/api",
                     origin="https://mirror")
        self.assertEqual(client.urls, ["https://mirror/api"])
        self.assertEqual(client.ids[0]["Origin"], "https://mirror")

    def test_verified_negative_carries_a_note(self):
        client = FakeClient(_fixture("conaf_empty.json"))
        outcome = conaf.search(client, cognome="VERDI")
        self.assertEqual(outcome.found, 0)
        self.assertEqual(outcome.total, 0)
        self.assertTrue(outcome.verified_empty)
        self.assertIn("no entry", outcome.note)

    def test_matches_that_cannot_be_read_raise_instead_of_going_silent(self):
        """Register reports rows, the surname filter keeps none: that is a
        failed lookup, not a negative one."""
        client = FakeClient(_fixture("conaf_results.json"))
        with self.assertRaises(ParseFailure) as ctx:
            conaf.search(client, cognome="VERDI")
        self.assertIn("3 matches", str(ctx.exception))

    def test_tax_code_lookup_uses_the_code_as_the_query_label(self):
        client = FakeClient(_fixture("conaf_results.json"))
        outcome = conaf.search(client, cf="RSSMRA70E02A944X", limit=1)
        self.assertEqual(outcome.query, "RSSMRA70E02A944X")
        self.assertEqual(outcome.found, 1)

    def test_mixed_case_input_is_retried_as_typed(self):
        """A case-sensitive register must not turn into a false negative."""
        client = FakeClient(_fixture("conaf_empty.json"),
                            _fixture("conaf_results.json"))
        outcome = conaf.search(client, cognome="Rossi")
        self.assertEqual(outcome.found, 2)
        self.assertEqual(client.bodies[0]["cognome"], "ROSSI")
        self.assertEqual(client.bodies[1]["cognome"], "Rossi")

    def test_no_second_attempt_when_the_first_one_matched(self):
        client = FakeClient(_fixture("conaf_results.json"))
        conaf.search(client, cognome="Rossi")
        self.assertEqual(len(client.bodies), 1)

    def test_no_second_attempt_for_an_already_uppercase_query(self):
        client = FakeClient(_fixture("conaf_empty.json"))
        conaf.search(client, cognome="ROSSI")
        self.assertEqual(len(client.bodies), 1)

    def test_upstream_failure_propagates(self):
        from albo_search.errors import UpstreamBlocked
        client = FakeClient(UpstreamBlocked("HTTP 503"))
        with self.assertRaises(UpstreamBlocked):
            conaf.search(client, cognome="ROSSI")

    def test_render_table_shows_the_register_columns(self):
        client = FakeClient(_fixture("conaf_results.json"))
        table = output.render_table(conaf.search(client, cognome="ROSSI"))
        self.assertIn("CONAF", table)
        self.assertIn("Agronomo Iunior", table)
        self.assertIn("suspended", table)


class RegistryConfigTest(unittest.TestCase):
    def test_bundled_registry_settings(self):
        cfg = config.default_sources()
        settings = config.registry_settings(cfg, "conaf")
        self.assertEqual(settings["endpoint"], conaf.DEFAULT_ENDPOINT)
        self.assertEqual(settings["origin"], conaf.DEFAULT_ORIGIN)

    def test_override_replaces_one_key_and_keeps_the_other(self):
        settings = config.registry_settings(
            {"registries": {"conaf": {"endpoint": "https://mirror/api"}}},
            "conaf")
        self.assertEqual(settings["endpoint"], "https://mirror/api")
        self.assertEqual(settings["origin"], conaf.DEFAULT_ORIGIN)

    def test_unknown_override_key_is_refused(self):
        with self.assertRaises(RegistryError) as ctx:
            config.registry_settings(
                {"registries": {"conaf": {"endpoit": "https://mirror/api"}}},
                "conaf")
        self.assertIn("endpoit", str(ctx.exception))

    def test_non_object_override_is_refused(self):
        with self.assertRaises(RegistryError):
            config.registry_settings({"registries": {"conaf": "https://x"}},
                                     "conaf")


if __name__ == "__main__":
    unittest.main()
