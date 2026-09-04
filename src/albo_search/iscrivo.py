"""Iscrivo bar register (COA on the Iscrivo/JSF platform).

The portal is a PrimeFaces application: the visible search input for the
name is ``form:j_idt35`` (the first text input on the page is the operator
combobox and must NOT be typed into). Runs in a real browser (optional
extra).
"""

from __future__ import annotations

import re

from .browser import new_page, playwright, settle
from .output import Record, SearchOutcome

NAME_FIELD = '[id="form:j_idt35"]'


def search(url: str, surname: str, limit: int = 25, timeout: float = 20.0) -> SearchOutcome:
    ms = max(5000, int(timeout * 1000))
    with playwright() as p:
        browser, page = new_page(p, timeout_ms=ms)
        try:
            page.goto(url, wait_until="networkidle", timeout=ms)
            settle(page)
            field = page.locator(NAME_FIELD)
            if field.count() == 0:
                raise RuntimeError(
                    "name field (form:j_idt35) not found — page layout may differ"
                )
            field.fill(surname)
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

            def _junk(text: str) -> bool:
                """True for header/container/pager rows that are not entries."""
                if ("Nominativo" in text or "Trovati" in text
                        or "Indirizzo" in text):
                    return True
                if re.fullmatch(r"p\s*\d*\s*p", text):
                    return True
                if len(text) > 400 or text.count("Avv.") > 1 or text.count("Dott.") > 1:
                    return True
                return False

            for _ in range(12):  # pagination safety cap
                rows = page.locator("table tr:has(td)")
                for index in range(rows.count()):
                    text = re.sub(r"\s+", " ", rows.nth(index).inner_text()).strip()
                    if not text or _junk(text) or not token.search(text):
                        continue
                    if text in seen:
                        continue
                    seen.add(text)
                    records.append(Record(source="ISCRIVO", scope=url, name=text))
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
                raise RuntimeError(
                    f"portal reported {total} matches but no rows parsed"
                )
            return SearchOutcome(query=surname, source="ISCRIVO", scope=url,
                                 records=records, total=total or len(records),
                                 verified_empty=False)
        finally:
            browser.close()
