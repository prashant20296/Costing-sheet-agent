import pytest

from costing_agent.manifest import FileRow, _pick, id_from_name, label_from_name, rev_from_name


@pytest.mark.parametrize("name,label", [
    ("UEM_12686_2025_R0 - Costing Sheet.xlsx", "costing_sheet"),
    ("13269_GRP Battery Boxs_Pricing.xlsx", "costing_sheet"),
    ("UEM_12686_2025_R0 - Techno Commercial Proposal.pdf", "offer_letter"),
    ("UEM_11969_2024_R0 - Technical Proposal.doc", "technical_proposal"),
    ("LOT-4 Instrument supports weightage WORKING.xlsx", "weight_workbook"),
    ("Furnace Area Instrument Stands MTO_Master.xlsx", "mto"),
    ("12215_R0 BOQ of support.xlsx", "bom"),
    ("141-MY-582-00001 - PAINTING SPECIFICATION.pdf", "client_spec"),
    ("141-IU-251-00001 - LOT-4 INSTRUMENT SUPPORT TYPICALS.pdf", "typicals_drawing"),
    ("frame.dwg", "drawing"),
    ("RE inquiry.msg", "correspondence"),
    ("12641_R0_Price sheet.xlsx", "costing_sheet"),
    ("UEM_12755_R0_Offer.xlsx", "offer_letter"),
])
def test_labels(name, label):
    assert label_from_name(name) == label


def test_ids_and_revs():
    assert id_from_name("UEM_12686_2025_R0 - Costing Sheet.xlsx") == "12686"
    assert id_from_name("UEM_137030_2026_R1 - Costing Sheet.xlsx") == "137030"   # malformed, flagged later
    assert id_from_name("12215_R0 BOQ of support.xlsx") == "12215"
    assert rev_from_name("UEM_12850_2025_R3- Techno Commercial Proposal.docx") == 3
    assert rev_from_name("Costing Sheet.xlsx") is None


def _f(name, rev, ext=".docx", mod="2025-01-01", id_="12000"):
    return FileRow("12000", name, name, ext, 1.0, mod, "offer_letter", rev=rev, id_in_name=id_)


def test_pick_latest_rev_then_own_id_then_format():
    files = [_f("a", 0), _f("b", 2, ".pdf"), _f("c", 2, ".docx", id_="11413"), _f("d", 2, ".docx")]
    assert _pick(files, "offer_letter", "12000", {".docx": 0, ".pdf": 1, ".doc": 2}).name == "d"
from costing_agent.manifest import role_from


@pytest.mark.parametrize("label, name, role", [
    ("costing_sheet", "UEM_11881_2024_R0 - Costing Sheet.xlsx", "uem_output"),
    ("offer_letter", "UEM_11881_2024_R0 - Techno Commercial Proposal.doc", "uem_output"),
    ("technical_proposal", "UEM_12016_2024_R0 - Technical Proposal.doc", "uem_output"),
    ("bom", "BOM.xlsx", "customer_input"),
    ("drawing", "SR-231018-POLE-GA-001.pdf", "customer_input"),
    ("other", "RFQ docs.zip", "customer_input"),
    ("weight_workbook", "LOT-4 Instrument supports weightage WORKING.xlsx", "check"),
])
def test_role_from(label, name, role):
    assert role_from(label, name) == role