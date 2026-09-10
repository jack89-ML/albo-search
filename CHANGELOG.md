# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-09-10

### Added

- Charset-aware decoding: responses use the charset declared in
  `Content-Type`, then a UTF-8 → ISO-8859-1 → Windows-1252 chain. The client
  used to hand raw bytes to the adapters, which decoded UTF-8 with
  `errors="replace"`: accented surnames from Latin-1 portals came out mangled.
- New client API: `get_text` / `post_text` / `post_raw_text` return the decoded
  body together with the charset actually used.
- Reactive waits (`wait_for_results`, `wait_for_widgets`) in the Iscrivo,
  Cassa Forense and CNDCEC adapters: the fixed 2–5 s pauses after every
  interaction are gone (~8.5 s per Iscrivo query), replaced by a wait for the
  results table or the portal's empty-state message.
- Pure, offline-testable parsing extracted from the browser flows:
  `iscrivo.parse_rows`, `anagrafe.select_hits`, `anagrafe.build_record`.
  Anagrafe coverage went from 12% to 42%, Iscrivo from 17% to 55%.
- Lint (ruff) and coverage gates in CI (66% measured, fails under 60%).

### Fixed

- **JSON output could lose the record name**: `{"name": r.name, **r.extra}`
  let a source-specific extra column called `name` overwrite it.
- **Retries on non-idempotent requests**: a transient `503` on the POST of a
  stateful JSF form was retried up to three times, i.e. the form could be
  submitted twice. Only `GET` is retried now.
- `429`/`503` honour `Retry-After`; the backoff is jittered instead of fixed.
- A response without a size limit could exhaust memory (now capped at 25 MiB)
  and a non-`http(s)` URL is refused before any connection.
- A typo in `ALBO_SEARCH_CONFIG` / `ALBO_SOURCES` silently fell back to the
  bundled defaults instead of failing loudly.


## [0.1.0] - 2026-09-04

### Added

- CLI `albo-search` (alias `albo`) with four subcommands: `avvocati`
  (Sferabit / Iscrivo), `commercialisti` (CNDCEC), `anagrafe` (Ministry of the
  Interior), `identita` (Cassa Forense).
- Output as terminal table, JSON or CSV; deterministic POSIX exit codes
  (`0` match, `1` verified absence, `2` upstream error, `130` interrupt).
- Per-registry adapter layer with a stdlib HTTP client (desktop User-Agent,
  no `Python-urllib` header) and an optional Playwright driver for
  JSF/PrimeFaces forms.
- Global `--timeout` bound on every upstream request.
- XDG-compliant user configuration merged over the bundled `sources.json`
  (`~/.config/albo-search/sources.json`, `$ALBO_SEARCH_CONFIG`, `--sources`).
- Unit test suite with offline HTML fixtures for the Sferabit and Cassa
  Forense parsers.

### Changed

- Hardened the Iscrivo parser and its selectors.
- Replaced fixed sleeps with reactive waits in the `anagrafe` adapter and
  structured parsing of the returned roster.
- Decoupled bar-council resolution from the query flow; table output hygiene
  (column widths, empty-result rendering).

[Unreleased]: https://github.com/jack89-ML/albo-search/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jack89-ML/albo-search/releases/tag/v0.1.0
