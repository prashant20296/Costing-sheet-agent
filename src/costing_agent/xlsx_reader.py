"""Read a workbook as {sheet: [Row]} where Row = {column: Cell}, with cached values AND formulas.

Layout is never assumed from cell addresses: callers detect headers from text.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import openpyxl

ERROR_TOKENS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!")


@dataclass
class Cell:
    coord: str
    row: int
    col: int
    value: object
    formula: Optional[str] = None

    @property
    def is_error(self) -> bool:
        return isinstance(self.value, str) and self.value.strip() in ERROR_TOKENS

    @property
    def is_num(self) -> bool:
        return isinstance(self.value, (int, float)) and not isinstance(self.value, bool)

    @property
    def is_text(self) -> bool:
        return isinstance(self.value, str) and bool(self.value.strip()) and not self.is_error

    @property
    def text(self) -> str:
        return self.value.strip() if isinstance(self.value, str) else ""


Row = dict  # {col_index: Cell}


def read_workbook(path: str | Path) -> dict:
    path = str(path)
    wf = openpyxl.load_workbook(path)                       # formulas
    wv = openpyxl.load_workbook(path, data_only=True)       # cached values
    sheets: dict = {}
    for ws in wv.worksheets:
        wsf = wf[ws.title]
        rows: dict = {}
        for row in ws.iter_rows():
            for c in row:
                f = wsf[c.coordinate].value
                formula = f if isinstance(f, str) and f.startswith("=") else None
                if c.value is None and formula is None:
                    continue
                rows.setdefault(c.row, {})[c.column] = Cell(c.coordinate, c.row, c.column, c.value, formula)
        sheets[ws.title] = [rows[r] for r in sorted(rows)]
    return sheets
