"""CNDCEC national register of certified accountants.

Portal: ricerca.commercialisti.it (Kendo UI). Filters are set through the
page widgets, then the result list is read straight from the Kendo
dataSource. Requires the browser extra.
"""

from __future__ import annotations

import time

from .browser import new_page, playwright, settle
from .output import Record, SearchOutcome

BASE = "https://ricerca.commercialisti.it"


def _set_dropdown(page, selector: str, target: str) -> str:
    """Select an option in a kendoDropDownList whose Description contains target."""
    return page.evaluate(
        """(args) => {
          const [sel, target] = args;
          const w = $(sel).data('kendoDropDownList');
          if (!w) return 'no-widget';
          w.dataSource.read();
          return new Promise((resolve) => {
            w.dataSource.bind('change', function once() {
              w.dataSource.unbind('change', once);
              const ds = w.dataSource.data();
              let idx = -1;
              for (let i = 0; i < ds.length; i++) {
                if (String(ds[i].Description).toLowerCase().includes(target.toLowerCase())) {
                  idx = i; break;
                }
              }
              if (idx >= 0) { w.select(idx); w.trigger('change'); resolve('set:' + ds[idx].Description); }
              else resolve('not-found');
            });
          });
        }""",
        [selector, target],
    )


def _dump(page):
    return page.evaluate(
        """() => {
          const lv = $('#listIscritti').data('kendoListView');
          if (!lv) return {n: 0, rows: []};
          const ds = lv.dataSource;
          return {
            n: (ds.data() || []).length,
            rows: (ds.data() || []).map(x => ({
              cognome: x.Cognome || '', nome: x.Nome || '',
              birth: (x.ComuneNascita || '') + ' ' + (x.DataNascita || ''),
              office: (x.Studio || '').replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ').trim(),
              suspended: !!x.Sospeso, removed: !!x.Radiato,
            }))
          };
        }"""
    )


def search(cognome: str = "", cap: str = "", order: str = "",
           section: str = "", timeout: float = 20.0) -> SearchOutcome:
    ms = max(5000, int(timeout * 1000))
    with playwright() as p:
        browser, page = new_page(p, timeout_ms=ms)
        try:
            page.goto(f"{BASE}/RicercaIscritti", wait_until="domcontentloaded",
                      timeout=ms)
            settle(page, 3.0)
            if order:
                _set_dropdown(page, "#dllTutti", order)
                settle(page, 1.0)
            if section:
                _set_dropdown(page, "#ddlSezioni", section)
                settle(page, 0.8)
            if cap:
                page.fill('input[name="Cap"]', cap)
            elif cognome:
                page.fill('input[name="Cognome"]', cognome)
            else:
                raise ValueError("provide --cognome or --cap")
            page.locator("#btnContinua").click()

            deadline = time.time() + max(float(timeout), 10.0)
            while time.time() < deadline:
                settle(page, 3.0)
                if page.locator("#listIscritti .box-avvisi").count() > 0:
                    break
                empty = page.locator("#emptyIscritti")
                if empty.count() > 0 and empty.first.is_visible():
                    break

            empty_msg = ""
            empty = page.locator("#emptyIscritti")
            if empty.count() > 0 and empty.first.is_visible():
                empty_msg = empty.first.inner_text().strip()
            data = _dump(page)

            scope = order or "ITALIA"
            if cap:
                scope = f"CAP {cap}"
            records = [
                Record(source="CNDCEC", scope=scope,
                       name=f"{r['cognome']} {r['nome']}".strip(),
                       extra={
                           "birth": r["birth"].strip(),
                           "office": r["office"],
                           "status": ("suspended" if r["suspended"]
                                      else "removed" if r["removed"] else ""),
                       })
                for r in data["rows"] if (r["cognome"] or r["nome"])
            ]
            if empty_msg:
                return SearchOutcome(query=cognome or cap, source="CNDCEC",
                                     scope=scope, records=[], total=0,
                                     note=empty_msg, verified_empty=True)
            return SearchOutcome(query=cognome or cap, source="CNDCEC",
                                 scope=scope, records=records,
                                 total=data["n"], verified_empty=False)
        finally:
            browser.close()
