import pandas as pd

df = pd.read_csv("data/interim/batch_pkg8/batch_summary.csv",
                 dtype={"inquiry_id": str, "offer_ref": str})

print("inquiries:", len(df))
print(df["status"].value_counts(), "\n")

# 1. Did the parser understand the workbook?
no_layout = df[df["costed_tabs"] == 0]
print("no costing table recognised:", list(no_layout["inquiry_id"]), "\n")

# 2. How close is costing to offer?
bins   = [-0.01, 1, 3, 6]
labels = ["<=1%", "1-3%", "3-6%"]
df["match"] = pd.cut(df["best_gap_pct"], bins=bins, labels=labels)
df["match"] = df["match"].cat.add_categories("no match").fillna("no match")
print(df["match"].value_counts().sort_index(), "\n")

# 3. Folder identity: offer ref printed inside the offer vs folder name
clash = df[df["offer_ref"].notna() & (df["offer_ref"] != df["inquiry_id"])]
print("offer ref differs from folder:")
print(clash[["inquiry_id", "offer_ref"]].to_string(index=False), "\n")

# 4. The ones to look at by hand
cols = ["inquiry_id", "layouts", "final_total", "offer_total", "best_gap_pct", "explained_pct"]
print(df[df["match"] == "no match"][cols].to_string(index=False))