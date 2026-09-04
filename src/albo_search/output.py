"""Shared result models and output rendering (table / JSON / CSV)."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field


@dataclass
class Record:
    """A single registry entry with source-specific columns kept as strings."""

    source: str
    scope: str            # e.g. "MILANO", "FIRENZE", "CNDCEC", "ANAGRAFE"
    name: str
    extra: dict[str, str] = field(default_factory=dict)

    def as_row(self, columns: list[str]) -> list[str]:
        values = [self.source, self.scope, self.name]
        values += [self.extra.get(c, "") for c in columns]
        return values


@dataclass
class SearchOutcome:
    """Result of a completed search."""

    query: str
    source: str
    scope: str
    records: list[Record]
    total: int | None = None      # upstream total when the source reports it
    note: str = ""                # upstream informational line, if any
    verified_empty: bool = False  # True only when the source said "no results"

    @property
    def found(self) -> int:
        return len(self.records)


def render_json(outcome: SearchOutcome) -> str:
    payload = {
        "query": outcome.query,
        "source": outcome.source,
        "scope": outcome.scope,
        "total": outcome.total if outcome.total is not None else outcome.found,
        "note": outcome.note,
        "verified_empty": outcome.verified_empty,
        "results": [
            {"name": r.name, **r.extra}
            for r in outcome.records
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_csv(outcome: SearchOutcome) -> str:
    columns: list[str] = []
    for record in outcome.records:
        for key in record.extra:
            if key not in columns:
                columns.append(key)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["source", "scope", "name", *columns])
    for record in outcome.records:
        writer.writerow(record.as_row(columns))
    return buf.getvalue()


def render_table(outcome: SearchOutcome) -> str:
    lines: list[str] = []
    head = f"{outcome.source} · {outcome.scope} · query '{outcome.query}'"
    lines.append(head)
    lines.append("-" * len(head))
    if outcome.note:
        lines.append(outcome.note)
    if not outcome.records:
        lines.append("No results (verified negative)."
                     if outcome.verified_empty else "No results.")
        return "\n".join(lines)
    columns: list[str] = []
    for record in outcome.records:
        for key in record.extra:
            if key not in columns:
                columns.append(key)
    rows = [r.as_row(columns) for r in outcome.records]
    header = ["source", "scope", "name", *columns]
    widths = [max(len(str(row[i])) for row in [header, *rows]) for i in range(len(header))]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines.append(fmt.format(*header))
    lines.append("-" * (sum(widths) + 2 * (len(header) - 1)))
    for row in rows:
        lines.append(fmt.format(*row))
    if outcome.total is not None and outcome.total > outcome.found:
        lines.append(f"… {outcome.total - outcome.found} more on the portal "
                     f"(showing the first {outcome.found})")
    return "\n".join(lines)
