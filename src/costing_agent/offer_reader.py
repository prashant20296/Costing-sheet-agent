"""Read a techno-commercial offer (.docx, .doc, .pdf) into price items, scope and terms."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OfferItem:
    item_no: str | None
    description: str
    qty: float | None
    unit: str | None
    rate: float | None
    total: float | None
    table_no: int | None = None   # offers often hold one price table per scope item, each numbered 01

    @property
    def key(self) -> str:
        return f"T{self.table_no}/{self.item_no}" if self.table_no else str(self.item_no)


@dataclass
class Offer:
    file: str
    offer_ref: str | None = None
    date: str | None = None
    customer: str | None = None
    customer_ref: str | None = None
    subject: str | None = None
    items: list[OfferItem] = field(default_factory=list)
    grand_totals: list[float] = field(default_factory=list)
    terms: dict[str, str] = field(default_factory=dict)
    exclusions: list[str] = field(default_factory=list)
    client_scope: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def _to_float(s: str | None) -> float | None:
    if s is None:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", s.replace(" ", ""))
    return float(m.group(0).replace(",", "")) if m else None


def _find_soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        for exe in ("soffice.com", "soffice.exe"):     # .com is the console build: it waits and reports
            p = Path(base) / "LibreOffice" / "program" / exe
            if base and p.is_file():
                return str(p)
    return None


def _convert_doc(path: Path) -> Path:
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice is needed to read .doc files (or save the file as .docx)")
    work = Path(tempfile.mkdtemp(prefix="costing_doc_"))
    src = work / "offer.doc"                 # plain name: real names hold '..' and spaces
    shutil.copyfile(path, src)
    # own, reused profile so a running LibreOffice cannot swallow the job; a brand-new profile
    # only initialises on the first launch and converts nothing, hence one retry
    profile = (Path(tempfile.gettempdir()) / "costing_agent_lo_profile").as_uri()
    cmd = [soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore", "--nologo",
           "--convert-to", "docx:MS Word 2007 XML", "--outdir", str(work), str(src)]
    out = work / "offer.docx"
    for _ in range(2):
        try:
            subprocess.run(cmd, capture_output=True, timeout=180)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"LibreOffice timed out converting {path.name}") from None
        if out.is_file():
            return out
    raise RuntimeError(f"LibreOffice produced no .docx for {path.name}")


def _read_docx(path: Path) -> tuple[str, list[list[list[str]]]]:
    import docx
    d = docx.Document(path)
    text = "\n".join(p.text for p in d.paragraphs)
    tables = [[[c.text.strip() for c in r.cells] for r in t.rows] for t in d.tables]
    return text, tables


def _read_pdf(path: Path) -> tuple[str, list[list[list[str]]]]:
    import pdfplumber
    texts, tables = [], []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            texts.append(pg.extract_text() or "")
            for t in pg.extract_tables():
                tables.append([[(c or "").strip() for c in r] for r in t])
    return "\n".join(texts), tables


def _header_cols(row: list[str]) -> dict[str, int] | None:
    """Column roles from header text; PDF tables often have empty merged columns in between."""
    cols: dict[str, int] = {}
    for i, c in enumerate(row):
        t = re.sub(r"\s+", " ", c.lower())
        if "description" in t:
            cols.setdefault("desc", i)
        elif re.search(r"\bqty|quantity", t):
            cols.setdefault("qty", i)
        elif re.search(r"unit\s*(price|rate)|\brate\b", t):
            cols.setdefault("rate", i)
        elif re.search(r"total|amount", t):
            cols["total"] = i
        elif re.search(r"s\.?\s*no|item|^#$|^sl", t):
            cols.setdefault("item", i)
    return cols if {"desc", "qty"} <= cols.keys() else None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _shift(rows: list[list[str]], tc: int) -> int:
    """PDF-to-Word tables can put data one cell left or right of its header.
    Return the offset that puts a number under the Total heading."""
    for r in rows:
        for off in (0, -1, 1):
            j = tc + off
            if 0 <= j < len(r) and _to_float(r[j]) is not None:
                return off
    return 0

def _price_items(tables: list[list[list[str]]]) -> tuple[list[OfferItem], list[float]]:
    items, grands = [], []
    for t_no, t in enumerate(tables, start=1):
        t = [[c or "" for c in r] for r in t]
        hdr = next(((i, cols) for i, r in enumerate(t) if (cols := _header_cols(r))), None)
        if hdr is None:
            continue
        i0, cols = hdr
        qc, tc = cols["qty"], cols.get("total", len(t[i0]) - 1)
        rc, ic = cols.get("rate"), cols.get("item", 0)
        off = _shift(t[i0 + 1:], tc)
        qc, tc, ic = qc + off, tc + off, max(ic + off, 0)
        rc = rc + off if rc is not None else None
        current: OfferItem | None = None
        for r in t[i0 + 1:]:
            get = lambda i: r[i] if i is not None and i < len(r) else ""
            joined = " ".join(r).lower()
            total = _to_float(get(tc))
            if "grand total" in joined or re.search(r"^\s*total\b", joined):
                if total is not None:
                    grands.append(total)
                current = None
                continue
            # description: every non-empty cell between the item column and the qty column
            desc = _clean(" ".join(c for c in r[ic + 1:qc] if c))
            if total is None:
                if current is not None and desc:          # continuation line of the item above
                    current.description = _clean(f"{current.description} {desc}")
                continue
            qty_txt = get(qc)
            unit = re.sub(r"[\d.,\s]+", "", qty_txt).rstrip(".") or None
            current = OfferItem(_clean(get(ic)) or None, desc, _to_float(qty_txt), unit,
                                _to_float(get(rc)) if rc is not None else None, total, table_no=t_no)
            items.append(current)
    return items, grands


def _bullets_after(text: str, heading: str, stop: list[str]) -> list[str]:
    lines = [l.strip() for l in text.splitlines()]
    out, on = [], False
    for l in lines:
        bare = re.sub(r"^[IVX]+\.\s*", "", l).strip().rstrip(":").lower()
        if bare.startswith(heading):
            on = True
            continue
        if on and any(bare.startswith(s) for s in stop):
            break
        if on and l:
            out.append(re.sub(r"^[\u2022\u00b7\-\*]\s*", "", l))
    return out


def read_offer(path: str | Path) -> Offer:
    path = Path(path)
    src = _convert_doc(path) if path.suffix.lower() == ".doc" else path
    text, tables = _read_pdf(src) if src.suffix.lower() == ".pdf" else _read_docx(src)
    o = Offer(file=path.name)
    m = re.search(r"Offer\s*Ref\s*:?\s*(\d+)", text) or re.search(r"Our\s*Ref\s*:?\s*UEM/(\d+)/", text)
    o.offer_ref = m.group(1) if m else None
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Z][a-z]+)\s+(\d{4})", text)
    o.date = " ".join(m.groups()) if m else None
    m = re.search(r"^\s*(M/s[^\n]+)", text, re.M)
    o.customer = m.group(1).strip().rstrip(".") if m else None
    m = re.search(r"Customer\s*Ref\s*:\s*([^\n]+)", text)
    o.customer_ref = m.group(1).strip() if m else None
    m = re.search(r"Subject\s*:\s*([^\n]+)", text)
    o.subject = m.group(1).strip() if m else None
    o.items, o.grand_totals = _price_items(tables)
    for key in ("Price Term", "Inco Terms", "Delivery Mode", "Warranty", "Payment Terms", "Lead Time"):
        m = re.search(rf"{key}[\s.\u2026]*:\s*([^\n]+)", text)
        if m:
            o.terms[key] = m.group(1).strip()
    o.exclusions = _bullets_after(text, "exclusions", ["price offer", "commercial"])
    o.client_scope = _bullets_after(text, "client scope", ["documentation", "quality", "general terms"])
    if re.search(r"actual\s+fabricated\s+weight", text, re.I):
        o.terms["Invoicing"] = "at actual fabricated weight"
    for it in o.items:
        if it.qty and it.rate and it.total and abs(it.qty * it.rate - it.total) / it.total > 0.0001:
            o.flags.append(f"item {it.key}: qty x rate = {it.qty * it.rate:,.2f} but total is {it.total:,.2f}"
                           f" (diff {it.qty * it.rate - it.total:+,.2f}; displayed qty may be rounded)")
    return o
