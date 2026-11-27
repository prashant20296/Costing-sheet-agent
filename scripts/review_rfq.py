"""Where do customer (RFQ) documents sit, and what kinds of files are they?"""
import pandas as pd

DIR = "data/interim/manifest_pkg8"
inq = pd.read_csv(f"{DIR}/manifest_inquiries.csv", dtype={"inquiry_id": str})
files = pd.read_csv(f"{DIR}/manifest_files.csv", dtype={"inquiry_id": str})

# 1. inquiries with / without customer docs, per the inventory
print(inq["inv_customer_docs"].value_counts(dropna=False), "\n")

# 2. first folder below the inquiry folder, e.g. 'R0', 'RFQ', 'Customer docs'
parts = files["rel_path"].str.replace("\\", "/", regex=False).str.split("/")
files["top_folder"] = parts.str[0].where(parts.str.len() > 1, "(root)")
files = files.merge(inq[["inquiry_id", "inv_customer_docs"]], on="inquiry_id")

# 3. most common top folders, only where the inventory says customer docs exist
y = files[files["inv_customer_docs"] == "Y"]
print(y["top_folder"].str.lower().value_counts().head(25), "\n")

# 4. file labels split by 'has customer docs' Y / N
print(pd.crosstab(files["label"], files["inv_customer_docs"]))