"""Map free-text labels (with typos) to a standard cost category, and read bases/percentages."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# Order matters: first match wins.
CATEGORY_KEYWORDS = [
    ("margin", ["margin", "profit"]),
    ("contingency", ["contingency", "contyngency", "contingencies"]),
    ("cutting_service", ["waterjet", "laser", "plasma"]),
    ("ndt", ["ndt", "dpi", "mpi", "radiography", "inspection", "testing"]),
    ("galvanizing", ["galvanizing", "galvanising", "galvanized", "hdg"]),
    ("painting", ["painting", "paint", "coating", "blasting"]),
    ("transport", ["transport", "transportation", "logistics", "delivery"]),
    ("handling_packing", ["handling", "packing", "crate", "pallet"]),
    ("design_calc", ["calculation", "engineering", "design"]),
    ("ddp", ["ddp"]),
    ("consumables", ["welding", "consumable", "consumables", "electrode"]),
    ("fabrication_labour", ["manhours", "manhour", "labour", "labor", "fabrication"]),
    ("material", ["material", "materials"]),
]

# Totals and sub-totals: stored in scenario.totals, never as cost lines.
TOTAL_KINDS = {
    "final_total", "subtotal_cost", "unit_price_per_set", "unit_rate_per_kg",
    "labour_subtotal", "misc_subtotal", "material_subtotal",
}

# A text cell that is only a unit ('Kgs.', 'Lot.') is not a row label.
UNIT_TOKEN = re.compile(r"^(kgs?|lots?|nos?|hrs?|hours?|m2|sqm|mtr|m|visit|pcs)\.?$", re.I)

UOM_BASIS = {
    "kg": "per_kg", "kgs": "per_kg", "m2": "per_m2", "sqm": "per_m2",
    "hr": "per_hour", "hrs": "per_hour", "hour": "per_hour", "hours": "per_hour",
    "lot": "per_lot", "lots": "per_lot", "nos": "per_unit", "no": "per_unit", "pcs": "per_unit",
    "visit": "per_visit", "mtr": "per_m", "m": "per_m",
}


def _norm(label: str) -> str:
    s = re.sub(r"[^a-z0-9%\s]", " ", (label or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _tok_match(token: str, kw: str) -> bool:
    if token == kw:
        return True
    return len(token) >= 5 and len(kw) >= 5 and SequenceMatcher(None, token, kw).ratio() >= 0.84


def _has(tokens, keywords) -> bool:
    return any(_tok_match(t, k) for t in tokens for k in keywords)


def classify_label(label: str):
    """Return a category, a total kind (see TOTAL_KINDS), or None when the label is unknown."""
    n = _norm(label)
    if not n:
        return None
    if "unit rate" in n:
        return "unit_rate_per_kg"
    if n.startswith("unit price"):
        return "unit_price_per_set"
    if re.search(r"manhours? total|total manhours?", n):
        return "labour_subtotal"
    if "miscellaneous" in n:
        return "misc_subtotal"
    if "grand total" in n or n in ("total", "total price") or n.startswith("total price"):
        return "final_total"
    if n == "grand" or re.search(r"^total cost|total cost$", n):
        return "subtotal_cost"
    if re.fullmatch(r"materials? cost", n):
        return "material_subtotal"
    tokens = n.replace("%", " % ").split()
    if "cutting" in tokens and (_has(tokens, ["allowance"]) or "scrap" in tokens):
        return "cutting_allowance"
    for cat, kws in CATEGORY_KEYWORDS:
        if _has(tokens, kws):
            return cat
    if "water" in tokens and "jet" in tokens:
        return "cutting_service"
    return None


def basis_from_uom(uom):
    u = re.sub(r"[^a-z0-9]", "", (uom or "").lower())
    return UOM_BASIS.get(u)


def label_percent(label: str):
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", label or "")
    return float(m.group(1)) if m else None


def formula_percents(formula) -> list:
    """Percentages implied by one formula: '*7%' -> 7, '*1.1' -> 10, '*0.07' -> 7."""
    if not formula:
        return []
    out = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", formula)]
    out += [round((float(m) - 1) * 100, 2) for m in re.findall(r"\*\s*(1\.\d+)\b", formula)]
    out += [round(float(m) * 100, 2) for m in re.findall(r"\*\s*(0\.\d+)\b", formula)]
    return out


def qty_formula_literals(formula):
    """'=5*90' -> (5.0, 90.0): a quantity typed as two literals (for example crew x hours)."""
    if not formula:
        return None
    m = re.fullmatch(r"=\s*(\d+(?:\.\d+)?)\s*\*\s*(\d+(?:\.\d+)?)\s*", formula)
    return (float(m.group(1)), float(m.group(2))) if m else None
