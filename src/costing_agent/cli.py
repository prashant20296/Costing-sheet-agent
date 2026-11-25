"""Command line: parse one inquiry folder (or a costing file plus its offer)."""
from __future__ import annotations

import argparse
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
    a = ap.parse_args(argv)
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
