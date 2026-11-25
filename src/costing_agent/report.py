"""Write parsed data as CSV/JSON and a human-readable parse report."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from .checks import check_boq
from .models import ParsedCosting
from .offer_reader import Offer
from .reconcile import Reconciliation

RATE_BASES = {"per_kg", "per_hour", "per_lot", "per_visit", "per_m2", "per_unit", "pct"}


def _r(v):
    return round(v, 2) if isinstance(v, (int, float)) else v


def _csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def rate_snapshot_rows(parsed: ParsedCosting, offer: Offer | None) -> list[dict]:
    """Rates and percentages found in the sheet. They go to a rate history, never into the model."""
    rows = []
    for s in parsed.scenarios:
        for l in s.lines:
            if l.basis not in RATE_BASES or l.category in ("margin", "contingency") and l.basis != "pct":
                continue
            value = l.rate if l.rate is not None else (l.formula_pcts[0] if l.formula_pcts else l.label_pct)
            if value is None:
                continue
            rows.append({
                "inquiry_id": parsed.inquiry_id, "sheet": s.sheet, "component": l.component, "category": l.category, "basis": l.basis,
                "value": round(value, 4), "uom": l.uom, "offer_date": offer.date if offer else None,
                "customer": offer.customer if offer else None,
            })
    return rows


def write_outputs(parsed: ParsedCosting, offer: Offer | None, rec: Reconciliation | None, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tag = parsed.inquiry_id or Path(parsed.file).stem
    _csv(out / f"{tag}_cost_lines.csv", [asdict(l) for s in parsed.scenarios for l in s.lines])
    _csv(out / f"{tag}_boq_lines.csv", [asdict(b) for s in parsed.scenarios for b in s.boq])
    comps = []
    for s in parsed.scenarios:
        for c in s.components:
            d = asdict(c)
            kg = d.pop("kg_by_component")
            comps.append({"sheet": s.sheet, **d, **{f"kg_{k.strip()}": v for k, v in kg.items()}})
    _csv(out / f"{tag}_components.csv", comps)
    _csv(out / f"{tag}_rate_snapshot.csv", rate_snapshot_rows(parsed, offer))
    payload = {"costing": asdict(parsed), "offer": asdict(offer) if offer else None,
               "reconciliation": asdict(rec) if rec else None}
    (out / f"{tag}.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = out / f"{tag}_parse_report.md"
    md.write_text(render_report(parsed, offer, rec), encoding="utf-8")
    return md


def render_report(parsed: ParsedCosting, offer: Offer | None, rec: Reconciliation | None) -> str:
    L = [f"# Parse report: {parsed.file}", f"Inquiry id from file name: {parsed.inquiry_id}", ""]
    if offer:
        L += ["## Offer", f"- file: {offer.file}", f"- offer ref: {offer.offer_ref}  date: {offer.date}",
              f"- customer: {offer.customer}  customer ref: {offer.customer_ref}", f"- subject: {offer.subject}"]
        for it in offer.items:
            L.append(f"- item {it.key}: {it.description[:70]} | {it.qty} {it.unit} x {it.rate} = {it.total}")
        if offer.terms:
            L.append("- terms: " + "; ".join(f"{k}: {v}" for k, v in offer.terms.items()))
        L.append(f"- exclusions listed: {len(offer.exclusions)}; client scope items: {len(offer.client_scope)}")
        L += [f"- NOTE {f}" for f in offer.flags]
        L.append("")
    if rec:
        L += ["## Costing to offer reconciliation"]
        L += [f"- ID CHECK: {f}" for f in rec.id_flags] or ["- identifiers agree"]
        for m in rec.matches:
            L.append(f"- offer '{m.offer_item}' {m.offer_total:,.2f} -> "
                     + (f"{m.best_source} {m.source_total:,.2f} (gap {m.gap_pct}%)" if m.best_source else "no matching costing total"))
        if rec.explained_share_pct is not None:
            L.append(f"- costing explains {rec.explained_share_pct}% of the offer value")
        L.append("")
    L.append("## Tabs")
    for s in parsed.scenarios:
        if s.layout == "other":
            L.append(f"- `{s.sheet}`: not a costing table (scratch, weight calc or other); skipped")
            continue
        L += [f"### `{s.sheet}` ({s.layout})", f"- title: {s.title}",
              f"- total weight: {s.total_weight_kg and round(s.total_weight_kg, 1)} kg; sets/units: {s.sets}",
              f"- final total: {s.final_total and round(s.final_total, 2)}; "
              f"rate per kg: {s.totals.get('final_rate_per_kg')}",
              f"- scope detected: {s.scope}",
              f"- margin {s.totals.get('margin_pct_effective')}% / contingency {s.totals.get('contingency_pct_effective')}% "
              f"(effective); markup on direct cost {s.totals.get('markup_on_direct_pct')}%",
              f"- BOQ lines: {len(s.boq)}; cost lines: {len(s.lines)}; components: {len(s.components)}; "
              f"options: {[(o.label, o.total) for o in s.options]}", "", "| category | basis | qty | rate | amount |", "|---|---|---|---|---|"]
        for l in s.lines:
            if l.component:
                continue
            L.append(f"| {l.category or '?'} ({l.label[:28]}) | {l.basis} | {_r(l.qty)} | {_r(l.rate)} | {_r(l.amount)} |")
        comp_lines = [l for l in s.lines if l.component]
        if comp_lines:
            names = list(dict.fromkeys(l.component for l in comp_lines))
            cats = list(dict.fromkeys(l.category or l.label for l in comp_lines))
            L += ["", "| category | " + " | ".join(n.strip() for n in names) + " | all |", "|---|" + "---|" * (len(names) + 1)]
            for c in cats:
                vals = {n: sum(l.amount or 0 for l in comp_lines if (l.category or l.label) == c and l.component == n) for n in names}
                L.append(f"| {c} | " + " | ".join(str(_r(vals[n]) or "-") for n in names) + f" | {_r(sum(vals.values()))} |")
        flags = [f"{l.label}: {f}" for l in s.lines for f in l.flags] + s.warnings + check_boq(s)
        L += [""] + [f"- FLAG {f}" for f in flags] + [""]
    return "\n".join(L)
