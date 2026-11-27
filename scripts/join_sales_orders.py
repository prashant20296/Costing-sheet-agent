"""Which Package 8 inquiries became sales orders?"""
import re

import pandas as pd

SO = r"D:\Costing_sheet\docs\Structural\Sales Order List.xlsx"
MAN = "data/interim/manifest_pkg8/manifest_inquiries.csv"

so = pd.read_excel(SO, usecols=["Title", "Inquiry Ref.", "SO Status", "Order Date"], dtype={"Inquiry Ref.": str})
inq = pd.read_csv(MAN, dtype={"inquiry_id": str})

ID = re.compile(r"(?<!\d)(1[1-4]\d{3})(?!\d)")     # a 5-digit inquiry no. 11000-14999, not part of a longer number


def find_id(row) -> pd.Series:
    """Inquiry id from 'Inquiry Ref.' first; if empty, try the Title."""
    for col in ("Inquiry Ref.", "Title"):
        m = ID.search(str(row[col]))
        if m:
            return pd.Series([m.group(1), col])
    return pd.Series([None, None])


so[["inquiry_id", "id_source"]] = so.apply(find_id, axis=1)
print(so["id_source"].value_counts(dropna=False), "\n")

# join: keep all 56 inquiries, add their orders (if any)
pkg8 = inq[["inquiry_id", "inv_customer_docs"]].merge(so, on="inquiry_id", how="left")
pkg8["won"] = pkg8["SO Status"].notna() & (pkg8["SO Status"] != "CANCELLED")
won = pkg8.groupby("inquiry_id")["won"].any()
print(won.value_counts(), "\n")
print(pkg8[pkg8["won"]][["inquiry_id", "SO Status", "Order Date", "id_source", "inv_customer_docs"]].to_string(index=False))
won.rename("won").reset_index().to_csv("data/interim/won_pkg8.csv", index=False)
print("saved data/interim/won_pkg8.csv")