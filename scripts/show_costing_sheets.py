"""Print each tab of a costing workbook: size and its first non-empty rows."""
import sys

import openpyxl

path = sys.argv[1]
max_rows = int(sys.argv[2]) if len(sys.argv) > 2 else 12

wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
for ws in wb.worksheets:
    print(f"\n=== tab '{ws.title}': {ws.max_row} rows x {ws.max_column} cols")
    shown = 0
    for r_no, row in enumerate(ws.iter_rows(values_only=True), start=1):
        cells = [str(v).strip()[:20] for v in row if v not in (None, "")]
        if not cells:
            continue
        print(f"{r_no:>4}: " + " | ".join(cells[:10]))
        shown += 1
        if shown >= max_rows:
            break