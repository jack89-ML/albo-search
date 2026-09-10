# albo-search

[![test](https://github.com/jack89-ML/albo-search/actions/workflows/test.yml/badge.svg)](https://github.com/jack89-ML/albo-search/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/python-3.10–3.14-blue)](https://github.com/jack89-ML/albo-search/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![tests](https://img.shields.io/badge/tests-71%20passing-green)](tests)
[![coverage](https://img.shields.io/badge/coverage-66%25-green)](pyproject.toml)

A lightweight CLI tool to query official Italian public professional registers and public administration rosters.

Designed for automated compliance checks, OSINT investigations, and data aggregation. Supports standard POSIX exit codes and formats output as terminal tables, plain JSON, or CSV.

## Supported Registries

| Command | Register | Source Authority | Engine |
| :--- | :--- | :--- | :--- |
| `avvocati` | Consiglio dell'Ordine Avvocati (COA) | Sferabit / Iscrivo platforms | HTTP stdlib / Browser |
| `commercialisti` | Albo Unico Commercialisti | CNDCEC | Browser |
| `anagrafe` | Amministratori Locali | Ministero dell'Interno | Browser |
| `identita` | Elenco Nazionale Avvocati | Cassa Forense | Browser |

## Design Principles

- **POSIX Exit Codes:** Distinguishes verified absence from technical failures (`0` = Match found, `1` = Verified not found, `2` = Upstream error or network failure, `130` = Interrupted by user).
- **Minimal Footprint:** Core functionality relies entirely on the Python 3.10+ standard library. Dynamic JavaScript forms use an optional Playwright driver.
- **Composable:** Emits clean JSON to `stdout` with diagnostic errors routed exclusively to `stderr` for direct piping into `jq` or external pipelines.
- **Dead-man Switch:** a global `--timeout` (default 20s) bounds every upstream request; a stalled portal aborts with exit code `2`, never a hang.
- **Desktop User-Agent:** the stdlib HTTP client never sends the default `Python-urllib` header, which WAFs block on sight; it presents a standard desktop browser UA.

## Requirements

- Python 3.10 – 3.14.
- No runtime dependencies for the HTTP adapters.
- Optional: `playwright` (and a Chromium build) for the registries behind
  JavaScript forms.

## Installation

### Core (Standard Library only)

Supports direct HTTP adapters (e.g., Sferabit endpoints):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Full Browser Support (Optional)

Required for CNDCEC, Cassa Forense, and Iscrivo JSF forms:

```bash
pip install -e ".[browser]"
playwright install chromium
```

## Usage

```bash
# Direct HTTP query via Sferabit
albo-search avvocati --foro FIRENZE "Rossi"

# Pipe JSON directly to jq
albo-search avvocati --foro MILANO "Rossi" --json | jq '.results[0]'

# Filter by city and surname
albo-search commercialisti --cognome "Rossi" --ordine FIRENZE --limit 5

# Lookup office holders and stated professions
albo-search anagrafe --cognome "Rossi" --nome "Mario" --limit 3

# Cross-check identity
albo-search identita --cognome "Rossi" --ordine BOLOGNA

# Raise the global timeout for slow portals
albo-search avvocati --foro SALERNO "Rossi" --timeout 45
```

`albo` is registered as a shorthand alias for `albo-search`.

## Client behaviour

- **Idempotency aware**: only `GET` requests are retried. A POST to a stateful
  JSF form is never replayed — a silent second submission is worse than a
  failed one. Transient `403/429/503` responses are retried with jittered
  exponential backoff, honouring `Retry-After` when the server sends it.
- **Charset aware**: responses are decoded with the charset the server
  declares (`Content-Type`), then a UTF-8 → ISO-8859-1 → Windows-1252 chain.
  Italian portals still serve Latin-1: decoding those pages as UTF-8 mangles
  accented surnames.
- **Reactive waits**: each adapter waits for the results table or the portal's
  empty-state message, whichever comes first, instead of pausing for a fixed
  number of seconds per page.
- **Bounded**: responses larger than 25 MiB are refused, and a URL whose scheme
  is not `http(s)` is rejected before any connection (a `sources.json` cannot
  turn the client into a file reader).

## Exit Codes

The tool returns deterministic status codes suitable for shell scripts:

- `0`: Query successful, one or more records returned.
- `1`: Query successful, zero records found (confirmed negative lookup).
- `2`: Operational error (network timeout, invalid parameters, upstream interface failure).
- `130`: Interrupted by the user (SIGINT) — no traceback is printed.

## Configuration

Registry endpoints are defined in `src/albo_search/data/sources.json` and ship with the package — installed copies must never be edited. User overrides follow the XDG Base Directory specification and are merged over the bundled defaults automatically:

| Source | Location |
| :--- | :--- |
| Bundled defaults | `src/albo_search/data/sources.json` (in the package) |
| User override | `~/.config/albo-search/sources.json` (or `$XDG_CONFIG_HOME/albo-search/sources.json`) |
| Explicit | `$ALBO_SEARCH_CONFIG` environment variable or `--sources <path>` |

Example user override — add or replace individual bar councils without touching the package:

```json
{
  "lawyers": {
    "sferabit": [
      { "name": "FIRENZE", "id": 1047 }
    ],
    "iscrivo": [
      { "name": "SALERNO", "url": "https://iscrivo.dcssrl.it/ISCRIVO-ALBOONLINE/avvsalerno/avvocati" }
    ]
  }
}
```

Create it with:

```bash
mkdir -p ~/.config/albo-search
cp src/albo_search/data/sources.json ~/.config/albo-search/sources.json
# ... then edit the copy
```

## Development

```bash
git clone https://github.com/jack89-ML/albo-search
cd albo-search
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[browser]"
python -m unittest discover -s tests -v     # 71 tests, all offline
```

The suite uses stored HTML fixtures, so it never touches the upstream portals.
Release history lives in [CHANGELOG.md](CHANGELOG.md); the disclosure policy is
in [SECURITY.md](SECURITY.md).

## Related tools

- [`eml-forensics`](https://github.com/jack89-ML/eml-forensics) — offline
  e-discovery for `.eml` corpora: MIME parsing, attachment hashes, OCR.
- [`cleanrepo`](https://github.com/jack89-ML/cleanrepo) — pre-publish OPSEC
  scanner for secrets, private networks and local paths.

## Legal & Operational Notice

This tool performs read-only requests against officially public, publicly-indexed institutional endpoints. It stores no cached personal data, bypasses no authentication barriers, and requires no API keys. Users are solely responsible for ensuring their query frequency adheres to upstream server acceptable-use policies.

## License

MIT — see [LICENSE](LICENSE).
