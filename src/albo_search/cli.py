"""Command-line interface for albo-search."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from . import anagrafe, cassaforense, cndcec, config, iscrivo, sferabit
from .errors import RegistryError, exit_code
from .http import HttpClient
from .output import SearchOutcome, render_csv, render_json, render_table

EXIT_INTERRUPTED = 130  # 128 + SIGINT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="albo-search",
        description="Query Italian public professional registers.",
    )
    parser.add_argument("--version", action="version",
                        version=f"albo-search {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_law = sub.add_parser("avvocati", help="lawyers: COA bar registers")
    p_law.add_argument("--foro", required=True,
                       help="bar council name as configured in sources.json "
                            "(e.g. MILANO, FIRENZE, SALERNO)")
    p_law.add_argument("cognome", help="surname to search")
    _common(p_law)

    p_acc = sub.add_parser("commercialisti", help="accountants: CNDCEC register")
    p_acc.add_argument("--cognome", default="", help="surname to search")
    p_acc.add_argument("--cap", default="", help="postal code census")
    p_acc.add_argument("--ordine", default="", help="order name, e.g. Firenze")
    p_acc.add_argument("--sezione", default="", choices=["A", "B"],
                       help="register section")
    _common(p_acc)

    p_adm = sub.add_parser("anagrafe",
                           help="local administrators (Ministry of Interior)")
    p_adm.add_argument("--cognome", required=True)
    p_adm.add_argument("--nome", default="")
    p_adm.add_argument("--luogo", default="",
                       help="birthplace filter (uppercase works best)")
    _common(p_adm)

    p_id = sub.add_parser("identita",
                          help="lawyers national identity index (Cassa Forense)")
    p_id.add_argument("--cognome", required=True)
    p_id.add_argument("--nome", default="")
    p_id.add_argument("--ordine", default="", help="bar council name")
    _common(p_id)

    return parser


def _common(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--sources", default=None,
                           help="path to a local sources.json override")
    subparser.add_argument("--timeout", type=int, default=20,
                           help="global request timeout in seconds (default 20)")
    subparser.add_argument("--limit", type=int, default=25,
                           help="max rows to fetch/show (default 25)")
    fmt = subparser.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="JSON output (jq-friendly)")
    fmt.add_argument("--csv", action="store_true", help="CSV output")


def _render(outcome: SearchOutcome, args) -> str:
    if args.json:
        return render_json(outcome)
    if args.csv:
        return render_csv(outcome)
    return render_table(outcome)


def run(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit:
        return 2  # argparse usage/error already printed to stderr

    http = HttpClient(timeout=float(args.timeout))
    try:
        if args.command == "avvocati":
            cfg = config.resolve_sources(args.sources)
            scope = args.foro.upper()
            platform, bar = config.find_lawyer_bar(cfg, scope)
            if platform == "sferabit":
                outcome = sferabit.search(http, int(bar["id"]), args.cognome,
                                          limit=args.limit)
            else:
                outcome = iscrivo.search(bar["url"], args.cognome,
                                         limit=args.limit, timeout=args.timeout)
        elif args.command == "commercialisti":
            outcome = cndcec.search(cognome=args.cognome, cap=args.cap,
                                    order=args.ordine, section=args.sezione,
                                    timeout=args.timeout)
        elif args.command == "anagrafe":
            outcome = anagrafe.search(args.cognome, args.nome, args.luogo,
                                      detail_limit=args.limit,
                                      timeout=args.timeout)
        elif args.command == "identita":
            outcome = cassaforense.search(args.cognome, args.nome, args.ordine,
                                          limit=args.limit, timeout=args.timeout)
        else:  # pragma: no cover
            raise RegistryError(f"unknown command {args.command}")
    except KeyboardInterrupt:
        print("interrupted by user", file=sys.stderr)
        return EXIT_INTERRUPTED
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # unexpected upstream/browser failure
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(_render(outcome, args))  # stdout carries ONLY the formatted output
    return exit_code(True, outcome.found)


def main() -> None:
    try:
        sys.exit(run())
    except KeyboardInterrupt:  # pragma: no cover - safety net for SIGINT
        print("interrupted by user", file=sys.stderr)
        sys.exit(EXIT_INTERRUPTED)


if __name__ == "__main__":
    main()
