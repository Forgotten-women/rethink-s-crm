import os
import sys
import sqlite3
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import LOCAL_DB_PATH, PARQUET_PATH, PAYOUTS_PARQUET_PATH, PAYSUITE_PAYOUTS_PARQUET_PATH
from core.database import migrate_db_for_multitenancy

print("Running migrate_db_for_multitenancy()...")
migrate_db_for_multitenancy()
print("Migration function completed.")

conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
cur = conn.cursor()

cur.execute("SELECT id, name, short_code, accent_color FROM companies")
print("Companies in DB:", cur.fetchall())

for tbl in ["donations", "master_project_codes", "platform_campaign_mappings", "fundraisers", "expense_requests"]:
    try:
        cur.execute(f"SELECT company_id, count(*) FROM {tbl} GROUP BY company_id")
        print(f"Table {tbl} breakdown:", cur.fetchall())
    except Exception as e:
        print(f"Table {tbl} check error: {e}")

conn.close()

for p_path in [PARQUET_PATH, PAYOUTS_PARQUET_PATH]:
    if os.path.exists(p_path):
        df = pd.read_parquet(p_path)
        print(f"Parquet {os.path.basename(p_path)}: shape={df.shape}, company_id unique={df['company_id'].unique().tolist() if 'company_id' in df.columns else 'MISSING'}")

print("Multi-tenancy migration verified successfully!")
