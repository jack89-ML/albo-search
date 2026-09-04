"""Sferabit bar register (COA on the Sferabit platform).

Pure HTTP: GET the public index, then POST to ``elencoAlboOnline.php`` with
the filter parameters in the query string (the JavaScript form builds the
link this way; a bare POST without them returns the unfiltered list).
"""

from __future__ import annotations

import re
import urllib.parse

from .errors import ParseFailure
from .http import HttpClient
from .output import Record, SearchOutcome

BASE = "https://pubblico.sferabit.com/servizi/alboonline"

_SUMMARY = re.compile(r"(\d+)\s*[-–]\s*(\d+)\s+di\s+(\d+)\s+nominativi", re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def _query_string(surname: str) -> str:
    params = {
        "nRicerche": "1",
        "filtroRagioneSociale": surname,
        "filtroIdTipiAnagraficheCategorie": "",
        "filtroIdImpoSpecializzazioni": "",
        "filtroIdImpoPatrociniMaterie": "",
        "filtroIndirizzo": "",
        "filtroCassazionista": "",
        "filtroPatrocini": "",
        "filtroDifese": "",
        "filtroCap": "",
        "filtroCitta": "",
        "filtroProv": "",
        "partenza": "0",
        "maxRecords": "0",
        "elenco": "albo",
    }
    return urllib.parse.urlencode(params)


def _clean(text: str) -> str:
    return _SPACE.sub(" ", _TAG.sub(" ", text)).strip()


def _find_total(html: str) -> int | None:
    match = _SUMMARY.search(html)
    return int(match.group(3)) if match else None


def search(client: HttpClient, bar_id: int, surname: str,
           limit: int = 25) -> SearchOutcome:
    index_url = f"{BASE}/index.php?id={bar_id}"
    client.get(index_url)  # seed cookies
    response = client.post_raw(
        f"{BASE}/elencoAlboOnline.php?{_query_string(surname)}",
        "",
        referer=index_url,
    )
    html = response.decode("utf-8", errors="replace")
    total = _find_total(html)

    records: list[Record] = []
    seen: set[str] = set()
    token = re.compile(rf"\b{re.escape(surname)}\b", re.I)
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S):
        cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        cells = [c for c in cells if c and "&nbsp;" not in c]
        if not cells:
            continue
        joined = " ".join(cells)
        if _SUMMARY.search(joined) or re.search(r"(Inizio|Avanti|Indietro|Fine)", joined):
            continue
        if not token.search(joined):
            continue
        name_cell = next((c for c in cells if token.search(c)), cells[0])
        if name_cell in seen:
            continue
        seen.add(name_cell)
        category = cells[1] if len(cells) > 1 else ""
        if category.lower() in ("apri", "aperto", ""):
            category = cells[2] if len(cells) > 2 else ""
        extra = {} if not category or category == name_cell else {"category": category}
        records.append(Record(source="SFERABIT", scope=str(bar_id),
                              name=name_cell, extra=extra))
        if len(records) >= limit:
            break

    if not records and total:
        raise ParseFailure(
            f"upstream reported {total} matches but no rows could be parsed "
            f"(bar id {bar_id}); page structure may have changed"
        )
    if records:
        return SearchOutcome(query=surname, source="SFERABIT", scope=str(bar_id),
                             records=records[:limit], total=total,
                             verified_empty=False)
    return SearchOutcome(query=surname, source="SFERABIT", scope=str(bar_id),
                         records=[], total=total or 0,
                         note="0 matches" if total == 0 else "",
                         verified_empty=total == 0)
