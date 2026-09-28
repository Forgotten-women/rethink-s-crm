import sqlite3
import pandas as pd
import os

db_path = '/home/ubuntu/Python_Visualization/launchgood_donations.db'
parquet_path = '/home/ubuntu/Python_Visualization/donations_cache.parquet'

print("--- 1. Check Platform Campaign Mappings for Iqra ---")
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT platform, count(*) FROM platform_campaign_mappings WHERE company_id = 'iqra' GROUP BY platform")
print("Iqra mappings count by platform:", cur.fetchall())

cur.execute("SELECT DISTINCT platform, campaign_name FROM platform_campaign_mappings WHERE company_id = 'iqra'")
iqra_campaign_rows = cur.fetchall()
iqra_camp_dict = {}
for p, c in iqra_campaign_rows:
    if c:
        iqra_camp_dict[c.strip().lower()] = p

print(f"Total unique Iqra campaigns mapped: {len(iqra_camp_dict)}")

print("\n--- 2. Check Parquet Donations ---")
df = pd.read_parquet(parquet_path)
print("Total rows in Parquet:", len(df))
print("Current company_id in Parquet:\n", df['company_id'].value_counts(dropna=False))
print("Platforms in Parquet:\n", df['Platform'].value_counts(dropna=False))

c_col = 'Campaign Title' if 'Campaign Title' in df.columns else 'Campaign'
camp_series = df[c_col].fillna('').astype(str).str.strip().str.lower()

matched_mask = camp_series.isin(set(iqra_camp_dict.keys()))
print(f"Total donations matching Iqra mapped campaigns: {matched_mask.sum()}")
matched_df = df[matched_mask]
print("Matched donations by Platform:\n", matched_df['Platform'].value_counts())
print("Matched donations by current company_id:\n", matched_df['company_id'].value_counts())

print("\n--- 3. Check All GiveBright Donations ---")
gb_df = df[df['Platform'] == 'GiveBright']
print(f"Total GiveBright donations: {len(gb_df)}")
print("GiveBright company_id distribution:\n", gb_df['company_id'].value_counts())

print("\n--- 4. Check Madinah Donations ---")
mad_df = df[df['Platform'].fillna('').astype(str).str.lower().str.contains('madinah')]
print(f"Donations with Platform containing 'madinah': {len(mad_df)}")

# Check if Campaign Title contains Madinah or Iqra
iqra_name_df = df[camp_series.str.contains('iqra') | camp_series.str.contains('madinah')]
print(f"Donations where Campaign Title contains 'iqra' or 'madinah': {len(iqra_name_df)}")
print(iqra_name_df[['Platform', c_col, 'company_id']].head(20))

conn.close()
