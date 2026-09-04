"""Core behaviour: exit codes, output rendering, zero-leak config guard."""

import codecs
import json
import unittest

from albo_search import config, output
from albo_search.errors import RegistryError, exit_code
from albo_search.output import Record, SearchOutcome

# Case-related tokens, rot13-encoded so the literal names never appear in
# the repository (the directive is zero references anywhere).
_ENCODED = [
    "pebgbar", "pngnamneb", "fniryyv", "pnynoevn", "fpnaqvppv",
    "snovnab", "fpnyvfr", "crenppuvb", "pbframn", "pnfgebivyynev",
    "iremvab", "fvyn",
]
FORBIDDEN = tuple(codecs.encode(token, "rot13") for token in _ENCODED)


class ExitCodeTest(unittest.TestCase):
    def test_found_zero(self):
        self.assertEqual(exit_code(True, 3), 0)

    def test_empty_one(self):
        self.assertEqual(exit_code(True, 0), 1)

    def test_failure_two(self):
        self.assertEqual(exit_code(False, 0), 2)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.outcome = SearchOutcome(
            query="Rossi", source="SFERABIT", scope="1080",
            records=[Record(source="SFERABIT", scope="1080", name="ROSSI MARIO",
                            extra={"category": "Avvocati", "city": "Milano"}),
                     Record(source="SFERABIT", scope="1080", name="ROSSI LUIGI",
                            extra={"category": "Avvocati", "city": "Milano"})],
            total=2,
        )

    def test_table_contains_rows_and_header(self):
        text = output.render_table(self.outcome)
        self.assertIn("ROSSI MARIO", text)
        self.assertIn("ROSSI LUIGI", text)
        self.assertIn("query 'Rossi'", text)

    def test_json_is_pure_and_parseable(self):
        parsed = json.loads(output.render_json(self.outcome))
        self.assertEqual(parsed["query"], "Rossi")
        self.assertEqual(len(parsed["results"]), 2)
        self.assertEqual(parsed["results"][0]["name"], "ROSSI MARIO")

    def test_csv_has_header_and_two_rows(self):
        text = output.render_csv(self.outcome)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 3)  # header + 2 records
        self.assertIn("source,scope,name", lines[0])

    def test_table_empty_verified(self):
        empty = SearchOutcome(query="Rossi", source="SFERABIT", scope="1080",
                              records=[], total=0, verified_empty=True)
        self.assertIn("verified negative", output.render_table(empty))

    def test_cell_newlines_are_flattened(self):
        outcome = SearchOutcome(
            query="Rossi", source="X", scope="Y",
            records=[Record(source="X", scope="Y", name="A",
                            extra={"details": "line1\nline2\rline3"})],
            total=1,
        )
        table = output.render_table(outcome)
        self.assertNotIn("\r", table)
        self.assertNotIn("\nline1", table)
        self.assertIn("line1 · line2 · line3", table)
        csv_text = output.render_csv(outcome)
        self.assertNotIn("\rline", csv_text)
        self.assertIn("line1 · line2 · line3", csv_text)


class ZeroLeakTest(unittest.TestCase):
    """Guards the 'no case references' directive for the default config."""

    def test_packaged_sources_are_neutral(self):
        blob = json.dumps(config.default_sources()).lower()
        for token in FORBIDDEN:
            self.assertNotIn(token, blob, f"forbidden token in sources: {token}")

    def _clean_env(self):
        import os
        env = dict(os.environ)
        env.pop("ALBO_SEARCH_CONFIG", None)
        env.pop("ALBO_SOURCES", None)
        return env

    def test_xdg_override_is_merged(self):
        import os
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            cfg_dir = os.path.join(tmp, "config", "albo-search")
            os.makedirs(cfg_dir)
            with open(os.path.join(cfg_dir, "sources.json"), "w") as handle:
                handle.write(json.dumps({
                    "lawyers": {"sferabit": [{"name": "BARI", "id": 9999}]}
                }))
            env = self._clean_env()
            env["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = config.resolve_sources()
            names = [x["name"] for x in cfg["lawyers"]["sferabit"]]
            self.assertIn("MILANO", names)   # bundled default preserved
            self.assertIn("BARI", names)     # XDG override merged in

    def test_env_config_takes_precedence_over_xdg(self):
        import os
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            xdg = os.path.join(tmp, "config", "albo-search")
            os.makedirs(xdg)
            with open(os.path.join(xdg, "sources.json"), "w") as handle:
                handle.write(json.dumps({
                    "lawyers": {"iscrivo": [{"name": "NAPOLI",
                                             "url": "https://x/napoli"}]}
                }))
            env_path = os.path.join(tmp, "env-sources.json")
            with open(env_path, "w") as handle:
                handle.write(json.dumps({
                    "lawyers": {"iscrivo": [{"name": "TORINO",
                                             "url": "https://x/torino"}]}
                }))
            env = self._clean_env()
            env["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
            env["ALBO_SEARCH_CONFIG"] = env_path
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = config.resolve_sources()
            names = [x["name"] for x in cfg["lawyers"]["iscrivo"]]
            self.assertIn("TORINO", names)
            self.assertNotIn("NAPOLI", names)  # XDG ignored, env wins

    def test_sample_bars_present(self):
        lawyers = config.default_sources()["lawyers"]
        names = [x["name"] for x in lawyers["sferabit"]]
        names += [x["name"] for x in lawyers["iscrivo"]]
        self.assertIn("MILANO", names)
        self.assertIn("FIRENZE", names)
        self.assertIn("SALERNO", names)

    def test_find_lawyer_bar_resolves_platform(self):
        cfg = config.default_sources()
        platform, bar = config.find_lawyer_bar(cfg, "milano")
        self.assertEqual(platform, "sferabit")
        self.assertEqual(bar["id"], 1080)
        platform, bar = config.find_lawyer_bar(cfg, "salerno")
        self.assertEqual(platform, "iscrivo")
        self.assertIn("url", bar)

    def test_find_lawyer_bar_unknown_lists_available(self):
        cfg = config.default_sources()
        with self.assertRaises(RegistryError) as ctx:
            config.find_lawyer_bar(cfg, "NONEXISTENT")
        self.assertIn("MILANO", str(ctx.exception))

    def test_explicit_missing_sources_raises(self):
        with self.assertRaises(RegistryError) as ctx:
            config.resolve_sources("/nonexistent/albo-sources.json")
        self.assertIn("sources file not found", str(ctx.exception))

    def test_whole_repo_tree_is_neutral(self):
        """Scans every text file under the project for forbidden tokens.

        The guard module itself is skipped: it stores the tokens rot13-encoded.
        """
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        skipped = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}
        offenders = []
        for path in root.rglob("*"):
            if not path.is_file() or any(part in skipped for part in path.parts):
                continue
            if path.name == "test_core.py":  # encoded tokens live here
                continue
            if path.suffix.lower() in {".png", ".jpg", ".pyc", ".pdf"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            for token in FORBIDDEN:
                if token in text:
                    offenders.append((str(path.relative_to(root)), token))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
