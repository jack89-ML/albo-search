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
            settle(page, 4.0)
            page.wait_for_load_state("networkidle", timeout=ms)
            settle(page, 2.0)

            body_text = page.locator("body").inner_text()
            empty_hit = re.search(
                r"Nessun nominativo trovato|Nessun risultato", body_text, re.I
            )
            total_hit = re.search(r"Trovat[io]\s+(\d+)\s+nominativ", body_text, re.I)

            records: list[Record] = []
            seen: set[str] = set()
            token = re.compile(rf"\b{re.escape(surname)}\b", re.I)

            for _ in range(12):  # pagination safety cap
                rows = page.locator("table tr:has(td)")
                for index in range(rows.count()):
                    row = rows.nth(index)
                    cells = [_norm(cell) for cell in
                             row.locator("td").all_inner_texts()]
                    cells = [c for c in cells if c]
                    joined = " ".join(cells)
                    if _junk(joined, len(cells)) or not token.search(joined):
                        continue
                    if joined in seen:
                        continue
                    seen.add(joined)
                    name_cell = next((c for c in cells if token.search(c)),
                                     cells[0] if cells else joined)
                    details = " · ".join(
                        c for c in cells if c != name_cell)
                    extra = {"details": details} if details else {}
                    records.append(Record(source="ISCRIVO", scope=url,
                                          name=name_cell, extra=extra))
                    if len(records) >= limit:
                        break
                if len(records) >= limit:
                    break
                nxt = page.locator(".ui-paginator-next:not(.ui-state-disabled)")
                if nxt.count() == 0:
                    break
                try:
                    nxt.first.click(timeout=4000)
                    settle(page, 2.0)
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
