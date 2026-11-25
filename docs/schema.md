# Parser output schema (v1)

| table | key fields |
|---|---|
| cost_lines | sheet, row, label, category, basis, qty, uom, rate, amount, component, label_pct, formula_pcts, qty_literals, flags |
| boq_lines | sheet, row, item_no, part_no, description, material, length, width, nos, qty, sets, total_qty, unit_weight, total_weight_kg, total_area_m2, unit_price, amount |
| components | sheet, tag, dims_text, length_m, width_m, footprint_m2, area_m2, kg_<component> |
| rate_snapshot | inquiry_id, sheet, component, category, basis, value, uom, offer_date, customer |
| offer_items | table_no, item_no (key = T<table>/<item>), description, qty, unit, rate, total |
| scenario totals | final_total, subtotal_cost, direct_cost_sum, margin_pct_effective, contingency_pct_effective, markup_on_direct_pct, final_rate_per_kg, weight_allowance_factor |
| scenario scope | materials (supplied / free_issue), galvanizing, painting |

Categories: material, cutting_allowance, consumables, cutting_service, fabrication_labour, galvanizing,
painting, ndt, transport, handling_packing, design_calc, ddp, margin, contingency.
Bases: per_kg, per_m2, per_hour, per_lot, per_visit, per_unit, pct, component_total.
