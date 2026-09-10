"""Iscrivo bar register (COA on the Iscrivo/JSF platform).

The portal is a PrimeFaces application: the visible search input for the
name is ``form:j_idt35`` (the first text input on the page is the operator
combobox and must NOT be typed into). Runs in a real browser (optional
extra).
"""

from __future__ import annotations

import re

from .browser import new_page, playwright, settle
from .errors import ParseFailure
from .output import Record, SearchOutcome

# Primary selector plus resilient fallbacks for the incremental JSF id.
NAME_FIELD = ('input[id="form:j_idt35"], '
              'input[id*="form:"][id*="nominativo" i], '
              'input[id*="form:"][id*="cognome" i]')

_SPACE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def _junk(joined: str, cell_count: int) -> bool:
    """True for header/container/pager rows that are not entries."""
    if "Nominativo" in joined or "Indirizzo" in joined or "Trovati" in joined:
        return True
    if re.fullmatch(r"p\s*\d*\s*p", joined):
        return True
    if len(joined) > 400 or joined.count("Avv.") > 1 or joined.count("Dott.") > 1:
        return True
    return cell_count == 0


def parse_rows(rows: list[list[str]], surname: str, scope: str = "",
               limit: int = 25) -> list[Record]:
    """Portal rows (one list of cell texts each) to records. Pure, offline.

    Keeping the decision logic out of the browser flow is what makes it
    testable: the row filters, the name-cell choice ``\u2026`` and the details
    assembly are the parts that actually break when the portal changes.
    """
    token = re.compile(rf"\b{re.escape(surname)}\b", re.I)
    records: list[Record] = []
    seen: set[str] = set()
    for cells in rows:
        cells = [_norm(cell) for cell in cells if cell and cell.strip()]
        if not cells:
            continue
        joined = " ".join(cells)
        if _junk(joined, len(cells)) or not token.search(joined):
            continue
        if joined in seen:
            continue
        seen.add(joined)
        name_cell = next((c for c in cells if token.search(c)), cells[0])
        details = " · ".join(c for c in cells if c != name_cell)
        extra = {"details": details} if details else {}
        records.append(Record(source="ISCRIVO", scope=scope, name=name_cell,
                              extra=extra))
        if len(records) >= limit:
            break
    return records


# Reactive wait: the results table or the portal's empty-state message,
# whichever appears first. Replaces a fixed ~8.5s of sleeps per query.
_RESULTS_READY_JS = r"""() => {
  const text = document.body ? document.body.innerText : '';
  if (/Nessun nominativo|Nessun risultato/i.test(text)) return true;
  if (/Trovat[io]\s+\d+\s+nominativ/i.test(text)) return true;
  return document.querySelectorAll('table tr').length > 3;
}"""


def wait_for_results(page, timeout_ms: int) -> None:
    """Block until the portal has rendered results (or the wait expires)."""
    wait = getattr(page, "wait_for_function", None)
    if wait is None:                      # pragma: no cover - defensive
        return
    try:
        wait(_RESULTS_READY_JS, timeout=max(2000, timeout_ms // 3))
    except Exception:
        pass                              # the parse step reports the outcome


def search(url: str, surname: str, limit: int = 25,
           timeout: int = 25) -> SearchOutcome:
    ms = max(5000, timeout * 1000)
    with playwright() as p:
        browser, page = new_page(p, timeout_ms=ms)
        try:
            page.goto(url, wait_until="networkidle", timeout=ms)
            settle(page)
            field = page.locator(NAME_FIELD)
            if field.count() == 0:
                raise ParseFailure(
                    "name field not found (tried form:j_idt35 and fallbacks) — "
                    "page layout may differ"
                )
            field.first.fill(surname)
            page.locator('button:has-text("Cerca")').first.click()
            wait_for_results(page, ms)

            body_text = page.locator("body").inner_text()
            empty_hit = re.search(
                r"Nessun nominativo trovato|Nessun risultato", body_text, re.I
            )
            total_hit = re.search(r"Trovat[io]\s+(\d+)\s+nominativ", body_text, re.I)

            records: list[Record] = []
            for _ in range(12):  # pagination safety cap
                rows = page.locator("table tr:has(td)")
                page_rows = [row.locator("td").all_inner_texts()
                             for row in (rows.nth(index)
                                         for index in range(rows.count()))]
                records = parse_rows(page_rows, surname, scope=url, limit=limit)
                if len(records) >= limit:
                    break
                nxt = page.locator(".ui-paginator-next:not(.ui-state-disabled)")
                if nxt.count() == 0:
                    break
                try:
                    nxt.first.click(timeout=4000)
                    wait_for_results(page, ms)
                except Exception:
                    break

            total = int(total_hit.group(1)) if total_hit else None
            if empty_hit:
                return SearchOutcome(query=surname, source="ISCRIVO", scope=url,
                                     records=[], total=0, verified_empty=True,
                                     note="no results (portal message)")
            if not records and total:
                raise ParseFailure(
                    f"portal reported {total} matches but no rows parsed"
                )
            return SearchOutcome(query=surname, source="ISCRIVO", scope=url,
                                 records=records, total=total or len(records),
                                 verified_empty=False)
        finally:
            browser.close()
