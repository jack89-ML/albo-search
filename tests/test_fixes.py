"""Regressions found in the 0.2.0 code review."""

import json
import os
import unittest
from unittest import mock

from albo_search import config, output
from albo_search.errors import RegistryError
from albo_search.output import Record, SearchOutcome


class JsonKeyCollisionTest(unittest.TestCase):
    def test_record_name_is_not_overwritten_by_an_extra_column(self):
        outcome = SearchOutcome(
            query="rossi", source="X", scope="s",
            records=[Record(source="X", scope="s", name="ROSSI MARIO",
                            extra={"name": "SHOULD NOT WIN"})])
        payload = json.loads(output.render_json(outcome))
        self.assertEqual(payload["results"][0]["name"], "ROSSI MARIO")


class ConfigEnvPathTest(unittest.TestCase):
    def test_missing_env_file_raises_instead_of_silently_falling_back(self):
        missing = "/tmp/albo-config-mancante.json"
        with mock.patch.dict(os.environ, {"ALBO_SEARCH_CONFIG": missing}):
            with self.assertRaises(RegistryError):
                config._override_paths(None)

    def test_existing_env_file_is_used(self):
        path = "/tmp/albo-sources-ok.json"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("[]")
        with mock.patch.dict(os.environ, {"ALBO_SEARCH_CONFIG": path}):
            resolved = config._override_paths(None)
        self.assertEqual(len(resolved), 1)
        self.assertTrue(str(resolved[0]).endswith("albo-sources-ok.json"))

    def test_explicit_missing_override_is_a_hard_error(self):
        with self.assertRaises(RegistryError):
            config._override_paths("/tmp/albo-config-assente.json")


if __name__ == "__main__":
    unittest.main()
