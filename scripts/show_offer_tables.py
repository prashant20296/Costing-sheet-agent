import sys
from pathlib import Path

from costing_agent.offer_reader import _convert_doc, _read_docx, _read_pdf

path = Path(sys.argv[1])
src = _convert_doc(path) if path.suffix.lower() == ".doc" else path
text, tables = _read_pdf(src) if src.suffix.lower() == ".pdf" else _read_docx(src)

print(f"{len(tables)} tables found")
for n, t in enumerate(tables, start=1):
    print(f"\n--- table {n}: {len(t)} rows")
    for row in t:                       # first 4 rows are enough to see the header
        print(" | ".join(c.replace("\n", " ")[:25] for c in row))