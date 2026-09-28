#!/usr/bin/env python3
"""
scripts/migrate_payout_codes.py
Migrates all legacy 2/3-part codes in payout_settlements and payouts_cache.parquet
to official 4-part master project codes using platform_campaign_mappings and master_project_codes.
"""

import os
import sys
import sqlite3
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.utils import fix_mojibake
from core.data_processor import atomic_write_parquet, sanitize_df_dtypes_for_parquet
from config.settings import LOCAL_DB_PATH, PAYOUTS_PARQUET_PATH
from backend.api.payouts import LEGACY_PAYOUT_CODE_MAP, invalidate_payouts_cache

def migrate_payouts():
    print("=" * 70)
    print("  LAUNCHGOOD PAYOUT CODES MIGRATION")
    print("=" * 70)

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cur = conn.cursor()

    # 1. Master project codes lookup
    cur.execute("SELECT code, department, office, country, zakat_eligibility FROM master_project_codes")
    master_codes_map = {}
    for r in cur.fetchall():
        if r[0]:
            c_up = str(r[0]).strip().upper()
            master_codes_map[c_up] = {
                "code": c_up,
                "heading": r[1] or "Unassigned",
                "sub_heading": r[2] or "Unassigned",
                "country": r[3] or "Unassigned",
                "zakat_eligibility": r[4] or "Unassigned"
            }

    # 2. Platform campaign mappings for launchgood
    cur.execute("""
        SELECT LOWER(TRIM(campaign_name)), UPPER(TRIM(code)), is_primary 
        FROM platform_campaign_mappings 
        WHERE platform = 'launchgood' OR platform IS NULL OR platform = ''
        ORDER BY is_primary ASC
    """)
    camp_map = {}
    for cname, code, is_pri in cur.fetchall():
        c_clean = fix_mojibake(cname).strip().lower()
        raw_code = str(code or "").strip().upper()
        mapped_code = LEGACY_PAYOUT_CODE_MAP.get(raw_code, raw_code)
        if c_clean and mapped_code:
            camp_map[c_clean] = mapped_code

    print(f"Loaded {len(master_codes_map)} master codes and {len(camp_map)} campaign mappings.")

    # 3. Migrate SQLite payout_settlements table
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payout_settlements'")
    if cur.fetchone():
        df_payouts = pd.read_sql_query("SELECT * FROM payout_settlements", conn)
        if not df_payouts.empty:
            print(f"Migrating {len(df_payouts):,} rows in SQLite 'payout_settlements' table...")
            
            c_names = df_payouts["Campaign Name"].astype(str).str.strip().str.lower().apply(fix_mojibake)
            codes = df_payouts["Code"].astype(str).str.strip().str.upper()

            migrated_codes = []
            migrated_headings = []
            migrated_subheadings = []
            migrated_countries = []
            migrated_zakats = []

            for idx, (cn, cc) in enumerate(zip(c_names, codes)):
                # 1. Resolve from campaign mapping
                target_code = camp_map.get(cn)
                # 2. Fallback to legacy dictionary
                if not target_code or target_code not in master_codes_map:
                    target_code = LEGACY_PAYOUT_CODE_MAP.get(cc, cc)

                meta = master_codes_map.get(target_code, {
                    "code": target_code,
                    "heading": df_payouts.iloc[idx].get("Heading", "Unassigned"),
                    "sub_heading": df_payouts.iloc[idx].get("Sub-Heading", "Unassigned"),
                    "country": df_payouts.iloc[idx].get("Country", "Unassigned"),
                    "zakat_eligibility": df_payouts.iloc[idx].get("Zakat Eligibility", "Unassigned")
                })

                migrated_codes.append(meta["code"])
                migrated_headings.append(meta["heading"])
                migrated_subheadings.append(meta["sub_heading"])
                migrated_countries.append(meta["country"])
                migrated_zakats.append(meta["zakat_eligibility"])

            df_payouts["Code"] = migrated_codes
            df_payouts["Heading"] = migrated_headings
            df_payouts["Sub-Heading"] = migrated_subheadings
            df_payouts["Country"] = migrated_countries
            df_payouts["Zakat Eligibility"] = migrated_zakats

            # Atomic database replace
            df_payouts = sanitize_df_dtypes_for_parquet(df_payouts)
            df_payouts.to_sql("payout_settlements", con=conn, if_exists="replace", index=False, chunksize=5000)
            conn.commit()

            # Ensure indexes exist
            cur.execute('CREATE INDEX IF NOT EXISTS idx_payouts_transfer_id ON payout_settlements("Transfer ID");')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_payouts_donation_id ON payout_settlements("Donation ID");')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_payouts_camp_name ON payout_settlements("Campaign Name");')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_payouts_code ON payout_settlements("Code");')
            conn.commit()
            print("  ✅ Successfully migrated SQLite 'payout_settlements' table.")

    conn.close()

    # 4. Migrate Parquet Cache
    if os.path.exists(PAYOUTS_PARQUET_PATH):
        df_parquet = pd.read_parquet(PAYOUTS_PARQUET_PATH)
        if not df_parquet.empty:
            print(f"Migrating {len(df_parquet):,} rows in '{os.path.basename(PAYOUTS_PARQUET_PATH)}'...")
            c_names = df_parquet["Campaign Name"].astype(str).str.strip().str.lower().apply(fix_mojibake)
            codes = df_parquet["Code"].astype(str).str.strip().str.upper()

            migrated_codes = []
            migrated_headings = []
            migrated_subheadings = []
            migrated_countries = []
            migrated_zakats = []

            for idx, (cn, cc) in enumerate(zip(c_names, codes)):
                target_code = camp_map.get(cn)
                if not target_code or target_code not in master_codes_map:
                    target_code = LEGACY_PAYOUT_CODE_MAP.get(cc, cc)

                meta = master_codes_map.get(target_code, {
                    "code": target_code,
                    "heading": df_parquet.iloc[idx].get("Heading", "Unassigned"),
                    "sub_heading": df_parquet.iloc[idx].get("Sub-Heading", "Unassigned"),
                    "country": df_parquet.iloc[idx].get("Country", "Unassigned"),
                    "zakat_eligibility": df_parquet.iloc[idx].get("Zakat Eligibility", "Unassigned")
                })

                migrated_codes.append(meta["code"])
                migrated_headings.append(meta["heading"])
                migrated_subheadings.append(meta["sub_heading"])
                migrated_countries.append(meta["country"])
                migrated_zakats.append(meta["zakat_eligibility"])

            df_parquet["Code"] = migrated_codes
            df_parquet["Heading"] = migrated_headings
            df_parquet["Sub-Heading"] = migrated_subheadings
            df_parquet["Country"] = migrated_countries
            df_parquet["Zakat Eligibility"] = migrated_zakats

            df_parquet = sanitize_df_dtypes_for_parquet(df_parquet)
            atomic_write_parquet(df_parquet, PAYOUTS_PARQUET_PATH)
            print("  ✅ Successfully migrated and saved payouts_cache.parquet.")

    invalidate_payouts_cache()
    print("\n✨ Migration complete! Payout caches invalidated.")

if __name__ == "__main__":
    migrate_payouts()
