from costing_agent.models import ParsedCosting, Scenario
from costing_agent.offer_reader import Offer, OfferItem
from costing_agent.reconcile import reconcile


def _offer(*totals):
    items = [OfferItem(f"{i:02d}", f"item {i}", 1, "Lot", t, t) for i, t in enumerate(totals, 1)]
    return Offer(file="offer.docx", offer_ref="12016", items=items)


def test_one_tab_prices_the_whole_offer():
    # 12016 pattern: the costing tab total equals the sum of all offer lines
    sc = Scenario(sheet="Sheet1", layout="cost_list", totals={"final_total": 3_195_204.0})
    parsed = ParsedCosting(file="costing.xlsx", inquiry_id="12016", scenarios=[sc])
    rec = reconcile(parsed, _offer(900_000, 600_000, 800_000, 495_204, 400_000))

    assert rec.total_match is not None
    assert rec.total_match.gap_pct == 0.0
    assert rec.best_scenario == "Sheet1 / final total"
    assert rec.explained_share_pct == 100.0


def test_item_level_match_still_works():
    # 11731 pattern: one tab = offer line 1, other lines priced elsewhere
    sc = Scenario(sheet="6 Module", layout="cost_list", totals={"final_total": 49_792.63})
    parsed = ParsedCosting(file="c.xlsx", inquiry_id="11731", scenarios=[sc])
    rec = reconcile(parsed, _offer(49_800, 26_000, 5_280, 6_500, 5_500))

    assert rec.matches[0].best_source == "Sheet1 / final total".replace("Sheet1", "6 Module")
    assert rec.total_match is None          # 49,793 is far from the 93,080 offer sum