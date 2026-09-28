import sqlite3
import pandas as pd
import os
import sys
import shutil
from datetime import datetime

# Configuration paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "launchgood_donations.db")
PARQUET_PATH = os.path.join(BASE_DIR, "donations_cache.parquet")
SEED_DB_PATH = os.path.join(BASE_DIR, "data_cache", "seed_database.sqlite")
EXCEL_PATH = os.path.join(BASE_DIR, "Rethink_Humama_Final.xlsx")

def run_migration():
    print(f"=== Starting Final Register Migration ===")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Target Database: {DB_PATH}")
    print(f"Source Register: {EXCEL_PATH}")

    # 1. Backups
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_backup = f"{DB_PATH}.backup_pre_final_register_{timestamp}"
    if os.path.exists(DB_PATH):
        shutil.copyfile(DB_PATH, db_backup)
        print(f"[BACKUP] Created SQLite DB backup: {db_backup}")

    if os.path.exists(PARQUET_PATH):
        pq_backup = f"{PARQUET_PATH}.backup_pre_final_register_{timestamp}"
        shutil.copyfile(PARQUET_PATH, pq_backup)
        print(f"[BACKUP] Created Parquet backup: {pq_backup}")

    # 2. Read Excel Register
    df_excel = pd.read_excel(EXCEL_PATH, header=1)
    df_excel = df_excel.dropna(how="all", axis=1)

    # 3. Connect to SQLite DB
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()

    # Archive current master_project_codes as _legacy_master_project_codes_54
    cur.execute("DROP TABLE IF EXISTS _legacy_master_project_codes_54")
    cur.execute("CREATE TABLE _legacy_master_project_codes_54 AS SELECT * FROM master_project_codes")
    conn.commit()
    print("[ARCHIVE] Archived current 54 codes to _legacy_master_project_codes_54")

    # 4. Recreate master_project_codes with expanded schema
    cur.execute("DROP TABLE IF EXISTS master_project_codes")
    cur.execute("""
    CREATE TABLE master_project_codes (
        code TEXT PRIMARY KEY,
        department TEXT NOT NULL,
        office TEXT NOT NULL,
        portfolio TEXT DEFAULT '',
        country TEXT NOT NULL,
        programme_fund TEXT DEFAULT '',
        fund_code TEXT DEFAULT '',
        zakat_eligibility TEXT NOT NULL DEFAULT 'Zakat',
        legacy_non_zakat_code TEXT DEFAULT '',
        legacy_zakat_code TEXT DEFAULT '',
        old_codes TEXT DEFAULT '',
        description TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    print("[SCHEMA] Created updated master_project_codes table with Programme Fund and Legacy GL codes")

    # 5. Ingest all 184 codes from Excel + the agreed custom codes
    excel_records = []
    old_to_new_direct = {}  # legacy_code -> new_code

    for _, r in df_excel.iterrows():
        final_code = str(r.get("Final Allocation Code") or "").strip().upper()
        if not final_code or final_code in ["NAN", "NONE", ""]:
            continue

        cntry = str(r.get("Country") or "General / Multi-Country").strip()
        port = str(r.get("Portfolio") or "").strip()
        dept = str(r.get("Department") or "Unassigned").strip()
        off = str(r.get("Office") or "Unassigned").strip()
        prog_fund = str(r.get("Programme Fund") or "").strip()
        fund_code = str(r.get("Fund Code") or "").strip()
        zakat_elig = "Zakat" if str(r.get("Zakat Eligible (legacy basis)")).strip().lower() == "yes" else "Non-Zakat"
        non_zakat_gl = str(r.get("Legacy Non-Zakat Code(s)") or "").strip().replace(".0", "")
        if non_zakat_gl in ["nan", "none", "None"]: non_zakat_gl = ""
        zakat_gl = str(r.get("Legacy Zakat Code(s)") or "").strip().replace(".0", "")
        if zakat_gl in ["nan", "none", "None"]: zakat_gl = ""
        old_raw = str(r.get("Old Code(s)") or "").strip()
        if old_raw in ["nan", "none", "None"]: old_raw = ""

        excel_records.append({
            "code": final_code,
            "department": dept,
            "office": off,
            "portfolio": port,
            "country": cntry,
            "programme_fund": prog_fund,
            "fund_code": fund_code,
            "zakat_eligibility": zakat_elig,
            "legacy_non_zakat_code": non_zakat_gl,
            "legacy_zakat_code": zakat_gl,
            "old_codes": old_raw,
            "description": f"Imported from Final Register: {prog_fund}"
        })

        if old_raw:
            tokens = [t.strip().upper() for t in old_raw.replace(",", ";").split(";") if t.strip()]
            for tok in tokens:
                old_to_new_direct[tok] = final_code

    # Add the agreed custom codes aligned in /grill-me
    custom_aligned_codes = [
        # 1. UK Sisters Project Hardship Fund
        {
            "code": "GBR-SOC-AID-SIS",
            "department": "Aid",
            "office": "Sisters Project Hardship Fund",
            "portfolio": "Social & Shelter",
            "country": "United Kingdom",
            "programme_fund": "3. Families & Livelihoods Fund",
            "fund_code": "F3-FAM",
            "zakat_eligibility": "Zakat",
            "legacy_non_zakat_code": "42010101101",
            "legacy_zakat_code": "42010101201",
            "old_codes": "UK-SP-HRDF",
            "description": "Sisters Project UK Hardship Fund"
        },
        # 2. Morocco Earthquake Relief
        {
            "code": "MAR-SOC-EMR-EQR",
            "department": "Emergency Response",
            "office": "Earthquake Relief",
            "portfolio": "Social & Shelter",
            "country": "Morocco",
            "programme_fund": "1. Emergency / Most-Needed Fund",
            "fund_code": "F1-EMR",
            "zakat_eligibility": "Zakat",
            "legacy_non_zakat_code": "42040101101",
            "legacy_zakat_code": "42040101201",
            "old_codes": "MAR-EMR-EQR",
            "description": "Morocco Earthquake Relief Fund"
        },
        # 3. Sudan General Emergency Aid
        {
            "code": "SDN-SOC-EMR-GEN",
            "department": "Emergency Response",
            "office": "General Emergency Aid",
            "portfolio": "Social & Shelter",
            "country": "Sudan",
            "programme_fund": "1. Emergency / Most-Needed Fund",
            "fund_code": "F1-EMR",
            "zakat_eligibility": "Zakat",
            "legacy_non_zakat_code": "42050101101",
            "legacy_zakat_code": "42050101201",
            "old_codes": "SDN-EMR",
            "description": "Sudan Emergency Aid"
        },
        # 4. Global Water Wells & Boreholes
        {
            "code": "ALL-INF-MIS-WEL",
            "department": "Misc Infrastructure",
            "office": "Water Well",
            "portfolio": "Infrastructure",
            "country": "Global / Unspecified",
            "programme_fund": "5. Water & Infrastructure Fund",
            "fund_code": "F5-WAI",
            "zakat_eligibility": "Non-Zakat",
            "legacy_non_zakat_code": "42080301101",
            "legacy_zakat_code": "",
            "old_codes": "ALL-WAT-WEL",
            "description": "Global Water Wells and Boreholes"
        },
        # 5. Gaza Schools General
        {
            "code": "GAZ-EDU-SCH-GEN",
            "department": "Schools",
            "office": "Schools General",
            "portfolio": "Education",
            "country": "Gaza",
            "programme_fund": "4. Education Fund",
            "fund_code": "F4-EDU",
            "zakat_eligibility": "Zakat",
            "legacy_non_zakat_code": "42020201101",
            "legacy_zakat_code": "42020201201",
            "old_codes": "GAZ-ONE-SCH",
            "description": "Gaza Schools General Education Fund"
        },
        # 6. Gaza Musallah
        {
            "code": "GAZ-INF-MIS-MUS",
            "department": "Misc Infrastructure",
            "office": "Musallah",
            "portfolio": "Infrastructure",
            "country": "Gaza",
            "programme_fund": "5. Water & Infrastructure Fund",
            "fund_code": "F5-WAI",
            "zakat_eligibility": "Non-Zakat",
            "legacy_non_zakat_code": "42020302101",
            "legacy_zakat_code": "",
            "old_codes": "GAZ-ONE-MUS",
            "description": "Gaza Musallah Construction and Restoration"
        },
        # 7. Syria Dentist Scholarship
        {
            "code": "SYR-EDU-SPN-DEN",
            "department": "Sponsorships",
            "office": "Dentist Scholarship",
            "portfolio": "Education",
            "country": "Syria",
            "programme_fund": "4. Education Fund",
            "fund_code": "F4-EDU",
            "zakat_eligibility": "Zakat",
            "legacy_non_zakat_code": "42010202101",
            "legacy_zakat_code": "42010202201",
            "old_codes": "SYR-ONE-DEN; TBC-ONE-DEN",
            "description": "Syria Dentist Scholarship"
        }
    ]

    for custom in custom_aligned_codes:
        existing = next((r for r in excel_records if r["code"] == custom["code"]), None)
        if not existing:
            excel_records.append(custom)
        tokens = [t.strip().upper() for t in custom["old_codes"].replace(",", ";").split(";") if t.strip()]
        for tok in tokens:
            old_to_new_direct[tok] = custom["code"]

    # Register agreed mappings for GAZ-ONE-PRO and AFG-INF
    old_to_new_direct["GAZ-ONE-PRO"] = "GAZ-MED-SUP-ASD"
    old_to_new_direct["AFG-INF"] = "AFG-INF-MIS-HOU"

    # Update old_codes string for GAZ-MED-SUP-ASD and AFG-INF-MIS-HOU in excel_records
    for r in excel_records:
        if r["code"] == "GAZ-MED-SUP-ASD":
            current_old = r["old_codes"]
            r["old_codes"] = f"{current_old}; GAZ-ONE-PRO".strip("; ")
        elif r["code"] == "AFG-INF-MIS-HOU":
            current_old = r["old_codes"]
            r["old_codes"] = f"{current_old}; AFG-INF".strip("; ")

    # Insert all records into master_project_codes
    for r in excel_records:
        cur.execute("""
        INSERT INTO master_project_codes (
            code, department, office, portfolio, country, 
            programme_fund, fund_code, zakat_eligibility, 
            legacy_non_zakat_code, legacy_zakat_code, old_codes, description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            department = excluded.department,
            office = excluded.office,
            portfolio = excluded.portfolio,
            country = excluded.country,
            programme_fund = excluded.programme_fund,
            fund_code = excluded.fund_code,
            zakat_eligibility = excluded.zakat_eligibility,
            legacy_non_zakat_code = excluded.legacy_non_zakat_code,
            legacy_zakat_code = excluded.legacy_zakat_code,
            old_codes = excluded.old_codes,
            description = excluded.description,
            updated_at = CURRENT_TIMESTAMP;
        """, (
            r["code"], r["department"], r["office"], r["portfolio"], r["country"],
            r["programme_fund"], r["fund_code"], r["zakat_eligibility"],
            r["legacy_non_zakat_code"], r["legacy_zakat_code"], r["old_codes"], r["description"]
        ))
    conn.commit()
    print(f"[INGEST] Successfully populated master_project_codes with {len(excel_records)} codes!")

    # 6. Build Master Lookup Map for Fast Cascade
    master_lookup = {r["code"]: r for r in excel_records}

    # Function to resolve any old code + campaign context to new Final Allocation Code
    def resolve_new_code(old_c, camp_name="", cntry=""):
        c_clean = str(old_c or "").strip().upper()
        if not c_clean or c_clean in ["UNASSIGNED", "NAN", "NONE", "N/A", ""]:
            return "UNASSIGNED"

        # Already a new Final Allocation Code
        if c_clean in master_lookup:
            return c_clean

        # Check multi-country split codes contextually
        camp_lower = str(camp_name or "").lower()
        cntry_lower = str(cntry or "").lower()

        if c_clean == "ALL-SEA-QUR":
            if "gaza" in camp_lower or "palestine" in camp_lower or cntry_lower == "gaza":
                return "GAZ-SOC-AID-QAA"
            elif "syria" in camp_lower or cntry_lower == "syria":
                return "SYR-SOC-AID-QAA"
            elif "yemen" in camp_lower or cntry_lower == "yemen":
                return "YEM-SOC-AID-QAA"
            elif "afghanistan" in camp_lower or cntry_lower == "afghanistan":
                return "AFG-SOC-AID-QAA"
            return "SYR-SOC-AID-QAA"

        if c_clean == "ALL-ZKT":
            if "gaza" in camp_lower or "palestine" in camp_lower or cntry_lower == "gaza":
                return "GAZ-SOC-AID-ZKT"
            elif "syria" in camp_lower or cntry_lower == "syria":
                return "SYR-SOC-AID-ZKT"
            elif "afghanistan" in camp_lower or cntry_lower == "afghanistan":
                return "AFG-SOC-AID-ZKT"
            return "ALL-SOC-AID-ZKT"

        if c_clean in old_to_new_direct:
            return old_to_new_direct[c_clean]

        return c_clean

    # 7. Migrate platform_campaign_mappings
    print("[MIGRATION] Re-keying platform_campaign_mappings to Final Allocation Codes...")
    cur.execute("CREATE TEMP TABLE temp_pcm AS SELECT * FROM platform_campaign_mappings")
    cur.execute("DELETE FROM platform_campaign_mappings")

    cur.execute("SELECT id, platform, campaign_name, code, community_name, campaign_url, is_primary, donor_name, donor_email FROM temp_pcm")
    updated_mappings_count = 0
    for row in cur.fetchall():
        row_id, plat, camp, old_c, comm, curl, is_prim, dname, demail = row
        new_c = resolve_new_code(old_c, camp)

        cur.execute("""
        INSERT INTO platform_campaign_mappings (
            platform, campaign_name, code, community_name, campaign_url, is_primary, donor_name, donor_email
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, campaign_name, code) DO UPDATE SET
            community_name = excluded.community_name,
            campaign_url = COALESCE(NULLIF(excluded.campaign_url, ''), platform_campaign_mappings.campaign_url),
            is_primary = excluded.is_primary,
            donor_name = COALESCE(NULLIF(excluded.donor_name, ''), platform_campaign_mappings.donor_name),
            donor_email = COALESCE(NULLIF(excluded.donor_email, ''), platform_campaign_mappings.donor_email)
        """, (plat, camp, new_c, comm, curl, is_prim, dname, demail))
        updated_mappings_count += 1

    cur.execute("DROP TABLE temp_pcm")
    conn.commit()
    print(f"[MIGRATION] Re-keyed {updated_mappings_count} platform campaign mappings!")

    # 8. Recreate Backward-Compatible SQL Views with Programme Fund and GL Codes
    print("[VIEWS] Recreating SQL views with Programme Fund, Fund Code, and GL Codes...")
    platforms_view_config = [
        ("campaign_classifications", "launchgood"),
        ("givebright_classifications", "givebright"),
        ("paysuite_classifications", "paysuite"),
        ("rethink_website_classifications", "website")
    ]

    for v_name, p_name in platforms_view_config:
        cur.execute(f"DROP VIEW IF EXISTS {v_name}")
        cur.execute(f"""
        CREATE VIEW {v_name} AS
        SELECT 
            m.campaign_name,
            m.code,
            COALESCE(m.community_name, 'N/A') AS community_name,
            COALESCE(m.campaign_url, '') AS campaign_url,
            COALESCE(c.department, 'Unassigned') AS department,
            COALESCE(c.office, 'Unassigned') AS office,
            COALESCE(c.portfolio, '') AS portfolio,
            COALESCE(c.programme_fund, '') AS programme_fund,
            COALESCE(c.fund_code, '') AS fund_code,
            COALESCE(c.legacy_non_zakat_code, '') AS legacy_non_zakat_code,
            COALESCE(c.legacy_zakat_code, '') AS legacy_zakat_code,
            COALESCE(c.department, 'Unassigned') AS heading,
            COALESCE(c.office, 'Unassigned') AS sub_heading,
            COALESCE(c.country, 'Unassigned') AS country,
            COALESCE(c.zakat_eligibility, 'Unassigned') AS zakat_eligibility,
            COALESCE(m.is_primary, 0) AS is_primary,
            COALESCE(m.donor_name, '') AS donor_name,
            COALESCE(m.donor_email, '') AS donor_email
        FROM platform_campaign_mappings m
        LEFT JOIN master_project_codes c ON UPPER(TRIM(m.code)) = UPPER(TRIM(c.code))
        WHERE m.platform = '{p_name}';
        """)

    conn.commit()
    print("[VIEWS] Successfully created views with dual aliases and Programme Fund columns!")

    # 9. Update SQLite donations table columns
    print("[DONATIONS DB] Adding new columns to donations table...")
    don_cols = [r[1] for r in cur.execute("PRAGMA table_info(donations)").fetchall()]

    for col_def in [
        ("Programme Fund", "TEXT DEFAULT ''"),
        ("Fund Code", "TEXT DEFAULT ''"),
        ("Old Code", "TEXT DEFAULT ''")
    ]:
        col_name, col_type = col_def
        if col_name not in don_cols:
            cur.execute(f'ALTER TABLE donations ADD COLUMN "{col_name}" {col_type}')
            print(f"  Added column '{col_name}' to donations table")

    conn.commit()

    # 10. Migrate Parquet Cache & SQLite donations rows in batch
    print("[DATA CASCADE] Migrating Parquet dataset (106,834 records)...")
    if os.path.exists(PARQUET_PATH):
        df_don = pd.read_parquet(PARQUET_PATH)

        # Preserve Old Code
        if "Old Code" not in df_don.columns or df_don["Old Code"].dropna().empty:
            df_don["Old Code"] = df_don["Code"].astype(str)
        else:
            df_don["Old Code"] = df_don["Old Code"].fillna(df_don["Code"].astype(str))

        # Vectorized / Apply resolution for new codes
        camp_series = df_don["Campaign Name"].astype(str)
        cntry_series = df_don["Country"].astype(str) if "Country" in df_don.columns else pd.Series("", index=df_don.index)
        code_series = df_don["Code"].astype(str)

        new_codes = []
        for old_c, c_name, c_cntry in zip(code_series, camp_series, cntry_series):
            new_codes.append(resolve_new_code(old_c, c_name, c_cntry))

        df_don["Code"] = new_codes

        # Vectorized lookup for Department, Office, Portfolio, Programme Fund, Fund Code, Country, Zakat
        dept_map = {k: v["department"] for k, v in master_lookup.items()}
        off_map = {k: v["office"] for k, v in master_lookup.items()}
        port_map = {k: v["portfolio"] for k, v in master_lookup.items()}
        fund_map = {k: v["programme_fund"] for k, v in master_lookup.items()}
        fcode_map = {k: v["fund_code"] for k, v in master_lookup.items()}
        cntry_map = {k: v["country"] for k, v in master_lookup.items()}
        zakat_map = {k: v["zakat_eligibility"] for k, v in master_lookup.items()}

        s_code = df_don["Code"].str.upper()

        mapped_dept = s_code.map(dept_map)
        mapped_off = s_code.map(off_map)
        mapped_port = s_code.map(port_map)
        mapped_fund = s_code.map(fund_map)
        mapped_fcode = s_code.map(fcode_map)
        mapped_cntry = s_code.map(cntry_map)
        mapped_zakat = s_code.map(zakat_map)

        df_don["Department"] = mapped_dept.fillna(df_don.get("Department", "Unassigned"))
        df_don["Heading"] = df_don["Department"]
        df_don["Office"] = mapped_off.fillna(df_don.get("Office", "Unassigned"))
        df_don["Sub-Heading"] = df_don["Office"]
        df_don["Portfolio"] = mapped_port.fillna(df_don.get("Portfolio", ""))
        df_don["Programme Fund"] = mapped_fund.fillna("")
        df_don["Fund Code"] = mapped_fcode.fillna("")
        df_don["Country"] = mapped_cntry.fillna(df_don.get("Country", "General / Multi-Country"))
        df_don["Zakat Eligibility"] = mapped_zakat.fillna(df_don.get("Zakat Eligibility", "Zakat"))

        df_don.to_parquet(PARQUET_PATH, index=False)
        print(f"[DATA CASCADE] Parquet updated with new codes, Programme Funds, and Old Codes!")

        # Also update SQLite donations table in batch
        print("[DATA CASCADE] Updating SQLite donations table...")
        df_don.to_sql("donations", con=conn, if_exists="replace", index=False)
        print("[DATA CASCADE] SQLite donations table synchronized successfully!")

    # 11. Sync Seed Database if present
    if os.path.exists(SEED_DB_PATH):
        try:
            print("[SEED DB] Syncing seed_database.sqlite with final register schema...")
            seed_conn = sqlite3.connect(SEED_DB_PATH, timeout=30.0)
            seed_cur = seed_conn.cursor()

            seed_cur.execute("DROP TABLE IF EXISTS master_project_codes")
            cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='master_project_codes'")
            mpc_create_sql = cur.fetchone()[0]
            seed_cur.execute(mpc_create_sql)

            # Copy data
            cur.execute("SELECT * FROM master_project_codes")
            all_mpc_rows = cur.fetchall()
            placeholders = ",".join(["?"] * len(all_mpc_rows[0]))
            seed_cur.executemany(f"INSERT INTO master_project_codes VALUES ({placeholders})", all_mpc_rows)

            seed_conn.commit()
            seed_conn.close()
            print("[SEED DB] Successfully updated seed_database.sqlite!")
        except Exception as se:
            print(f"[SEED DB NOTICE]: {se}")

    conn.close()
    print("\n=== Final Register Migration Completed Successfully! ===")

if __name__ == "__main__":
    run_migration()
