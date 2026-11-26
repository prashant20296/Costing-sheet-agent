import pandas as pd

df = pd.read_csv("data/interim/manifest_pkg8/manifest_inquiries.csv", dtype={"inquiry_id": str})

print(df.shape)                                   # (rows, columns)
print(df["parse_ready"].value_counts())           # how many True / False

not_ready = df[df["parse_ready"] == False]        # filter rows
print(not_ready[["inquiry_id", "inv_all_three", "flags"]].to_string())

flagged = df[df["flags"].notna()]                 # rows where flags is not empty
print(len(flagged), "inquiries have flags")