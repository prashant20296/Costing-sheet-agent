from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BOQLine:
    sheet: str
    row: int
    item_no: Optional[str] = None
    part_no: Optional[str] = None
    description: Optional[str] = None
    material: Optional[str] = None
    length: Optional[float] = None
    width: Optional[float] = None
    nos: Optional[float] = None
    qty: Optional[float] = None
    uom: Optional[str] = None
    sets: Optional[float] = None
    total_qty: Optional[float] = None
    unit_weight: Optional[float] = None
    total_weight_kg: Optional[float] = None
    unit_area: Optional[float] = None
    total_area_m2: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


@dataclass
class CostLine:
    sheet: str
    row: int
    label: str
    category: Optional[str]
    basis: Optional[str] = None          # per_kg, per_m2, per_hour, per_lot, per_unit, per_visit, pct, component_total
    qty: Optional[float] = None
    uom: Optional[str] = None
    rate: Optional[float] = None         # as typed in the sheet; goes to rate history, never to the model
    amount: Optional[float] = None
    component: Optional[str] = None      # matrix layouts: structural / ladder / grating ...
    label_pct: Optional[float] = None
    formula_pcts: list = field(default_factory=list)
    qty_literals: Optional[tuple] = None  # (5, 90) from "=5*90"
    flags: list = field(default_factory=list)


@dataclass
class Component:
    tag: str
    dims_text: Optional[str] = None
    length_m: Optional[float] = None
    width_m: Optional[float] = None
    footprint_m2: Optional[float] = None
    area_m2: Optional[float] = None
    kg_by_component: dict = field(default_factory=dict)


@dataclass
class Option:
    """A priced option typed inside a costing sheet (for example 'Fabrication only' at AED/tonne)."""
    label: str
    rate_per_tonne: float
    tonnes: float
    total: float
    row: int = 0


@dataclass
class Scenario:
    sheet: str
    layout: str = "other"                # boq_list | cost_list | matrix | other
    title: Optional[str] = None
    boq: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    components: list = field(default_factory=list)
    options: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    scope: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    total_weight_kg: Optional[float] = None
    sets: Optional[float] = None

    @property
    def final_total(self) -> Optional[float]:
        return self.totals.get("final_total")

    def direct_cost(self) -> float:
        return sum(l.amount or 0 for l in self.lines if l.category not in ("margin", "contingency"))


@dataclass
class ParsedCosting:
    file: str
    inquiry_id: Optional[str]
    scenarios: list = field(default_factory=list)
