"""Ministry of Interior registry of local administrators.

Search by surname (optionally name / birthplace), list matching rows, then
open the first rows' detail cards to read the declared profession and
education. Runs in a real browser.

Rows are parsed from their own DOM element (cells + link on the same <tr>),
so no index alignment between separate locator queries is needed. Waits are
reactive (selector / body-state) instead of fixed sleeps; Playwright
navigation failures are wrapped into :class:`RegistryError` so the CLI keeps
its POSIX exit-code contract.
"""

from __future__ import annotations

import re

from .browser import new_page, playwright, settle
from .errors import ParseFailure, RegistryError
from .output import Record, SearchOutcome

URL = "https://amministratori.interno.gov.it/index.php?page=CognomeNome"
ROW_LINK = 'tr:has(a[href*="InfoAnagrafica"])'
EMPTY_MARKERS = (
    "nessun risultato", "nessun nominativo", "non è stato trovato",
    "non e' stato trovato", "non trovato", "nessuna corrispondenza",
    "non è presente alcun dato",
)
_SPACE = re.compile(r"\s+")

_HEADER_ALIASES = {
    "cognome": "cognome", "nome": "nome", "sesso": "sesso",
    "data di nascita": "data_nascita", "data": "data_nascita",
    "nascita": "data_nascita",
    "luogo di nascita": "luogo", "luogo": "luogo",
    "ente": "ente", "carica": "carica", "incarico": "carica",
}


def _norm(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def _field_map(header_cells: list[str]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for index, cell in enumerate(header_cells):
        key = _HEADER_ALIASES.get(cell.lower())
        if key:
            mapping[index] = key
    return mapping


def _extract_field(body: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*:\s*([^\n]+)", body)
    return _norm(match.group(1)) if match else ""


def search(cognome: str, nome: str = "", luogo: str = "",
           detail_limit: int = 5, timeout: float = 20.0) -> SearchOutcome:
    ms = max(5000, int(timeout * 1000))
    with playwright() as p:
        try:
            from playwright.sync_api import Error as PlaywrightError
        except ImportError:  # pragma: no cover - guarded by playwright()
            PlaywrightError = Exception  # type: ignore[assignment]
        browser, page = new_page(p, timeout_ms=ms)
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=ms)
            page.locator('input[name="cognome"]').first.fill(cognome)
            if nome:
                page.locator('input[name="nome"]').first.fill(nome)
            page.locator('button:has-text("CONFERMA"), input[type="submit"]').first.click()

            # Reactive wait: result rows with a detail link, or an empty-state
            # message — whatever the portal shows first.
            rows_seen = False
            try:
                page.wait_for_selector(ROW_LINK, timeout=max(ms // 3, 6000))
                rows_seen = True
            except PlaywrightError:
                pass
            if not rows_seen:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=ms)
                except PlaywrightError:
                    raise RegistryError("anagrafe portal did not respond in time")
                settle(page, 1.0)
            body_text = page.locator("body").inner_text().lower()

            token = re.compile(rf"\b{re.escape(cognome)}\b", re.I)
            hits: list[dict] = []
            for row in page.locator("table tr:has(td)").all():
                cells = [_norm(c) for c in row.locator("td").all_inner_texts()]
                cells = [c for c in cells if c]
                if not cells:
                    continue
                joined = " ".join(cells)
                if not token.search(joined):
                    continue
                if luogo and luogo.upper() not in joined.upper():
                    continue
                # Prefer the record link (detail page), else any link on the
                # same DOM row — same element, so indexes cannot drift.
                detail = row.locator('a[href*="InfoAnagrafica"]').first
                if detail.count() == 0:
                    detail = row.locator("a[href]").first
                href = detail.get_attribute("href") if detail.count() else None
                hits.append({"cells": cells, "href": href})

            # Zero rows: only a confirmed "no results" state may be reported
            # as a verified negative — anything else is a parse failure.
            if not hits:
                if any(marker in body_text for marker in EMPTY_MARKERS):
                    return SearchOutcome(query=cognome, source="ANAGRAFE",
                                         scope="IT", records=[], total=0,
                                         verified_empty=True,
                                         note="no matches (portal message)")
                raise ParseFailure(
                    "anagrafe returned no rows and no explicit empty message — "
                    "page structure may have changed"
                )

            # Column layout: try the header row of the results table first,
            # fall back to a positional assumption (cognome, nome, ...).
            mapping: dict[int, str] = {}
            for header_row in page.locator("table tr:has(td, th)").all():
                header_cells = [_norm(c) for c in
                                header_row.locator("td, th").all_inner_texts()]
                header_cells = [c for c in header_cells if c]
                if any("cognome" in c.lower() for c in header_cells):
                    mapping = _field_map(header_cells)
                    break
                if header_row.locator("th").count() > 0:
                    mapping = _field_map(header_cells)
                    break

            records: list[Record] = []
            for hit in hits[:detail_limit]:
                cells = hit["cells"]
                extra: dict[str, str] = {}
                if mapping:
                    for index, field in mapping.items():
                        if index < len(cells) and cells[index]:
                            extra[field] = cells[index]
                    name = f"{extra.get('cognome', '')} {extra.get('nome', '')}".strip()
                    if not name:
                        name = " ".join(cells)
                elif len(cells) >= 5:
                    extra = {"cognome": cells[0], "nome": cells[1],
                             "sesso": cells[2], "data_nascita": cells[3],
                             "luogo": cells[4]}
                    name = f"{cells[0]} {cells[1]}".strip()
                else:
                    name = cells[0]
                if hit.get("href"):
                    extra["row"] = " ".join(cells)
                    url = hit["href"] if hit["href"].startswith("http") else \
                        "https://amministratori.interno.gov.it/" + \
                        hit["href"].lstrip("./")
                    try:
                        page.goto(url, wait_until="domcontentloaded",
                                  timeout=ms)
                    except PlaywrightError:
                        raise RegistryError(
                            "anagrafe detail page did not respond in time")
                    settle(page, 1.0)
                    body = page.locator("body").inner_text()
                    profession = _extract_field(body, "Professione")
                    education = _extract_field(body, "Titolo di studio")
                    if profession:
                        extra["professione"] = profession
                    if education:
                        extra["titolo_studio"] = education
                records.append(Record(source="ANAGRAFE", scope="IT",
                                      name=name, extra=extra))
            return SearchOutcome(query=cognome, source="ANAGRAFE", scope="IT",
                                 records=records, total=len(hits),
                                 verified_empty=False)
        except RegistryError:
            raise
        except PlaywrightError as exc:
            raise RegistryError(f"anagrafe portal error: {exc}") from exc
        finally:
            browser.close()
