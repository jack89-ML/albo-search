# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
