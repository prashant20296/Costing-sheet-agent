"""Run against real inquiry folders. Point COSTING_SAMPLES at a folder holding the files
(they are customer data and are never committed). Tests are skipped when it is not set."""
import os
from pathlib import Path

import pytest

from costing_agent.offer_reader import read_offer
from costing_agent.parse_costing import parse_workbook
from costing_agent.reconcile import reconcile

ROOT = Path(os.environ.get("COSTING_SAMPLES", ""))
pytestmark = pytest.mark.skipif(not ROOT.is_dir(), reason="COSTING_SAMPLES not set")


def _first(pattern: str) -> Path:
    return next(p for p in sorted(ROOT.rglob(pattern)) if not p.name.startswith("~$"))


def test_11731_boq_with_manual_buildup():
    p = parse_workbook(_first("UEM_11731*Costing*.xlsx"))
    s = next(x for x in p.scenarios if x.layout == "boq_list")
    assert len(s.boq) == 22 and s.sets == 8
    assert s.final_total == pytest.approx(49792.63, abs=0.01)
    assert s.total_weight_kg == pytest.approx(4859.43, abs=0.01)
    assert any("4%" in f and "3%" in f for l in s.lines for f in l.flags)
    assert not [w for w in s.warnings if "sum" in w]


def test_13331_profiles_and_margin_flags():
    p = parse_workbook(_first("UEM_13331*Costing*.xlsx"))
    s = p.scenarios[0]
    assert s.final_total == pytest.approx(301973.14, abs=0.01)
    assert s.totals["margin_pct_effective"] == pytest.approx(10.0)
    flags = [f for l in s.lines for f in l.flags]
    assert any("Margin" not in f and "10" in f for f in flags)


def test_12686_all_per_kg_lines():
    s = parse_workbook(_first("UEM_12686*Costing*.xlsx")).scenarios[0]
    assert s.layout == "cost_list" and s.final_total == pytest.approx(212816.80, abs=0.01)
    assert s.total_weight_kg == pytest.approx(17080)


def test_12960_matrix_and_offer_link():
    p = parse_workbook(_first("UEM_12960*Costing*.xlsx"))
    matrices = [s for s in p.scenarios if s.layout == "matrix"]
    assert len(matrices) == 3
    offer = read_offer(_first("UEM_12960*Proposal*.docx"))
    rec = reconcile(p, offer)
    assert rec.best_scenario and "Without Materials" in rec.best_scenario
    assert rec.id_flags, "file name 12960 should disagree with offer ref 13027"


def test_12960_matrix_rates_from_formulas():
    s = next(x for x in parse_workbook(_first("UEM_12960*Costing*.xlsx")).scenarios if x.sheet == "Without Materials")
    by = {(l.category, l.component.strip()): l for l in s.lines}
    steel = by[("material", "Structural")]
    assert steel.basis == "per_kg" and steel.rate == pytest.approx(2.8) and steel.qty == pytest.approx(11550)
    assert by[("material", "Drip tray")].rate == pytest.approx(17.0)
    weld = by[("consumables", "Structural")]
    assert weld.basis == "pct" and weld.rate == pytest.approx(10.0)
    assert by[("fabrication_labour", "Grating")].rate == pytest.approx(6.5)
    paint_tray = by[("painting", "Drip tray")]
    assert paint_tray.basis == "per_m2" and paint_tray.rate == pytest.approx(120)
    assert any("total m2" in f for f in paint_tray.flags)
    assert by[("ndt", "Structural")].basis == "per_unit"


def test_11731_offer_items_per_table():
    o = read_offer(_first("UEM_11731*Proposal*.pdf"))
    assert [it.key for it in o.items] == ["T1/01", "T2/01", "T3/01", "T4/01", "T5/01"]
    assert o.items[0].qty == 8 and o.items[0].rate == pytest.approx(6225)
    assert "Galvanizing" in o.items[0].description
    assert "Painting" in o.items[1].description
    assert sum(it.total for it in o.items) == pytest.approx(93080)


def test_find_files_skips_lock_files():
    from costing_agent.cli import find_files
    folder = _first("UEM_11731*Costing*.xlsx").parent
    costing, offers = find_files(folder)
    assert len(costing) == 1 and not costing[0].name.startswith("~$")
