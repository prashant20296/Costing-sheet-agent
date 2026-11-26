"""Command line: parse one inquiry folder (or a costing file plus its offer)."""
from __future__ import annotations

import argparse
import csv
import traceback
from pathlib import Path

from .offer_reader import read_offer
from .parse_costing import parse_workbook
from .reconcile import reconcile
from .report import write_outputs


def _real(p: Path) -> bool:
    """Skip Office lock files ('~$name.xlsx') and other temp files."""
    return p.is_file() and not p.name.startswith(("~$", "."))


def find_files(folder: Path) -> tuple[list[Path], list[Path]]:
    costing = sorted(p for p in folder.rglob("*") if _real(p) and p.suffix.lower() in (".xlsx", ".xlsm")
                     and "costing" in p.name.lower())
    offers = sorted(p for p in folder.rglob("*") if _real(p) and p.suffix.lower() in (".docx", ".doc", ".pdf")
                    and ("proposal" in p.name.lower() or "offer" in p.name.lower()))
    return costing, offers


def run(costing: Path, offer_path: Path | None, out: Path) -> Path:
    parsed = parse_workbook(costing)
    offer = read_offer(offer_path) if offer_path else None
    rec = reconcile(parsed, offer) if offer else None
    return write_outputs(parsed, offer, rec, out)


def _summary_row(inq: dict, parsed, offer, rec) -> dict:
    costed = [s for s in parsed.scenarios if s.layout != "other"]
    flags = sum(len(l.flags) for s in costed for l in s.lines) + sum(len(s.warnings) for s in costed)
    unmapped = sum(1 for s in costed for l in s.lines if l.category is None)
    best = next((s for s in costed if rec and rec.best_scenario and rec.best_scenario.startswith(s.sheet)), None)
    best = best or next((s for s in costed if s.final_total), None)
    offer_total = (sum(it.total or 0 for it in offer.items) if offer and offer.items else
                   (offer.grand_totals[0] if offer and offer.grand_totals else None))
    all_m = (rec.matches + ([rec.total_match] if rec.total_match else [])) if rec else []
    gaps = [m.gap_pct for m in all_m if m.gap_pct is not None]
    return {
        "inquiry_id": inq["inquiry_id"], "customer": inq.get("customer"), "status": "ok", "error": "",
        "costing": inq["primary_costing"], "offer": inq.get("primary_offer") or "",
        "tabs": len(parsed.scenarios), "costed_tabs": len(costed),
        "layouts": "|".join(sorted({s.layout for s in costed})),
        "best_tab": best.sheet if best else "", "final_total": round(best.final_total, 2) if best and best.final_total else "",
        "weight_kg": round(best.total_weight_kg, 1) if best and best.total_weight_kg else "",
        "rate_per_kg": best.totals.get("final_rate_per_kg", "") if best else "",
        "offer_ref": offer.offer_ref if offer else "", "offer_items": len(offer.items) if offer else "",
        "offer_total": round(offer_total, 2) if offer_total else "",
        "matched_items": sum(1 for m in rec.matches if m.best_source) if rec else "",
        "best_gap_pct": min(gaps) if gaps else "",
        "explained_pct": rec.explained_share_pct if rec and rec.explained_share_pct is not None else "",
        "id_flags": "; ".join(rec.id_flags) if rec else "", "n_flags": flags, "unmapped_labels": unmapped,
    }


def parse_manifest(manifest_csv: Path, out: Path, only: set[str] | None = None) -> Path:
    with open(manifest_csv, encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if r["parse_ready"] == "True" and (not only or r["inquiry_id"] in only)]
    summary = []
    for r in rows:
        folder = Path(r["local_path"])
        costing = folder / r["primary_costing"]
        offer_path = folder / r["primary_offer"] if r["primary_offer"] else None
        try:
            parsed = parse_workbook(costing)
            parsed.inquiry_id = parsed.inquiry_id or r["inquiry_id"]
            offer, offer_err = None, ""
            if offer_path:
                try:
                    offer = read_offer(offer_path)
                except Exception as e:          # an unreadable offer must not lose the costing
                    offer_err = f"offer: {type(e).__name__}: {e}"
            rec = reconcile(parsed, offer) if offer else None
            if rec and parsed.inquiry_id != r["inquiry_id"]:
                rec.id_flags.insert(0, f"folder {r['inquiry_id']} holds costing named {parsed.inquiry_id}")
            write_outputs(parsed, offer, rec, out / r["inquiry_id"])
            row = _summary_row(r, parsed, offer, rec)
            if offer_err:
                row["status"], row["error"] = "offer_error", offer_err[:300]
        except Exception as e:
            row = {"inquiry_id": r["inquiry_id"], "customer": r.get("customer"), "status": "error",
                   "error": f"{type(e).__name__}: {e}"[:300], "costing": r["primary_costing"], "offer": r["primary_offer"]}
            (out / r["inquiry_id"]).mkdir(parents=True, exist_ok=True)
            (out / r["inquiry_id"] / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        summary.append(row)
        print(f"{row['inquiry_id']}: {row['status']} {row.get('error', '')[:100]}")
    path = out / "batch_summary.csv"
    out.mkdir(parents=True, exist_ok=True)
    if only and path.is_file():        # partial re-run: keep the other inquiries' rows
        with open(path, encoding="utf-8-sig") as fh:
            done = {r["inquiry_id"] for r in summary}
            summary = [r for r in csv.DictReader(fh) if r["inquiry_id"] not in done] + summary
        summary.sort(key=lambda r: r["inquiry_id"])
    keys = list(dict.fromkeys(k for row in summary for k in row))
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(summary)
    return path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="costing-agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("parse", help="parse one costing workbook (+ offer)")
    p1.add_argument("--costing", required=True, type=Path)
    p1.add_argument("--offer", type=Path)
    p1.add_argument("--out", type=Path, default=Path("data/interim"))
    p2 = sub.add_parser("parse-folder", help="find costing + offer inside an inquiry folder")
    p2.add_argument("folder", type=Path)
    p2.add_argument("--out", type=Path, default=Path("data/interim"))
    p3 = sub.add_parser("manifest", help="inventory workbook + local folders -> manifest CSVs")
    p3.add_argument("--inventory", required=True, type=Path)
    p3.add_argument("--roots", required=True, type=Path, nargs="+", help="folders holding one sub-folder per inquiry")
    p3.add_argument("--package", help="package number prefix of the inventory tab, e.g. 8")
    p3.add_argument("--out", type=Path, default=Path("data/interim/manifest"))
    p4 = sub.add_parser("parse-manifest", help="parse every parse-ready inquiry in a manifest")
    p4.add_argument("manifest", type=Path)
    p4.add_argument("--out", type=Path, default=Path("data/interim/batch"))
    p4.add_argument("--only", nargs="*", help="inquiry ids to parse")
    a = ap.parse_args(argv)
    if a.cmd == "manifest":
        from .manifest import build_manifest, read_inventory, write_manifest
        inv = read_inventory(a.inventory, a.package)
        rows, files = build_manifest(inv, a.roots)
        if a.package:   # local folders of other packages are not this package's business
            rows = [r for r in rows if r.package or r.source == "local"]
        pi, pf = write_manifest(rows, files, a.out)
        n = {s: sum(r.source == s for r in rows) for s in ("local", "sharepoint_only", "missing")}
        print(f"{len(rows)} inquiries ({n}); {sum(r.parse_ready for r in rows)} parse-ready; {len(files)} files")
        print(pi, pf, sep=chr(10))
        return
    if a.cmd == "parse-manifest":
        print(parse_manifest(a.manifest, a.out, set(a.only) if a.only else None))
        return
    if a.cmd == "parse":
        print(run(a.costing, a.offer, a.out))
        return
    costing, offers = find_files(a.folder)
    if not costing:
        raise SystemExit(f"no costing workbook found in {a.folder}")
    if len(costing) > 1:
        print(f"note: {len(costing)} costing files found, using {costing[0].name}")
    if len(offers) > 1:
        print(f"note: {len(offers)} offer-like files found, using {offers[0].name}")
    print(run(costing[0], offers[0] if offers else None, a.out))


if __name__ == "__main__":
    main()
