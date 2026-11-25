"""Sanity checks on parsed BOQ lines. These flag problems; they never change data."""
from __future__ import annotations

import re

from .models import Scenario

STEEL_KG_PER_M2_PER_MM = 7.85


def hollow_section_kg_per_m(b: float, h: float, t: float) -> float:
    """Approximate mass of SHS/RHS (sharp corners): t*(2(b+h)-4t) mm2 * 7.85 g/cm3."""
    area_mm2 = t * (2 * (b + h) - 4 * t)
    return area_mm2 * 0.00785


def check_boq(sc: Scenario) -> list[str]:
    out: list[str] = []
    for b in sc.boq:
        d = b.description or ""
        loc = f"{b.sheet} row {b.row}"
        m = re.search(r"(SHS|RHS)\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", d, re.I)
        if m and b.unit_weight:
            expected = hollow_section_kg_per_m(float(m[2]), float(m[3]), float(m[4]))
            if abs(b.unit_weight - expected) / expected > 0.08:
                out.append(f"{loc}: '{d.strip()}' listed at {b.unit_weight:g} kg/m, expected about {expected:.2f} "
                           f"({(b.unit_weight / expected - 1) * 100:+.0f}%) - check section size or weight")
            continue
        m = re.search(r"plate.*?(\d+(?:\.\d+)?)\s*mm\s*thick", d, re.I)
        if m and b.unit_weight:
            t_label = float(m[1])
            t_implied = b.unit_weight / STEEL_KG_PER_M2_PER_MM
            if abs(t_implied - t_label) / t_label > 0.03:
                out.append(f"{loc}: label says {t_label:g} mm but unit weight {b.unit_weight:g} kg/m2 implies {t_implied:.1f} mm")
    m = re.search(r"(\d[\d,]*)\s*no'?s\b", sc.title or "", re.I)
    if m and sc.sets:
        n = float(m.group(1).replace(",", ""))
        if abs(n - sc.sets) > 0.5:
            out.append(f"{sc.sheet}: title says {n:,.0f} Nos but the sheet multiplies by {sc.sets:g} sets")
    if sc.boq:
        s = sum(b.total_weight_kg or 0 for b in sc.boq)
        if sc.total_weight_kg and abs(s - sc.total_weight_kg) / sc.total_weight_kg > 0.001:
            out.append(f"{sc.sheet}: BOQ line weights sum to {s:,.1f} kg, sheet total {sc.total_weight_kg:,.1f} kg")
    return out
