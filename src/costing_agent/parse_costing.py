"""Parse a costing workbook into the standard schema.

Two families of layout are supported (v1):
  * list layouts: a BOQ table and/or a cost build-up table, read top to bottom
  * matrix layouts: components (structural, grating...) as columns, cost categories as rows
Layout is detected from header text, never from tab names or fixed cell addresses.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .categories import (
    TOTAL_KINDS, UNIT_TOKEN, basis_from_uom, classify_label, formula_percents,
    label_percent, qty_formula_literals,
)
from .models import BOQLine, Component, CostLine, Option, ParsedCosting, Scenario
from .xlsx_reader import Cell, Row, read_workbook

HEADER_ROLES = [
    ("total_weight", r"total\s*weight"),
    ("unit_weight", r"unit\s*weight"),
    ("total_area", r"total\s*m2"),
    ("unit_area", r"unit\s*m2"),
    ("amount", r"total\s*price|^total$|total\s*amount"),
    ("unit_price", r"unit\s*price"),
    ("total_qty", r"total\s*qty|^t\.\s*qty"),
    ("qty", r"^qty\.?$"),
    ("sets", r"^sets?\.?$"),
    ("nos", r"^nos\.?$"),
    ("uom", r"^uom$|^unit$"),
    ("material", r"^materials?$"),
    ("part", r"^part"),
    ("length", r"^l$|size/length|^length"),
    ("width", r"^w$|^width"),
    ("description", r"^items?$|description"),
    ("item_no", r"^#$|^sl\.?\s*no"),
]


def map_header(row: Row) -> dict[int, str]:
    roles: dict[int, str] = {}
    for col, c in sorted(row.items()):
        if not c.is_text:
            continue
        t = re.sub(r"\s+", " ", c.text.lower()).strip()
        for role, pat in HEADER_ROLES:
            if re.search(pat, t) and role not in roles.values():
                roles[col] = role
                break
    return roles


def is_header(row: Row) -> dict[int, str] | None:
    roles = map_header(row)
    texts = [c for c in row.values() if c.is_text]
    if len(roles) >= 4 and len(roles) / max(len(texts), 1) >= 0.7:
        return roles
    return None


def _num(row: Row, col: int | None) -> float | None:
    c = row.get(col) if col else None
    return float(c.value) if c is not None and c.is_num else None


def _txt(row: Row, col: int | None) -> str | None:
    c = row.get(col) if col else None
    return c.text if c is not None and c.is_text else None


def _inv(roles: dict[int, str]) -> dict[str, int]:
    return {v: k for k, v in roles.items()}


def _label_cell(row: Row) -> Cell | None:
    """Leftmost text cell that is not just a unit token ('Kgs.', 'Lot.')."""
    for col in sorted(row):
        c = row[col]
        if c.is_text and not UNIT_TOKEN.match(c.text) and len(c.text) >= 3:
            return c
    return None


def _row_formulas(row: Row, cols: set[int]) -> list[str]:
    """Formulas in the table's own columns only; scratch cells off to the side are ignored."""
    return [c.formula for col, c in row.items() if c.formula and col in cols]


# --------------------------------------------------------------------- list layouts

def _parse_boq_row(sheet: str, row: Row, inv: dict[str, int]) -> BOQLine | None:
    tw, amt, tq = _num(row, inv.get("total_weight")), _num(row, inv.get("amount")), _num(row, inv.get("total_qty"))
    if tw is None and amt is None and tq is None:
        return None
    first = next(iter(row.values()))
    item_no = _txt(row, inv.get("item_no"))
    if item_no is None and inv.get("item_no") and row.get(inv["item_no"]) is not None and row[inv["item_no"]].is_num:
        item_no = str(int(row[inv["item_no"]].value))
    return BOQLine(
        sheet=sheet, row=first.row, item_no=item_no,
        part_no=(str(int(_num(row, inv["part"]))) if inv.get("part") and _num(row, inv.get("part")) is not None
                 else _txt(row, inv.get("part"))),
        description=_txt(row, inv.get("description")), material=_txt(row, inv.get("material")),
        length=_num(row, inv.get("length")), width=_num(row, inv.get("width")),
        nos=_num(row, inv.get("nos")), qty=_num(row, inv.get("qty")), uom=_txt(row, inv.get("uom")),
        sets=_num(row, inv.get("sets")), total_qty=tq,
        unit_weight=_num(row, inv.get("unit_weight")), total_weight_kg=tw,
        unit_area=_num(row, inv.get("unit_area")), total_area_m2=_num(row, inv.get("total_area")),
        unit_price=_num(row, inv.get("unit_price")), amount=amt,
    )


def _is_boq_end(row: Row) -> bool:
    for c in row.values():
        if c.is_text and re.search(r"\btotal\b|materials?\s+cost", c.text.lower()):
            return True
    return False


def parse_list_sheet(sheet: str, rows: list[Row]) -> Scenario:
    sc = Scenario(sheet=sheet, layout="cost_list")
    state: tuple[str, dict[int, str]] | None = None  # ('boq'|'cost', roles)
    title_set = False
    boq_subtotal: dict[str, float] = {}
    for row in rows:
        roles = is_header(row)
        if roles:
            kind = "boq" if ({"material", "total_weight"} & set(roles.values())) else "cost"
            state = (kind, roles)
            if kind == "boq":
                sc.layout = "boq_list"
            title_set = True
            continue
        if state is None:
            if not title_set:
                t = _label_cell(row)
                if t:
                    sc.title, title_set = t.text, True
            continue
        kind, roles = state
        inv = _inv(roles)
        if kind == "boq":
            if _is_boq_end(row):
                boq_subtotal = {
                    "weight": _num(row, inv.get("total_weight")) or 0.0,
                    "amount": _num(row, inv.get("amount")) or 0.0,
                    "area": _num(row, inv.get("total_area")) or 0.0,
                }
                state = None
                continue
            line = _parse_boq_row(sheet, row, inv)
            if line:
                sc.boq.append(line)
            continue
        _parse_cost_row(sc, row, inv)
    _finish_list(sc, boq_subtotal)
    return sc


def _parse_cost_row(sc: Scenario, row: Row, inv: dict[str, int]) -> None:
    lab = _label_cell(row)
    just_after_total = sc.totals.pop("_last_was_total", None)
    amount_cell = row.get(inv.get("amount")) if inv.get("amount") else None
    amount = float(amount_cell.value) if amount_cell is not None and amount_cell.is_num else None
    if lab is None:
        if amount is not None:
            if just_after_total:
                sc.totals["final_rate_per_kg_reported"] = amount
            else:
                sc.warnings.append(f"{amount_cell.coord}: unlabelled value {amount:,.2f}")
        return
    kind_or_cat = classify_label(lab.text)
    if amount_cell is not None and amount_cell.is_error:
        sc.warnings.append(f"{amount_cell.coord}: error value {amount_cell.value} on '{lab.text}'")
        return
    if amount is None:
        return  # section header or note
    if kind_or_cat in TOTAL_KINDS:
        sc.totals[kind_or_cat] = amount
        if kind_or_cat == "final_total":
            sc.totals["_last_was_total"] = 1
        return
    uom = _txt(row, inv.get("uom"))
    forms = _row_formulas(row, set(inv.values()))
    fpcts = sorted({p for f in forms for p in formula_percents(f)})
    lpct = label_percent(lab.text)
    basis = basis_from_uom(uom)
    qty_val = _num(row, inv.get("qty"))
    if basis is None and (lpct is not None or fpcts):
        basis = "pct"
    if basis == "per_lot" and qty_val is not None and 0 < qty_val < 1:
        basis = "pct"          # "Lot" with a fraction (0.08) means 8% of material
    line = CostLine(
        sheet=sc.sheet, row=lab.row, label=lab.text, category=kind_or_cat, basis=basis,
        qty=_num(row, inv.get("qty")), uom=uom, rate=_num(row, inv.get("unit_price")), amount=amount,
        label_pct=lpct, formula_pcts=fpcts,
        qty_literals=qty_formula_literals(row[inv["qty"]].formula) if inv.get("qty") in row else None,
    )
    if lpct is not None and fpcts and all(abs(lpct - p) > 0.01 for p in fpcts):
        line.flags.append(f"label says {lpct:g}% but formula applies {', '.join(f'{p:g}' for p in fpcts)}%")
    if kind_or_cat is None:
        line.flags.append("unmapped label")
    sc.lines.append(line)


def _finish_list(sc: Scenario, boq_subtotal: dict[str, float]) -> None:
    if sc.boq:
        sc.total_weight_kg = boq_subtotal.get("weight") or sum(b.total_weight_kg or 0 for b in sc.boq)
        sets = Counter(b.sets for b in sc.boq if b.sets)
        sc.sets = sets.most_common(1)[0][0] if sets else None
        ids = [b.item_no for b in sc.boq if b.item_no]
        if len(ids) != len(set(ids)):
            sc.warnings.append("item numbers repeat in the BOQ table")
        if not any(l.category == "material" for l in sc.lines) and boq_subtotal.get("amount"):
            sc.lines.insert(0, CostLine(
                sheet=sc.sheet, row=0, label="Materials (BOQ subtotal)", category="material", basis="per_kg",
                qty=sc.total_weight_kg, uom="Kgs.", amount=boq_subtotal["amount"],
                rate=(boq_subtotal["amount"] / sc.total_weight_kg) if sc.total_weight_kg else None))
    if sc.total_weight_kg is None:
        mat = next((l for l in sc.lines if l.category == "material" and l.basis == "per_kg" and l.qty), None)
        sc.total_weight_kg = mat.qty if mat else None
    _scope_and_checks(sc)


def _scope_and_checks(sc: Scenario) -> None:
    present = {l.category for l in sc.lines if (l.amount or 0) != 0}
    sc.scope["materials"] = "supplied" if "material" in present else "none"
    sc.scope["galvanizing"] = "included" if "galvanizing" in present else "none"
    sc.scope["painting"] = "included" if "painting" in present else "none"
    direct = sc.direct_cost()
    ref = sc.totals.get("subtotal_cost") or (sc.totals.get("final_total") if not any(
        l.category in ("margin", "contingency") for l in sc.lines) else None)
    if ref and abs(direct - ref) / ref > 0.001:
        sc.warnings.append(f"cost lines sum to {direct:,.2f} but sheet subtotal is {ref:,.2f}")
    sc.totals.pop("_last_was_total", None)
    sc.totals.setdefault("direct_cost_sum", round(direct, 2))
    base = sc.totals.get("subtotal_cost") or direct
    for cat in ("margin", "contingency"):
        amt = sum(l.amount or 0 for l in sc.lines if l.category == cat)
        if amt and base:
            sc.totals[f"{cat}_pct_effective"] = round(amt / base * 100, 2)
    if sc.final_total and direct:
        sc.totals["markup_on_direct_pct"] = round((sc.final_total / direct - 1) * 100, 2)
    if sc.final_total and sc.total_weight_kg:
        sc.totals["final_rate_per_kg"] = round(sc.final_total / sc.total_weight_kg, 2)


# --------------------------------------------------------------------- matrix layout

def _find_matrix_header(rows: list[Row]) -> tuple[int, int, dict[int, str], int | None] | None:
    for i, row in enumerate(rows):
        size = next((c for c in row.values() if c.is_text and re.fullmatch(r"size\s*:?", c.text.lower())), None)
        if not size:
            continue
        comps = {c.col: c.text for c in row.values() if c.is_text and c.col > size.col and c.text.lower() != "m2"
                 and not re.search(r"total", c.text.lower())}   # 'Total Weight' column is not a component
        area = next((c.col for c in row.values() if c.is_text and c.text.lower() in ("m2", "m\u00b2")), None)
        if len(comps) >= 2:
            return i, size.col, comps, area
    return None


_REF_TIMES_NUM = re.compile(r"=\s*\(?\s*\$?([A-Z]{1,3})\$?(\d+)\s*\)?\s*\*\s*(\d+(?:\.\d+)?)\s*(%?)\s*")
_NUM_TIMES_REF = re.compile(r"=\s*(\d+(?:\.\d+)?)\s*(%?)\s*\*\s*\(?\s*\$?([A-Z]{1,3})\$?(\d+)\s*\)?\s*")


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _matrix_basis(line: CostLine, cell: Cell, by_coord: dict, ctx: dict) -> None:
    """Read the basis and rate of one matrix cell from its formula.

    '=E10*2.8'  (E10 = weight row)      -> per_kg, rate 2.8, qty = kg
    '=I10*120'  (I = m2 column)         -> per_m2, rate 120, qty = m2
    '=E14*10%'  (E14 = another cost row) -> pct 10 of that row's category
    '=750*6'                            -> per_unit, rate 750, qty 6
    Anything else stays component_total (amount only)."""
    f = cell.formula
    if not f:
        line.flags.append("typed value, no formula: basis unknown")
        return
    lits = qty_formula_literals(f)
    if lits:
        line.basis, line.rate, line.qty = "per_unit", lits[0], lits[1]
        line.qty_literals = lits
        return
    m = _REF_TIMES_NUM.fullmatch(f)
    if m:
        col, row, num, pct = _col_index(m[1]), int(m[2]), float(m[3]), m[4]
    else:
        m = _NUM_TIMES_REF.fullmatch(f)
        if not m:
            return
        num, pct, col, row = float(m[1]), m[2], _col_index(m[3]), int(m[4])
    ref = by_coord.get((row, col))
    ref_val = float(ref.value) if ref is not None and ref.is_num else None
    if pct or row in ctx["cost_rows"]:
        line.basis = "pct"
        line.formula_pcts = [num if pct else round(num * 100, 4)]
        line.rate = line.formula_pcts[0]
        line.qty = ref_val
        line.uom = f"% of {ctx['cost_rows'].get(row, 'row ' + str(row))}"
        return
    if col == ctx["area_col"]:
        line.basis, line.uom = "per_m2", "m2"
    elif row in (ctx["total_row"], ctx["allowance_row"]):
        line.basis, line.uom = "per_kg", "kg"
        if row == ctx["allowance_row"]:
            line.flags.append(f"weight includes allowance x{ctx.get('allowance', '?')}")
    else:
        return
    line.rate, line.qty = num, ref_val
    if col == ctx["area_col"] and line.component and ctx["comp_col"].get(line.component) != col:
        line.flags.append(f"priced on the total m2 column, not on {line.component.strip()} only")


def parse_matrix_sheet(sheet: str, rows: list[Row], hdr) -> Scenario:
    i0, size_col, comps, area_col = hdr
    sc = Scenario(sheet=sheet, layout="matrix")
    comp_cols = sorted(comps)
    state = "items"
    comp_totals: dict[str, float] = {}
    by_coord = {(c.row, c.col): c for r in rows for c in r.values()}
    ctx = {"area_col": area_col, "total_row": None, "allowance_row": None, "cost_rows": {},
           "comp_col": {name: col for col, name in comps.items()}}
    for row in rows[i0 + 1:]:
        texts = [c for c in row.values() if c.is_text]
        low = [c.text.lower() for c in texts]
        if state == "items":
            if "total" in low:
                tot_cell = next(c for c in texts if c.text.lower() == "total")
                nums = [c for col, c in sorted(row.items()) if c.is_num and col > tot_cell.col]
                comp_totals = {comps[col]: float(row[col].value) for col in comp_cols if col in row and row[col].is_num}
                extra = [c for c in nums if c.col not in comp_cols and c.col != area_col]
                if extra:
                    sc.total_weight_kg = float(extra[0].value)
                ctx["total_row"] = tot_cell.row
                state = "categories"
                continue
            tag = next((c.text for col, c in sorted(row.items()) if c.is_text and col < size_col), None)
            dims = _txt(row, size_col)
            if tag is None and dims is None:
                continue
            comp = Component(tag=tag or "", dims_text=dims)
            m = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", dims or "", re.I)
            if m:
                comp.length_m, comp.width_m = float(m.group(1)), float(m.group(2))
                comp.footprint_m2 = round(comp.length_m * comp.width_m, 2)
            comp.area_m2 = _num(row, area_col)
            for col in comp_cols:
                v = _num(row, col)
                if v is not None:
                    comp.kg_by_component[comps[col]] = v
            sc.components.append(comp)
            continue
        # after the Total row
        lab = next((c for col, c in sorted(row.items()) if c.is_text and col < size_col), None)
        vals = {comps[col]: row[col] for col in comp_cols if col in row}
        if lab is None:
            nums = [c for c in row.values() if c.is_num]
            if vals and all(v.is_num for v in vals.values()) and comp_totals:
                ratios = [vals[k].value / comp_totals[k] for k in vals if comp_totals.get(k)]
                if ratios and max(ratios) - min(ratios) < 0.15 and 1.0 <= ratios[0] <= 1.5:
                    sc.totals["weight_allowance_factor"] = round(ratios[0], 3)
                    ctx["allowance_row"], ctx["allowance"] = next(iter(vals.values())).row, round(ratios[0], 3)
                    continue
            if area_col and area_col in row and row[area_col].is_num and len(vals) >= 2:
                if ctx.get("final_from_unlabelled"):
                    sc.warnings.append(f"{row[area_col].coord}: numeric row after the final total (scratch?)")
                    continue
                if "final_total" in sc.totals:      # labelled total above, this row is total + markup
                    sc.totals["subtotal_cost"] = sc.totals["final_total"]
                ctx["final_from_unlabelled"] = True
                sc.totals["final_total"] = float(row[area_col].value)
                after = [c for col, c in sorted(row.items()) if col > area_col and c.is_num]
                if after:
                    sc.totals["final_rate_per_kg_reported"] = float(after[0].value)
                continue
            if nums:
                sc.warnings.append(f"{nums[0].coord}: unlabelled numeric row")
            continue
        nums = [c for col, c in sorted(row.items()) if c.is_num and col > lab.col]
        if len(nums) >= 3 and all(c.is_num for c in nums[:3]) and nums[2].value and \
                abs(nums[0].value * nums[1].value - nums[2].value) / nums[2].value < 0.01:
            sc.options.append(Option(lab.text, float(nums[0].value), float(nums[1].value), float(nums[2].value), lab.row))
            continue
        cat = classify_label(lab.text)
        if cat in TOTAL_KINDS:               # 'Total price in AED' row: a total, not a cost line
            tot = _num(row, area_col) if area_col else None
            if tot is None:
                tot = sum(float(v.value) for v in vals.values() if v.is_num) or None
            if tot is not None:
                sc.totals[cat] = tot
            continue
        ctx["cost_rows"][lab.row] = cat or lab.text
        for name, cell in vals.items():
            if cell.is_num:
                line = CostLine(sheet=sheet, row=lab.row, label=lab.text, category=cat,
                                basis="component_total", amount=float(cell.value), component=name)
                _matrix_basis(line, cell, by_coord, ctx)
                sc.lines.append(line)
            elif cell.is_text and cell.text.upper() not in ("NA", "N/A", "-"):
                sc.scope[f"{cat or lab.text}:{name}"] = cell.text
    _matrix_checks(sc, comps, comp_totals)
    return sc


def _matrix_checks(sc: Scenario, comps: dict[int, str], comp_totals: dict[str, float]) -> None:
    sc.title = f"{len(sc.components)} units x {len(comps)} components"
    with_mat = sc.direct_cost()
    without_mat = sum(l.amount or 0 for l in sc.lines if l.category not in ("margin", "contingency", "material"))
    ft = sc.totals.get("final_total")
    ref = sc.totals.get("subtotal_cost") or ft
    if ft and sc.totals.get("subtotal_cost"):
        sc.totals["markup_on_direct_pct"] = round((ft / sc.totals["subtotal_cost"] - 1) * 100, 2)
    if ref:
        ft = ref
        if abs(with_mat - ft) / ft < 0.001:
            sc.scope["materials"] = "supplied"
        elif abs(without_mat - ft) / ft < 0.001:
            sc.scope["materials"] = "free_issue (material row shown but not in total)"
        else:
            sc.warnings.append(f"category rows sum to {with_mat:,.2f} (or {without_mat:,.2f} without material), sheet total {ft:,.2f}")
    present = {l.category for l in sc.lines if (l.amount or 0) != 0}
    sc.scope["galvanizing"] = "included" if "galvanizing" in present else "none"
    sc.scope["painting"] = "included" if "painting" in present else "none"
    sc.totals["direct_cost_sum"] = round(with_mat, 2)
    if not sc.total_weight_kg and sc.components:
        sc.total_weight_kg = sum(sum(c.kg_by_component.values()) for c in sc.components)
    if ft and sc.total_weight_kg:
        sc.totals["final_rate_per_kg"] = round(ft / sc.total_weight_kg, 2)


# --------------------------------------------------------------------- entry points

def parse_sheet(sheet: str, rows: list[Row]) -> Scenario:
    errors = [c for r in rows for c in r.values() if c.is_error]
    hdr = _find_matrix_header(rows)
    sc = parse_matrix_sheet(sheet, rows, hdr) if hdr else parse_list_sheet(sheet, rows)
    for c in errors:
        sc.warnings.append(f"{c.coord}: error value {c.value}")
    if not sc.lines and not sc.boq:
        sc.layout = "other"
    return sc


def inquiry_id_from_name(name: str) -> str | None:
    m = re.search(r"UEM[_\- ]?(\d{4,6})", name, re.I)
    return m.group(1) if m else None


def parse_workbook(path: str | Path) -> ParsedCosting:
    path = Path(path)
    parsed = ParsedCosting(file=path.name, inquiry_id=inquiry_id_from_name(path.name))
    for sheet, rows in read_workbook(path).items():
        parsed.scenarios.append(parse_sheet(sheet, rows))
    return parsed
