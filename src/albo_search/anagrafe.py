"""Ministry of Interior registry of local administrators.

Search by surname (optionally name / birthplace), list matching rows, then
open the first rows' detail cards to read declared profession and offices.
Runs in a real browser.
"""

from __future__ import annotations

import re

from .browser import new_page, playwright, settle
from .output import Record, SearchOutcome

URL = "https://amministratori.interno.gov.it/index.php?page=CognomeNome"
_SPACE = re.compile(r"\s+")


def _row_text(page) -> list[str]:
    rows = []
    for index in range(page.locator("tr").count()):
        text = _SPACE.sub(" ", page.locator("tr").nth(index).inner_text()).strip()
        if text:
            rows.append(text)
    return rows


def search(cognome: str, nome: str = "", luogo: str = "",
           detail_limit: int = 5, timeout: float = 20.0) -> SearchOutcome:
    ms = max(5000, int(timeout * 1000))
    with playwright() as p:
        browser, page = new_page(p, timeout_ms=ms)
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=ms)
            settle(page, 3.0)
            page.fill('input[name="cognome"]', cognome)
            if nome:
                page.fill('input[name="nome"]', nome)
            page.locator('button:has-text("CONFERMA"), input[type="submit"]').first.click()
            settle(page, 6.0)
            page.wait_for_load_state("networkidle", timeout=ms)
            settle(page, 2.0)

            token = re.compile(rf"\b{re.escape(cognome)}\b", re.I)
            hits = []
            rows = _row_text(page)
            for index, text in enumerate(rows):
                if not token.search(text) and not text.upper().startswith(cognome.upper()):
                    continue
                if luogo and luogo.upper() not in text.upper():
                    continue
                link = page.locator("tr").nth(index).locator("a").first
                href = link.get_attribute("href") if link.count() else None
                hits.append({"row": text, "href": href})

            if not hits:
                return SearchOutcome(query=cognome, source="ANAGRAFE", scope="IT",
                                     records=[], total=0, verified_empty=True,
                                     note="no matches on the first result page")

            records: list[Record] = []
            for hit in hits[:detail_limit]:
                extra = {"row": hit["row"]}
                if hit.get("href"):
                    url = hit["href"] if hit["href"].startswith("http") else \
                        "https://amministratori.interno.gov.it/" + hit["href"].lstrip("./")
                    page.goto(url, wait_until="domcontentloaded", timeout=ms)
                    settle(page, 3.0)
                    body = _SPACE.sub(" ", page.locator("body").inner_text())
                    marker = body.find("Cognome e Nome")
                    extra["detail"] = (body[marker:marker + 2400] if marker >= 0
                                       else body[-2000:])
                records.append(Record(source="ANAGRAFE", scope="IT",
                                      name=hit["row"], extra=extra))
            return SearchOutcome(query=cognome, source="ANAGRAFE", scope="IT",
                                 records=records, total=len(hits),
                                 verified_empty=False)
        finally:
            browser.close()
