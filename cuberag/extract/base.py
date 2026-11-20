"""Pluggable fact extractor: the output contract shared by every backend.

Contract (same as the TF-IDF stand-in of scripts/run_small_eval.py):
for each report and each concept the backend returns a probability q in [0, 1] that the report
states the concept, plus (when available) an evidence span quoted from the report text. A concept
that is not returned has q = 0 and emits no fact. The cube turns each (report, concept, q, span)
into one Fact (ALGEBRA.md 10.1, decision D3).

Facts are written as JSON lines: {"id": report id, "concept": str, "q": float, "span": str|null,
"span_found": bool}. `load_facts` reads them back.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Protocol, Sequence


@dataclass(frozen=True)
class Extraction:
    report_id: str
    concept: str
    q: float
    span: str | None = None
    span_found: bool = False  # the span occurs in the report text (whitespace/case-normalized)

    def to_json(self) -> dict:
        d = asdict(self)
        return {"id": d.pop("report_id"), **d}


@dataclass
class ReportText:
    rid: str
    text: str


class Extractor(Protocol):
    """A backend maps one report to its extractions. Batching and caching live in the runner."""

    name: str

    def extract_batch(self, reports: Sequence[ReportText]) -> list[tuple[list[Extraction], dict]]:
        """Return, per report, (extractions, meta). meta holds the raw output and token usage."""
        ...


def write_facts(path: Path, exts: Iterable[Extraction]) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for e in exts:
            f.write(json.dumps(e.to_json()) + "\n")
            n += 1
    return n


def load_facts(path: Path) -> list[Extraction]:
    out = []
    for line in open(path, encoding="utf-8"):
        d = json.loads(line)
        out.append(Extraction(d["id"], d["concept"], float(d["q"]), d.get("span"), bool(d.get("span_found"))))
    return out
