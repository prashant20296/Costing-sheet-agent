# Costing-sheet-agent

Learn how each customer and product is costed from past costing sheets and offers, then use
that structure to draft new costing sheets and proposals.

## Principles
1. **Learn structure and quantities, not rates.** Size, weight, dimension, count, which cost
   categories a customer/product uses, and the basis of each (per kg, per m2, per hour, per lot, %).
2. **Rates are inputs.** Steel, galvanizing, paint, labour and transport prices change often, so the
   estimator enters them for each quote. Rates found in old sheets go to `*_rate_snapshot.csv`
   (a dated rate history), never into the estimating model.
3. **Never trust a folder.** Identifiers are read from inside each document and cross-checked.
4. **Flag, don't fix.** Every parser check reports a problem; none silently changes data.
5. **Generated drafts are tagged** `origin = system_draft` so they never enter training as real revisions.

## Layout
```
src/costing_agent/
  xlsx_reader.py    cells with values + formulas
  categories.py     label -> category (typo tolerant), basis, % helpers
  parse_costing.py  list layouts (BOQ / cost build-up) and matrix layouts (components x categories)
  checks.py         plate thickness vs weight, SHS/RHS mass, weight sums
  offer_reader.py   .docx/.doc/.pdf offer -> items, terms, exclusions
  reconcile.py      costing <-> offer matching, identifier checks
  report.py         CSV/JSON + parse_report.md
  cli.py            costing-agent parse / parse-folder
tests/
data/raw/           customer files (git-ignored)
data/interim/       parser outputs (git-ignored)
```

## Use
```bash
pip install -e .
costing-agent parse --costing data/raw/12686/UEM_12686_2025_R0_-_Costing_Sheet.xlsx \
                    --offer   data/raw/12686/UEM_12686_2025_R0_-_Techno_Commercial_Proposal.pdf \
                    --out data/interim
# or let it find the files in an inquiry folder
costing-agent parse-folder data/raw/12686 --out data/interim

COSTING_SAMPLES=../docs/Structural pytest     # sample-based tests (searches sub-folders)
```
`.doc` offers need LibreOffice (`soffice` on PATH or the default Windows install folder), or save them as `.docx`.

## Outputs (per inquiry)
`<id>_parse_report.md`, `<id>.json`, `<id>_cost_lines.csv`, `<id>_boq_lines.csv`,
`<id>_components.csv` (matrix layouts), `<id>_rate_snapshot.csv`.

## Known limits (v1)
- Four layouts tested (BOQ + build-up, profile/plate/bolt BOQ, per-kg list, component matrix).
  New layouts show up as `other` or as `unmapped label` flags; add synonyms in `categories.py`.
- Offer reading needs a price table with Description and Qty columns.
- Drawings, MTO files and weight workbooks are not parsed yet.
- Matrix layouts: basis and rate are read from each cell's formula (`=E10*2.8` per kg, `=E14*10%` pct,
  `=I10*120` per m2, `=750*6` per unit). Typed values or other formulas stay `component_total`.
- Offer items carry `table_no`; reports show them as `T<table>/<item>` because each scope item often
  has its own table numbered 01.
