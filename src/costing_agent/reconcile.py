"""Link a costing workbook to its offer and check that the identifiers agree."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import ParsedCosting
from .offer_reader import Offer


@dataclass
class Match:
    offer_item: str
    offer_total: float
    best_source: str | None
    source_total: float | None
    gap_pct: float | None


@dataclass
class Reconciliation:
    inquiry_id: str | None
    id_flags: list[str] = field(default_factory=list)
    matches: list[Match] = field(default_factory=list)
    explained_share_pct: float | None = None
    best_scenario: str | None = None


def _candidates(parsed: ParsedCosting) -> list[tuple[str, float]]:
    out = []
    for s in parsed.scenarios:
        if s.layout == "other":
            continue
        if s.final_total:
            out.append((f"{s.sheet} / final total", s.final_total))
        for o in s.options:
            if o.total:
                out.append((f"{s.sheet} / {o.label}", o.total))
    return out


def reconcile(parsed: ParsedCosting, offer: Offer, tolerance_pct: float = 6.0) -> Reconciliation:
    rec = Reconciliation(inquiry_id=parsed.inquiry_id)
    ids = {"costing file name": parsed.inquiry_id, "offer ref": offer.offer_ref}
    m = re.findall(r"\d{6,}", offer.customer_ref or "")
    if m:
        ids["customer ref"] = m[0]
    if parsed.inquiry_id and offer.offer_ref and parsed.inquiry_id != offer.offer_ref:
        rec.id_flags.append(f"identifier mismatch: file name says {parsed.inquiry_id}, offer ref says {offer.offer_ref}")
    cands = _candidates(parsed)
    explained, additive_total = 0.0, 0.0
    for it in offer.items:
        best = min(cands, key=lambda c: abs(c[1] - it.total), default=None) if it.total else None
        gap = abs(best[1] - it.total) / it.total * 100 if best and it.total else None
        ok = gap is not None and gap <= tolerance_pct
        rec.matches.append(Match(it.description[:60], it.total or 0.0, best[0] if ok else None,
                                 best[1] if ok else None, round(gap, 2) if ok else None))
        if ok:
            explained += it.total
        additive_total += it.total or 0
    is_options = any(re.match(r"\s*option", it.description, re.I) for it in offer.items)
    if offer.items and not is_options and additive_total:
        rec.explained_share_pct = round(explained / additive_total * 100, 1)
    ok = [m for m in rec.matches if m.best_source]
    if ok:
        rec.best_scenario = min(ok, key=lambda m: m.gap_pct).best_source
    return rec
