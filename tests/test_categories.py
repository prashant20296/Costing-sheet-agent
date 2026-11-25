import pytest

from costing_agent.categories import classify_label, formula_percents, qty_formula_literals, label_percent
from costing_agent.checks import hollow_section_kg_per_m


@pytest.mark.parametrize("label,expected", [
    ("Trasnportation", "transport"),
    ("Transportation and Handling Cost", "transport"),
    ("Welding Cunsuamable 8%", "consumables"),
    ("4% Welding Consumable Cost", "consumables"),
    ("Contygency", "contingency"),
    ("Contingency cost (2%)", "contingency"),
    ("Galvanisig", "galvanizing"),
    ("HDG", "galvanizing"),
    ("Manhours Panel", "fabrication_labour"),
    ("Structrual Calculation", "design_calc"),
    ("Water Jet cutting", "cutting_service"),
    ("Cutting allowance 5%", "cutting_allowance"),
    ("Materials Cost with 5% allowance", "material"),
    ("NDT:10% DPI base plate weld", "ndt"),
    ("Grand total (Dirhams)", "final_total"),
    ("Total ", "final_total"),
    ("Grand ", "subtotal_cost"),
    ("Total cost", "subtotal_cost"),
    ("Unit Price in AED ", "unit_price_per_set"),
    ("Unit RateiKgs.", "unit_rate_per_kg"),
])
def test_classify(label, expected):
    assert classify_label(label) == expected


def test_formula_helpers():
    assert formula_percents("=P37*2%") == [2.0]
    assert formula_percents("=SUM(Q4:Q11)*1.1") == [10.0]
    assert qty_formula_literals("=5*90") == (5.0, 90.0)
    assert qty_formula_literals("=A1*90") is None
    assert label_percent("Margin (10%)") == 10.0


def test_hollow_section_mass():
    assert hollow_section_kg_per_m(100, 100, 4) == pytest.approx(12.06, abs=0.05)


def test_offer_header_cols_with_merged_columns():
    from costing_agent.offer_reader import _header_cols, _price_items
    hdr = ["S. No", "Description", "", "", "Qty.", "Unit Price in\nAED", "Total Amount in\nAED"]
    assert _header_cols(hdr) == {"item": 0, "desc": 1, "qty": 4, "rate": 5, "total": 6}
    table = [hdr, ["01", "", "Module Support:", "", "08 Nos.", "6,225.00", "49,800.00"],
             [None, None, "Supply and HDG", None, None, None, None],
             ["", "Grand Total price in AED", None, None, "", "", "49,800.00"]]
    items, grands = _price_items([table])
    assert items[0].qty == 8 and items[0].description == "Module Support: Supply and HDG"
    assert grands == [49800.0]
