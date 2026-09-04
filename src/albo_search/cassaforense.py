"""Cassa Forense national lawyers index (identity check).

The search page posts the ``ricElAvv`` form and renders the outcome into a
results area; the underlying AJAX endpoint needs a live session, so the
search runs in a real browser (optional extra). Parsing lives in a pure
function so it stays unit-testable offline.
"""

from __future__ import annotations

import re

from .browser import new_page, playwright, settle
from .errors import ParseFailure
from .output import Record, SearchOutcome

LANDING = ("https://servizi.cassaforense.it/CFor/ElencoNazionaleAvvocati/"
           "elenconazionaleavvocati_pg.cfm")

_SPACE = re.compile(r"\s+")
_EMPTY = re.compile(r"non ha prodotto risultati|nessun risultato", re.I)
_HEADER = re.compile(
    r"^\s*(cognome\s+e\s+nome|luogo\s+nascita|data\s+nascita|ordine)\s*$", re.I
)


def parse_fragment(html: str, surname: str, limit: int = 50):
    """Pure parser over the results HTML. Returns (records, empty_message).

    Handles two layouts: an HTML table of rows, or the textual record layout
    used by the live portal (". NAME / Luogo di nascita : X / ...").
    """
    token = re.compile(rf"\b{re.escape(surname)}\b", re.I)
    records: list[Record] = []
    empty_msg = ""
    text = _SPACE.sub(" ", re.sub(r"<[^>]+>", " ", html))
    if _EMPTY.search(text):
        empty_msg = "no results (portal message)"

    table_rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S)
    if table_rows:
        for row in table_rows:
            cells = [_SPACE.sub(" ", re.sub(r"<[^>]+>", " ", c)).strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
            cells = [c for c in cells if c]
            if not cells or not token.search(" ".join(cells)):
                continue
            if _HEADER.match(cells[0]):
                continue
            name_cell = next((c for c in cells if token.search(c)), cells[0])
            extra = {"details": " · ".join(cells[1:])} if len(cells) > 1 else {}
            records.append(Record(source="CASSA_FORENSE", scope="IT",
                                  name=name_cell, extra=extra))
            if len(records) >= limit:
                break
        return records, empty_msg

    # Textual layout: ". NAME Luogo di nascita : X Data di nascita : Y
    # Consiglio dell'Ordine di Z"
    block = re.compile(
        r"\.\s*([A-ZÀ-Ù][A-ZÀ-Ù\'’ .-]{1,80}?)"
        r"\s*Luogo di nascita\s*:\s*([^:]{2,60}?)\s*"
        r"Data di nascita\s*:\s*([^:]{2,40}?)\s*"
        r"Consiglio dell[\x27’]\s*Ordine di\s*([^:]{2,60}?)(?=\s*Record|\s*\.\s*[A-ZÀ-Ù]|\Z)",
        re.I | re.S,
    )
    normalized = re.sub(r"\s*\n\s*", " ", text)
    for match in block.finditer(normalized):
        name, place, birth, order = (g.strip() for g in match.groups())
        if not token.search(name):
            continue
        name = name.rstrip(".").strip()
        extra = {"place": place, "birth": birth, "order": order}
        records.append(Record(source="CASSA_FORENSE", scope="IT",
                              name=name, extra=extra))
        if len(records) >= limit:
            break
    return records, empty_msg


def search(surname: str, name: str = "", order: str = "",
           limit: int = 25, timeout: float = 20.0) -> SearchOutcome:
    ms = max(5000, int(timeout * 1000))
    with playwright() as p:
        browser, page = new_page(p, timeout_ms=ms)
        try:
            page.goto(LANDING, wait_until="domcontentloaded", timeout=ms)
            settle(page, 3.0)
            field = page.locator('input[name="cognome"]')
            if field.count() == 0:
                raise ParseFailure("Cassa Forense search form not found")
            field.fill(surname)
            if name:
                page.locator('input[name="nome"]').fill(name)
            if order:
                page.locator('select[name="Ordine"]').select_option(
                    label=order)
            page.locator("#btncerca, button:has-text('Cerca'), input[type='submit']").first.click()
            settle(page, 5.0)
            html = page.content()
            records, empty_msg = parse_fragment(html, surname, limit=limit)
            if empty_msg:
                return SearchOutcome(query=surname, source="CASSA_FORENSE",
                                     scope="IT", records=[], total=0,
                                     note=empty_msg, verified_empty=True)
            if not records:
                raise ParseFailure(
                    "Cassa Forense returned no parseable rows and no explicit "
                    "empty message — page structure may have changed"
                )
            return SearchOutcome(query=surname, source="CASSA_FORENSE",
                                 scope="IT", records=records,
                                 verified_empty=False)
        finally:
            browser.close()
