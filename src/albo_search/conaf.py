"""CONAF national register of agronomists and foresters (Albo Unico).

The register is served by a public JSON query API behind the SIDAF portal:
a read-only POST, no authentication and no browser required, so this is a
core (stdlib-only) adapter like the Sferabit one. The portal host itself
answers the call with HTTP 405, which is why the API host is contacted
directly.

Parsing lives in a pure function (:func:`parse_response`) so it stays
unit-testable offline. A response that cannot be understood raises instead of
being reported as an empty result: on a register lookup a silent "not found"
is the one wrong answer that matters.
"""

from __future__ import annotations

import json
import re

from .errors import ParseFailure, RegistryError
from .http import HttpClient
from .output import Record, SearchOutcome

DEFAULT_ENDPOINT = "https://api.conaf.it/msga/anagrafe/ricercaIscrittiAlbo"
DEFAULT_ORIGIN = "https://www.sidafonline.it"

# Every filter key is always sent, empty when unused: this endpoint treats a
# missing key differently from an empty one.
FIELDS = (
    "nome",
    "cognome",
    "cf",
    "ordineTerritorialeCompetente",
    "numeroIscrizioneOrdine",
)

# Two-letter province code. Anything else (a city name, a region, a typo) is
# refused before the request: this endpoint drops an unrecognised order filter
# and would answer with the whole national register.
PROVINCE = re.compile(r"^[A-Z]{2}$")

_SNIPPET = 120


def build_query(cognome: str = "", nome: str = "", cf: str = "",
                ordine: str = "", numero: str = "") -> dict[str, str]:
    """Assemble the request body, normalized, with no filter key missing.

    Surnames are stored uppercase in the register, so the accepted spelling is
    the uppercase one; :func:`search` retries with the input as typed when the
    normalized query finds nothing.
    """
    return {
        "nome": nome.strip().upper(),
        "cognome": cognome.strip().upper(),
        "cf": cf.strip().upper(),
        "ordineTerritorialeCompetente": ordine.strip().upper(),
        "numeroIscrizioneOrdine": numero.strip(),
    }


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _status(row: dict) -> str:
    """Disciplinary state, reported only when the register flags one."""
    if row.get("radiato"):
        return "removed"
    if row.get("sospeso"):
        return "suspended"
    return ""


def _place(*parts) -> str:
    return " ".join(text for text in (_text(p) for p in parts) if text)


def parse_response(raw: str, surname: str = "",
                   limit: int = 50) -> tuple[list[Record], int]:
    """Turn an API response into records.

    Returns ``(records, total_matches)``, where ``total_matches`` is what the
    register itself reports, before the local token filter and the ``limit``:
    callers need it to tell a verified negative (``0``) apart from an answer
    they failed to understand.
    """
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        snippet = " ".join(str(raw).split())[:_SNIPPET]
        raise ParseFailure(
            f"register returned a non-JSON response ({snippet!r}): the endpoint "
            "may have changed or be serving an error page"
        ) from exc
    if not isinstance(payload, dict):
        raise ParseFailure("register returned JSON that is not an object")
    if payload.get("error"):
        raise RegistryError(f"register reported an error: {payload['error']}")
    if "returnedObject" not in payload:
        raise ParseFailure(
            "register response carries no 'returnedObject' field "
            f"(fields: {sorted(payload)})"
        )
    rows = payload.get("returnedObject") or []
    if not isinstance(rows, list):
        raise ParseFailure("register 'returnedObject' is not a list")
    entries = [row for row in rows if isinstance(row, dict)]

    wanted = re.compile(rf"\b{re.escape(surname)}\b", re.I) if surname else None
    records: list[Record] = []
    for row in entries:
        name = f"{_text(row.get('cognome'))} {_text(row.get('nome'))}".strip()
        if not name or (wanted and not wanted.search(name)):
            continue
        order = _text(row.get("ordineTerritorialeCompetente"))
        extra = {
            "section": _text(row.get("sezioneRichiesta")),
            "title": _text(row.get("titoloRichiesto")),
            "order": order,
            "number": _text(row.get("numeroIscrizioneOrdine")),
            "registered": _text(row.get("dataIscrizioneOrdine")),
            "birth": _place(row.get("dataNascita"), row.get("cittaNascita")),
            "residence": _place(row.get("indirizzoResidenza"),
                                row.get("capResidenza")),
            "pec": _text(row.get("pec")),
            "status": _status(row),
            "public_employee": ("yes" if row.get(
                "flagDipendentePubblicaAmministrazione") else ""),
            "subject_id": _text(row.get("idSoggetto")),
        }
        records.append(Record(source="CONAF", scope=order or "IT",
                              name=name, extra=extra))
        if len(records) >= limit:
            break
    return records, len(entries)


def _validate(cognome: str, nome: str, cf: str, numero: str,
              ordine: str) -> None:
    """Refuse a query that cannot identify anyone, before any request."""
    if not any((cognome.strip(), nome.strip(), cf.strip(), numero.strip())):
        raise ValueError(
            "provide at least one of --nome, --cognome, --cf, --numero")
    if ordine.strip() and not PROVINCE.match(ordine.strip().upper()):
        raise ValueError(
            "ordine must be a two-letter province code (e.g. FI): an "
            "unrecognised filter is ignored upstream and would return the "
            "whole register")


def _label(body: dict[str, str]) -> str:
    if body["cf"]:
        return body["cf"]
    name = f"{body['nome']} {body['cognome']}".strip()
    if name:
        return name
    return f"n. {body['numeroIscrizioneOrdine']} {body['ordineTerritorialeCompetente']}".strip()


def _query(client: HttpClient, endpoint: str, origin: str, body: dict[str, str],
           surname: str, limit: int) -> tuple[list[Record], int]:
    raw, _charset = client.post_json_text(endpoint, body,
                                          headers={"Origin": origin},
                                          idempotent=True)
    return parse_response(raw, surname=surname, limit=limit)


def search(client: HttpClient, cognome: str = "", nome: str = "", cf: str = "",
           ordine: str = "", numero: str = "", limit: int = 25,
           endpoint: str = DEFAULT_ENDPOINT,
           origin: str = DEFAULT_ORIGIN) -> SearchOutcome:
    _validate(cognome, nome, cf, numero, ordine)
    body = build_query(cognome=cognome, nome=nome, cf=cf, ordine=ordine,
                       numero=numero)
    as_typed = {"nome": nome.strip(), "cognome": cognome.strip(),
                "cf": cf.strip(),
                "ordineTerritorialeCompetente": ordine.strip(),
                "numeroIscrizioneOrdine": numero.strip()}
    # Second chance with the spelling exactly as typed, in case the register
    # is case sensitive: only a query that normalization actually changed is
    # worth repeating, and only after the normalized one found nothing.
    attempts = [body] + ([as_typed] if as_typed != body else [])

    records: list[Record] = []
    total = 0
    for attempt in attempts:
        records, total = _query(client, endpoint, origin, attempt,
                                surname=attempt["cognome"], limit=limit)
        if total:
            break

    scope = body["ordineTerritorialeCompetente"] or "IT"
    label = _label(body)
    if total and not records:
        raise ParseFailure(
            f"register reported {total} matches for '{label}' but none could "
            "be read: the response layout may have changed")
    if not total:
        return SearchOutcome(query=label, source="CONAF", scope=scope,
                             records=[], total=0,
                             note="no entry in the national register for this "
                                  "query",
                             verified_empty=True)
    return SearchOutcome(query=label, source="CONAF", scope=scope,
                         records=records, total=total, verified_empty=False)
