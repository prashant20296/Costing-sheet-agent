"""Build a manifest of inquiries and files.

Two sources, never trusted alone:
  * the inventory workbook (one tab per package; folder link is a SharePoint hyperlink)
  * the inquiry folders on disk (one folder per inquiry, any depth)

Outputs: manifest_inquiries.csv (one row per inquiry) and manifest_files.csv (one row per file).
File labels here come from file names only (label_source = 'filename'); the LLM/content classifier
overrides them later. Every disagreement is a flag, never a silent fix.
"""
from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import openpyxl

CAD_EXT = {".dwg", ".dxf", ".dgn", ".stp", ".step", ".igs", ".plj", ".sldprt", ".sldasm"}
OFFICE_LOCK = ("~$", ".~lock")
DOC_EXT = {".pdf", ".xlsx", ".xlsm", ".xls", ".docx", ".doc", ".msg", ".eml", ".zip", ".png", ".jpg", ".jpeg"}

# filename rules, first match wins: (label, regex on lower-case name, allowed extensions or None)
NAME_RULES = [
    ("costing_sheet", r"costing|estimation\s*sheet|price\s*summary|cost\s*sheet|pricing", {".xlsx", ".xlsm", ".xls"}),
    ("offer_letter", r"techno\s*-?\s*commercial|commercial\s*(proposal|offer)|\boffer\b|quotation|\bqtn\b", None),
    ("technical_proposal", r"technical\s*proposal|tech\.?\s*proposal", None),
    ("weight_workbook", r"weight|weightage|tonnage", {".xlsx", ".xlsm", ".xls"}),
    ("mto", r"(?<![a-z])mto(?![a-z])|material\s*take\s*-?\s*off", None),
    ("bom", r"(?<![a-z])(bom|boq)(?![a-z])|bill\s*of\s*material", None),
    ("process_sheet", r"process\s*sheet|routing|traveller", None),
    ("client_spec", r"spec(ification)?\b|procedure|standard|\bitp\b|galvani[sz]ation|painting", {".pdf", ".docx", ".doc"}),
    ("datasheet", r"data\s*-?\s*sheet|\bds\b", None),
    ("typicals_drawing", r"typical", {".pdf"}),
    ("drawing", r"\bdrg\b|\bdwg\b|drawing|\bga\b|g\.a\.|layout|plan|assembly|detail|\brev\b", {".pdf"}),
    ("correspondence", r".", {".msg", ".eml"}),
]


def label_from_name(name: str) -> str:
    low, ext = name.lower(), Path(name).suffix.lower()
    if ext in CAD_EXT:
        return "drawing"
    for label, pat, exts in NAME_RULES:
        if (exts is None or ext in exts) and re.search(pat, low):
            return label
    return "other"


def id_from_name(name: str) -> str | None:
    m = re.search(r"UEM[_\- ]?(\d{4,6})(?!\d)", name, re.I) or re.match(r"(\d{5})[_\- ]", name)
    return m.group(1) if m else None


def rev_from_name(name: str) -> int | None:
    m = re.search(r"[_\- ]R(\d{1,2})(?![\d])", name, re.I)
    return int(m.group(1)) if m else None


@dataclass
class FileRow:
    inquiry_id: str
    rel_path: str
    name: str
    ext: str
    size_kb: float
    modified: str
    label: str
    label_source: str = "filename"
    is_cad: bool = False
    rev: int | None = None
    id_in_name: str | None = None
    flags: str = ""


@dataclass
class InquiryRow:
    inquiry_id: str
    package: str | None = None
    year: int | None = None
    date: str | None = None
    customer: str | None = None
    subject: str | None = None
    inv_all_three: str | None = None
    inv_customer_docs: str | None = None
    inv_costing_files: str | None = None
    inv_offer_files: str | None = None
    inv_latest_rev: str | None = None
    inv_notes: str | None = None
    folder_url: str | None = None
    local_path: str | None = None
    source: str = "missing"              # local | sharepoint_only | missing
    n_files: int = 0
    n_cad: int = 0
    n_costing: int = 0
    n_offer: int = 0
    n_drawing_pdf: int = 0
    primary_costing: str | None = None
    primary_offer: str | None = None
    parse_ready: bool = False
    flags: list = field(default_factory=list)


def _s(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y")
    return str(v).strip() or None


def read_inventory(path: str | Path, package_prefix: str | None = None) -> dict[str, InquiryRow]:
    """One InquiryRow per INQ across package tabs (tabs whose header row starts with 'INQ')."""
    wb = openpyxl.load_workbook(path)          # not read_only: hyperlinks are needed
    out: dict[str, InquiryRow] = {}
    for ws in wb.worksheets:
        hdr = [_s(c.value) for c in ws[1]]
        if not hdr or (hdr[0] or "").upper() != "INQ":
            continue
        if package_prefix and not ws.title.strip().startswith(f"{package_prefix} "):
            continue
        col = {h.lower(): i for i, h in enumerate(hdr) if h}
        for r in ws.iter_rows(min_row=2):
            inq = r[0].value
            if inq is None:
                continue
            g = lambda k: _s(r[col[k]].value) if k in col and col[k] < len(r) else None
            link_cell = r[col["folder link"]] if "folder link" in col else None
            row = InquiryRow(
                inquiry_id=str(int(inq)) if isinstance(inq, (int, float)) else str(inq).strip(),
                package=ws.title.strip(), year=r[col["year"]].value if "year" in col else None,
                date=g("date"), customer=g("customer"), subject=g("subject"),
                inv_all_three=g("all three"), inv_customer_docs=g("customer docs"),
                inv_costing_files=g("costing files"), inv_offer_files=g("offer files"),
                inv_latest_rev=g("latest rev"), inv_notes=g("notes"),
                folder_url=link_cell.hyperlink.target if link_cell is not None and link_cell.hyperlink else None,
            )
            if row.inquiry_id in out:
                out[row.inquiry_id].flags.append(f"also listed in package tab '{row.package}'")
                continue
            out[row.inquiry_id] = row
    return out


def scan_folder(inquiry_id: str, folder: Path) -> list[FileRow]:
    rows = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.name.startswith(OFFICE_LOCK):
            continue
        st = p.stat()
        ext = p.suffix.lower()
        f = FileRow(
            inquiry_id=inquiry_id, rel_path=str(p.relative_to(folder)), name=p.name, ext=ext,
            size_kb=round(st.st_size / 1024, 1), modified=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
            label=label_from_name(p.name), is_cad=ext in CAD_EXT, rev=rev_from_name(p.name),
            id_in_name=id_from_name(p.name),
        )
        flags = []
        if f.id_in_name and f.id_in_name != inquiry_id and f.label in ("costing_sheet", "offer_letter", "technical_proposal"):
            flags.append(f"file name says {f.id_in_name}")
        if st.st_size == 0:
            flags.append("empty file")
        if ext not in DOC_EXT and ext not in CAD_EXT:
            flags.append("unusual extension")
        f.flags = "; ".join(flags)
        rows.append(f)
    return rows


_OFFER_EXT_PREF = {".docx": 0, ".pdf": 1, ".doc": 2}


def _pick(files: list[FileRow], label: str, inquiry_id: str, ext_pref: dict | None = None) -> FileRow | None:
    """Latest revision first; then a file whose name carries this inquiry id; then format; then newest."""
    cands = [f for f in files if f.label == label and (ext_pref is None or f.ext in ext_pref)]
    if not cands:
        return None
    return sorted(cands, key=lambda f: (
        -(f.rev if f.rev is not None else -1),
        0 if f.id_in_name == inquiry_id else 1,
        (ext_pref or {}).get(f.ext, 9),
        "".join(chr(255 - ord(c)) for c in f.modified),
    ))[0]


def build_manifest(inventory: dict[str, InquiryRow], roots: list[Path]) -> tuple[list[InquiryRow], list[FileRow]]:
    local: dict[str, Path] = {}
    for root in roots:
        for d in sorted(p for p in Path(root).iterdir() if p.is_dir()):
            m = re.match(r"(\d{5})", d.name)
            if m:
                local.setdefault(m.group(1), d)
    all_files: list[FileRow] = []
    rows = []
    for inq_id in sorted(set(inventory) | set(local)):
        row = inventory.get(inq_id) or InquiryRow(inquiry_id=inq_id, flags=["folder on disk but not in inventory"])
        folder = local.get(inq_id)
        if folder is None:
            row.source = "sharepoint_only" if row.folder_url else "missing"
            rows.append(row)
            continue
        row.local_path, row.source = str(folder), "local"
        files = scan_folder(inq_id, folder)
        all_files += files
        row.n_files = len(files)
        row.n_cad = sum(f.is_cad for f in files)
        row.n_costing = sum(f.label == "costing_sheet" for f in files)
        row.n_offer = sum(f.label == "offer_letter" for f in files)
        row.n_drawing_pdf = sum(f.label in ("drawing", "typicals_drawing") and f.ext == ".pdf" for f in files)
        pc = _pick(files, "costing_sheet", inq_id, {".xlsx": 0, ".xlsm": 1})
        po = _pick(files, "offer_letter", inq_id, _OFFER_EXT_PREF)
        row.primary_costing = pc.rel_path if pc else None
        row.primary_offer = po.rel_path if po else None
        row.parse_ready = bool(pc)
        if not pc:   # fallback: our own priced BOQ inside a revision folder (R0, R1 ...)
            boq = [f for f in files if f.label == "bom" and f.ext in (".xlsx", ".xlsm")
                   and re.search(r"(^|[\\/])R\d+[\\/]", f.rel_path)]
            if boq:
                pc = _pick(boq, "bom", inq_id, {".xlsx": 0, ".xlsm": 1})
                row.primary_costing, row.parse_ready = pc.rel_path, True
                row.flags.append("costing guessed: priced BOQ in revision folder")
        if not pc:
            xls = [f for f in files if f.label == "costing_sheet" and f.ext == ".xls"]
            row.flags.append("costing only as .xls (save as .xlsx)" if xls else "no costing workbook found by name")
        if not po:
            row.flags.append("no offer found by name")
        for f, what in ((pc, "costing"), (po, "offer")):
            if f and f.id_in_name and len(f.id_in_name) != 5:
                row.flags.append(f"{what} file name has malformed id '{f.id_in_name}'")
        if pc and po and pc.rev is not None and po.rev is not None and pc.rev != po.rev:
            row.flags.append(f"latest costing is R{pc.rev} but latest offer is R{po.rev}")
        if pc and pc.id_in_name and len(pc.id_in_name) == 5 and pc.id_in_name != inq_id:
            row.flags.append(f"primary costing named for {pc.id_in_name}")
        if po and po.id_in_name and len(po.id_in_name) == 5 and po.id_in_name != inq_id:
            row.flags.append(f"primary offer named for {po.id_in_name}")
        if row.inv_all_three == "Y" and not (pc and po):
            row.flags.append("inventory says complete but costing/offer not found on disk")
        if row.inv_latest_rev and pc and pc.rev is not None and f"R{pc.rev}" != row.inv_latest_rev.upper() \
                and (po is None or po.rev is None or f"R{po.rev}" != row.inv_latest_rev.upper()):
            row.flags.append(f"inventory latest rev {row.inv_latest_rev}, files show costing R{pc.rev}"
                             + (f" / offer R{po.rev}" if po and po.rev is not None else ""))
        rows.append(row)
    return rows, all_files


def write_manifest(rows: list[InquiryRow], files: list[FileRow], out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pi, pf = out / "manifest_inquiries.csv", out / "manifest_files.csv"
    inq = [{**asdict(r), "flags": "; ".join(r.flags)} for r in rows]
    for path, data, cls in ((pi, inq, InquiryRow), (pf, [asdict(f) for f in files], FileRow)):
        keys = list(cls.__dataclass_fields__)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(data)
    return pi, pf
