"""CLI behaviour with mocked registry modules (offline)."""

import contextlib
import io
import unittest
from unittest import mock

from albo_search import cli, conaf
from albo_search.output import Record, SearchOutcome


def _outcome(found: int):
    records = [Record(source="X", scope="Y", name=f"MATCH {i}") for i in range(found)]
    return SearchOutcome(query="Rossi", source="X", scope="Y",
                         records=records, total=found,
                         verified_empty=found == 0)


class CliTest(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.run(argv)
        return code, buf.getvalue()

    def test_found_exits_zero(self):
        with mock.patch.object(cli.sferabit, "search",
                               return_value=_outcome(2)) as mocked:
            code, out = self._run(["avvocati", "--foro", "milano", "Rossi"])
        mocked.assert_called_once()
        self.assertEqual(code, 0)
        self.assertIn("MATCH 0", out)

    def test_not_found_exits_one(self):
        with mock.patch.object(cli.sferabit, "search",
                               return_value=_outcome(0)):
            code, _ = self._run(["avvocati", "--foro", "milano", "Rossi"])
        self.assertEqual(code, 1)

    def test_unknown_bar_exits_two(self):
        code, _ = self._run(["avvocati", "--foro", "NONEXISTENT", "Rossi"])
        self.assertEqual(code, 2)

    def test_json_flag_emits_pure_json(self):
        import json
        with mock.patch.object(cli.sferabit, "search",
                               return_value=_outcome(1)):
            code, out = self._run(["avvocati", "--foro", "milano",
                                   "Rossi", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["query"], "Rossi")

    def test_help_and_version_exit_zero(self):
        """`--help`/`--version` are successful invocations, not operational
        failures: they must not return the documented exit code 2."""
        for argv in (["--help"], ["--version"], ["-h"]):
            code, _ = self._run(argv)
            self.assertEqual(code, 0, f"{argv} returned {code}")

    def test_unknown_subcommand_exits_two(self):
        code, _ = self._run(["not-a-command"])
        self.assertEqual(code, 2)

    def test_no_arguments_exits_two(self):
        code, _ = self._run([])
        self.assertEqual(code, 2)

    def test_missing_positional_exits_two(self):
        code, _ = self._run(["avvocati", "--foro", "milano"])
        self.assertEqual(code, 2)

    def test_keyboard_interrupt_returns_130_silent_stdout(self):
        from unittest import mock as _mock
        err = io.StringIO()
        with _mock.patch.object(cli.iscrivo, "search",
                                side_effect=KeyboardInterrupt):
            with contextlib.redirect_stderr(err):
                code = cli.run(["avvocati", "--foro", "salerno", "Rossi"])
        self.assertEqual(code, 130)
        self.assertIn("interrupted", err.getvalue())

    def test_error_goes_to_stderr_not_stdout(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, out = self._run(["avvocati", "--foro", "NONEXISTENT", "Rossi"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")          # stdout stays clean
        self.assertIn("error:", err.getvalue())


class AgronomiCommandTest(unittest.TestCase):
    """The CONAF subcommand: argument wiring and its own refusals."""

    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.run(argv)
        return code, buf.getvalue()

    def test_dispatches_to_the_conaf_adapter_with_the_configured_endpoint(self):
        with mock.patch.object(cli.conaf, "search",
                               return_value=_outcome(2)) as mocked:
            code, out = self._run(["agronomi", "--cognome", "Rossi",
                                   "--ordine", "FI", "--limit", "7"])
        self.assertEqual(code, 0)
        self.assertIn("MATCH 0", out)
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["cognome"], "Rossi")
        self.assertEqual(kwargs["ordine"], "FI")
        self.assertEqual(kwargs["limit"], 7)
        self.assertEqual(kwargs["endpoint"], conaf.DEFAULT_ENDPOINT)
        self.assertEqual(kwargs["origin"], conaf.DEFAULT_ORIGIN)

    def test_zero_matches_exit_one(self):
        with mock.patch.object(cli.conaf, "search",
                               return_value=_outcome(0)):
            code, _ = self._run(["agronomi", "--cognome", "Rossi"])
        self.assertEqual(code, 1)

    def test_a_query_without_filters_exits_two_on_stderr(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, out = self._run(["agronomi"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("error:", err.getvalue())

    def test_a_bad_order_filter_exits_two(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = self._run(["agronomi", "--cognome", "Rossi",
                                 "--ordine", "FIRENZE"])
        self.assertEqual(code, 2)
        self.assertIn("province", err.getvalue())

    def test_json_output_is_pure(self):
        import json
        with mock.patch.object(cli.conaf, "search",
                               return_value=_outcome(1)):
            code, out = self._run(["agronomi", "--cognome", "Rossi", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["source"], "X")

    def test_help_lists_the_new_command(self):
        code, out = self._run(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("agronomi", out)


if __name__ == "__main__":
    unittest.main()
