import sqlite3
import pandas as pd
import os
import sys

def run_migration(db_path="launchgood_donations.db"):
    print(f"Starting migration on {db_path}...")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Step 1: Create master_project_codes table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS master_project_codes (
        code TEXT PRIMARY KEY,
        department TEXT NOT NULL,
        office TEXT NOT NULL,
        portfolio TEXT DEFAULT '',
        country TEXT NOT NULL,
        zakat_eligibility TEXT NOT NULL DEFAULT 'Zakat',
        description TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Step 2: Create platform_campaign_mappings table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS platform_campaign_mappings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        campaign_name TEXT NOT NULL,
        code TEXT NOT NULL,
        community_name TEXT DEFAULT 'N/A',
        campaign_url TEXT DEFAULT '',
        is_primary INTEGER DEFAULT 0,
        donor_name TEXT DEFAULT '',
        donor_email TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(platform, campaign_name, code)
    );
    """)
    conn.commit()

    # Check if legacy tables exist or if this is already migrated
    cur.execute("SELECT name, type FROM sqlite_master WHERE type='table' AND name='_legacy_campaign_classifications'")
    has_legacy_prefixed = cur.fetchone() is not None

    cur.execute("SELECT name, type FROM sqlite_master WHERE type='table' AND name='campaign_classifications'")
    has_lg_table = cur.fetchone() is not None

    needs_migration = has_legacy_prefixed or has_lg_table

    # Also check if master_project_codes is already populated
    cur.execute("SELECT COUNT(*) FROM master_project_codes")
    existing_codes_cnt = cur.fetchone()[0]

    if needs_migration and existing_codes_cnt == 0:
        print("Detected legacy classification tables. Extracting records...")
        
        prefix = "_legacy_" if has_legacy_prefixed else ""
        source_tables = [
            ("launchgood", f"{prefix}campaign_classifications"),
            ("givebright", f"{prefix}givebright_classifications"),
            ("paysuite", f"{prefix}paysuite_classifications"),
            ("website", f"{prefix}rethink_website_classifications")
        ]

        master_codes = {} # code -> {department, office, portfolio, country, zakat_eligibility}

        for platform, tbl in source_tables:
            try:
                df = pd.read_sql_query(f"SELECT * FROM {tbl}", conn)
                for _, r in df.iterrows():
                    code = str(r.get("code") or "").strip().upper()
                    if not code or code in ["UNASSIGNED", "N/A", "NAN", "NONE", ""]:
                        continue
                    
                    heading = str(r.get("heading") or "Unassigned").strip()
                    sub_heading = str(r.get("sub_heading") or "Unassigned").strip()
                    country = str(r.get("country") or "Unassigned").strip()
                    zakat = str(r.get("zakat_eligibility") or "Unassigned").strip()

                    # Only set/overwrite if better than Unassigned
                    if code not in master_codes:
                        master_codes[code] = {
                            "department": heading,
                            "office": sub_heading,
                            "portfolio": "",
                            "country": country,
                            "zakat_eligibility": zakat if zakat != "Unassigned" else "Zakat"
                        }
                    else:
                        cur_entry = master_codes[code]
                        if cur_entry["department"] == "Unassigned" and heading != "Unassigned":
                            cur_entry["department"] = heading
                        if cur_entry["office"] == "Unassigned" and sub_heading != "Unassigned":
                            cur_entry["office"] = sub_heading
                        if cur_entry["country"] == "Unassigned" and country != "Unassigned":
                            cur_entry["country"] = country
                        if cur_entry["zakat_eligibility"] == "Unassigned" and zakat != "Unassigned":
                            cur_entry["zakat_eligibility"] = zakat
            except Exception as e:
                print(f"Notice reading {tbl}: {e}")

        # Insert into master_project_codes
        print(f"Inserting {len(master_codes)} master project codes into master_project_codes...")
        for code, info in master_codes.items():
            cur.execute("""
            INSERT INTO master_project_codes (code, department, office, portfolio, country, zakat_eligibility)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                department = excluded.department,
                office = excluded.office,
                country = excluded.country,
                zakat_eligibility = excluded.zakat_eligibility
            """, (code, info["department"], info["office"], info["portfolio"], info["country"], info["zakat_eligibility"]))
        conn.commit()

        # 4. Migrate campaign mappings
        mapping_count = 0
        for platform, tbl in source_tables:
            try:
                df = pd.read_sql_query(f"SELECT * FROM {tbl}", conn)
                for _, r in df.iterrows():
                    cname = str(r.get("campaign_name") or "").strip()
                    code = str(r.get("code") or "Unassigned").strip().upper()
                    if not cname or cname.lower() in ["nan", "none", "n/a", ""]:
                        continue
                    
                    comm = str(r.get("community_name") or "N/A").strip()
                    curl = str(r.get("campaign_url") or "").strip()
                    is_prim = 1 if r.get("is_primary") in [1, True, "1", "true", "True"] else 0
                    dname = str(r.get("donor_name") or "").strip()
                    demail = str(r.get("donor_email") or "").strip()

                    cur.execute("""
                    INSERT INTO platform_campaign_mappings (platform, campaign_name, code, community_name, campaign_url, is_primary, donor_name, donor_email)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform, campaign_name, code) DO UPDATE SET
                        community_name = excluded.community_name,
                        campaign_url = COALESCE(NULLIF(excluded.campaign_url, ''), platform_campaign_mappings.campaign_url),
                        is_primary = excluded.is_primary,
                        donor_name = COALESCE(NULLIF(excluded.donor_name, ''), platform_campaign_mappings.donor_name),
                        donor_email = COALESCE(NULLIF(excluded.donor_email, ''), platform_campaign_mappings.donor_email)
                    """, (platform, cname, code, comm, curl, is_prim, dname, demail))
                    mapping_count += 1
            except Exception as e:
                print(f"Notice reading mapping from {tbl}: {e}")

        conn.commit()
        print(f"Successfully migrated {mapping_count} campaign mappings into platform_campaign_mappings.")

        # 5. Archive physical tables to _legacy_*
        if not has_legacy_prefixed:
            print("Archiving legacy tables...")
            for platform, tbl in source_tables:
                cur.execute(f"DROP TABLE IF EXISTS _legacy_{tbl}")
                cur.execute(f"ALTER TABLE {tbl} RENAME TO _legacy_{tbl}")
            conn.commit()

    # 6. Create backward-compatible views
    print("Creating backward-compatible SQL Views with Department, Office, Portfolio, and legacy Heading/Sub-heading aliases...")

    cur.execute("DROP VIEW IF EXISTS campaign_classifications")
    cur.execute("""
    CREATE VIEW campaign_classifications AS
    SELECT 
        m.campaign_name,
        m.code,
        COALESCE(m.community_name, 'N/A') AS community_name,
        COALESCE(m.campaign_url, '') AS campaign_url,
        COALESCE(c.department, 'Unassigned') AS department,
        COALESCE(c.office, 'Unassigned') AS office,
        COALESCE(c.portfolio, '') AS portfolio,
        COALESCE(c.department, 'Unassigned') AS heading,
        COALESCE(c.office, 'Unassigned') AS sub_heading,
        COALESCE(c.country, 'Unassigned') AS country,
        COALESCE(c.zakat_eligibility, 'Unassigned') AS zakat_eligibility,
        COALESCE(m.is_primary, 0) AS is_primary
    FROM platform_campaign_mappings m
    LEFT JOIN master_project_codes c ON UPPER(TRIM(m.code)) = UPPER(TRIM(c.code))
    WHERE m.platform = 'launchgood';
    """)

    cur.execute("DROP VIEW IF EXISTS givebright_classifications")
    cur.execute("""
    CREATE VIEW givebright_classifications AS
    SELECT 
        m.campaign_name,
        m.code,
        COALESCE(m.campaign_url, '') AS campaign_url,
        COALESCE(c.department, 'Unassigned') AS department,
        COALESCE(c.office, 'Unassigned') AS office,
        COALESCE(c.portfolio, '') AS portfolio,
        COALESCE(c.department, 'Unassigned') AS heading,
        COALESCE(c.office, 'Unassigned') AS sub_heading,
        COALESCE(c.country, 'Unassigned') AS country,
        COALESCE(c.zakat_eligibility, 'Unassigned') AS zakat_eligibility,
        COALESCE(m.is_primary, 0) AS is_primary
    FROM platform_campaign_mappings m
    LEFT JOIN master_project_codes c ON UPPER(TRIM(m.code)) = UPPER(TRIM(c.code))
    WHERE m.platform = 'givebright';
    """)

    cur.execute("DROP VIEW IF EXISTS paysuite_classifications")
    cur.execute("""
    CREATE VIEW paysuite_classifications AS
    SELECT 
        m.campaign_name,
        m.code,
        COALESCE(m.community_name, 'N/A') AS community_name,
        COALESCE(c.department, 'Unassigned') AS department,
        COALESCE(c.office, 'Unassigned') AS office,
        COALESCE(c.portfolio, '') AS portfolio,
        COALESCE(c.department, 'Unassigned') AS heading,
        COALESCE(c.office, 'Unassigned') AS sub_heading,
        COALESCE(c.country, 'Unassigned') AS country,
        COALESCE(c.zakat_eligibility, 'Unassigned') AS zakat_eligibility,
        COALESCE(m.donor_name, '') AS donor_name,
        COALESCE(m.donor_email, '') AS donor_email,
        COALESCE(m.is_primary, 0) AS is_primary
    FROM platform_campaign_mappings m
    LEFT JOIN master_project_codes c ON UPPER(TRIM(m.code)) = UPPER(TRIM(c.code))
    WHERE m.platform = 'paysuite';
    """)

    cur.execute("DROP VIEW IF EXISTS rethink_website_classifications")
    cur.execute("""
    CREATE VIEW rethink_website_classifications AS
    SELECT 
        m.campaign_name,
        m.code,
        COALESCE(m.community_name, 'N/A') AS community_name,
        COALESCE(c.department, 'Unassigned') AS department,
        COALESCE(c.office, 'Unassigned') AS office,
        COALESCE(c.portfolio, '') AS portfolio,
        COALESCE(c.department, 'Unassigned') AS heading,
        COALESCE(c.office, 'Unassigned') AS sub_heading,
        COALESCE(c.country, 'Unassigned') AS country,
        COALESCE(c.zakat_eligibility, 'Unassigned') AS zakat_eligibility,
        COALESCE(m.is_primary, 0) AS is_primary
    FROM platform_campaign_mappings m
    LEFT JOIN master_project_codes c ON UPPER(TRIM(m.code)) = UPPER(TRIM(c.code))
    WHERE m.platform IN ('website', 'rethink_website');
    """)

    # Triggers for campaign_classifications
    cur.execute("DROP TRIGGER IF EXISTS trg_campaign_classifications_insert")
    cur.execute("""
    CREATE TRIGGER trg_campaign_classifications_insert
    INSTEAD OF INSERT ON campaign_classifications
    BEGIN
        INSERT INTO master_project_codes (code, department, office, portfolio, country, zakat_eligibility)
        VALUES (
            UPPER(TRIM(NEW.code)), 
            COALESCE(NULLIF(NEW.department, ''), NULLIF(NEW.heading, ''), 'Unassigned'),
            COALESCE(NULLIF(NEW.office, ''), NULLIF(NEW.sub_heading, ''), 'Unassigned'),
            COALESCE(NEW.portfolio, ''),
            COALESCE(NEW.country, 'Unassigned'),
            COALESCE(NEW.zakat_eligibility, 'Zakat')
        )
        ON CONFLICT(code) DO UPDATE SET
            department = CASE WHEN excluded.department != 'Unassigned' THEN excluded.department ELSE master_project_codes.department END,
            office = CASE WHEN excluded.office != 'Unassigned' THEN excluded.office ELSE master_project_codes.office END,
            portfolio = CASE WHEN excluded.portfolio != '' THEN excluded.portfolio ELSE master_project_codes.portfolio END,
            country = CASE WHEN excluded.country != 'Unassigned' THEN excluded.country ELSE master_project_codes.country END,
            zakat_eligibility = CASE WHEN excluded.zakat_eligibility != 'Unassigned' THEN excluded.zakat_eligibility ELSE master_project_codes.zakat_eligibility END;

        INSERT INTO platform_campaign_mappings (platform, campaign_name, code, community_name, campaign_url, is_primary)
        VALUES (
            'launchgood',
            TRIM(NEW.campaign_name),
            UPPER(TRIM(NEW.code)),
            COALESCE(NEW.community_name, 'N/A'),
            COALESCE(NEW.campaign_url, ''),
            COALESCE(NEW.is_primary, 0)
        )
        ON CONFLICT(platform, campaign_name, code) DO UPDATE SET
            community_name = excluded.community_name,
            campaign_url = COALESCE(NULLIF(excluded.campaign_url, ''), platform_campaign_mappings.campaign_url),
            is_primary = excluded.is_primary;
    END;
    """)

    cur.execute("DROP TRIGGER IF EXISTS trg_campaign_classifications_delete")
    cur.execute("""
    CREATE TRIGGER trg_campaign_classifications_delete
    INSTEAD OF DELETE ON campaign_classifications
    BEGIN
        DELETE FROM platform_campaign_mappings 
        WHERE platform = 'launchgood' 
          AND LOWER(campaign_name) = LOWER(OLD.campaign_name)
          AND (OLD.code IS NULL OR LOWER(code) = LOWER(OLD.code));
    END;
    """)

    # Triggers for givebright_classifications
    cur.execute("DROP TRIGGER IF EXISTS trg_givebright_classifications_insert")
    cur.execute("""
    CREATE TRIGGER trg_givebright_classifications_insert
    INSTEAD OF INSERT ON givebright_classifications
    BEGIN
        INSERT INTO master_project_codes (code, department, office, portfolio, country, zakat_eligibility)
        VALUES (
            UPPER(TRIM(NEW.code)), 
            COALESCE(NULLIF(NEW.department, ''), NULLIF(NEW.heading, ''), 'Unassigned'),
            COALESCE(NULLIF(NEW.office, ''), NULLIF(NEW.sub_heading, ''), 'Unassigned'),
            COALESCE(NEW.portfolio, ''),
            COALESCE(NEW.country, 'Unassigned'),
            COALESCE(NEW.zakat_eligibility, 'Zakat')
        )
        ON CONFLICT(code) DO UPDATE SET
            department = CASE WHEN excluded.department != 'Unassigned' THEN excluded.department ELSE master_project_codes.department END,
            office = CASE WHEN excluded.office != 'Unassigned' THEN excluded.office ELSE master_project_codes.office END,
            portfolio = CASE WHEN excluded.portfolio != '' THEN excluded.portfolio ELSE master_project_codes.portfolio END,
            country = CASE WHEN excluded.country != 'Unassigned' THEN excluded.country ELSE master_project_codes.country END,
            zakat_eligibility = CASE WHEN excluded.zakat_eligibility != 'Unassigned' THEN excluded.zakat_eligibility ELSE master_project_codes.zakat_eligibility END;

        INSERT INTO platform_campaign_mappings (platform, campaign_name, code, campaign_url, is_primary)
        VALUES (
            'givebright',
            TRIM(NEW.campaign_name),
            UPPER(TRIM(NEW.code)),
            COALESCE(NEW.campaign_url, ''),
            COALESCE(NEW.is_primary, 0)
        )
        ON CONFLICT(platform, campaign_name, code) DO UPDATE SET
            campaign_url = COALESCE(NULLIF(excluded.campaign_url, ''), platform_campaign_mappings.campaign_url),
            is_primary = excluded.is_primary;
    END;
    """)

    cur.execute("DROP TRIGGER IF EXISTS trg_givebright_classifications_delete")
    cur.execute("""
    CREATE TRIGGER trg_givebright_classifications_delete
    INSTEAD OF DELETE ON givebright_classifications
    BEGIN
        DELETE FROM platform_campaign_mappings 
        WHERE platform = 'givebright' 
          AND LOWER(campaign_name) = LOWER(OLD.campaign_name)
          AND (OLD.code IS NULL OR LOWER(code) = LOWER(OLD.code));
    END;
    """)

    # Triggers for paysuite_classifications
    cur.execute("DROP TRIGGER IF EXISTS trg_paysuite_classifications_insert")
    cur.execute("""
    CREATE TRIGGER trg_paysuite_classifications_insert
    INSTEAD OF INSERT ON paysuite_classifications
    BEGIN
        INSERT INTO master_project_codes (code, department, office, portfolio, country, zakat_eligibility)
        VALUES (
            UPPER(TRIM(NEW.code)), 
            COALESCE(NULLIF(NEW.department, ''), NULLIF(NEW.heading, ''), 'Unassigned'),
            COALESCE(NULLIF(NEW.office, ''), NULLIF(NEW.sub_heading, ''), 'Unassigned'),
            COALESCE(NEW.portfolio, ''),
            COALESCE(NEW.country, 'Unassigned'),
            COALESCE(NEW.zakat_eligibility, 'Zakat')
        )
        ON CONFLICT(code) DO UPDATE SET
            department = CASE WHEN excluded.department != 'Unassigned' THEN excluded.department ELSE master_project_codes.department END,
            office = CASE WHEN excluded.office != 'Unassigned' THEN excluded.office ELSE master_project_codes.office END,
            portfolio = CASE WHEN excluded.portfolio != '' THEN excluded.portfolio ELSE master_project_codes.portfolio END,
            country = CASE WHEN excluded.country != 'Unassigned' THEN excluded.country ELSE master_project_codes.country END,
            zakat_eligibility = CASE WHEN excluded.zakat_eligibility != 'Unassigned' THEN excluded.zakat_eligibility ELSE master_project_codes.zakat_eligibility END;

        INSERT INTO platform_campaign_mappings (platform, campaign_name, code, community_name, donor_name, donor_email, is_primary)
        VALUES (
            'paysuite',
            TRIM(NEW.campaign_name),
            UPPER(TRIM(NEW.code)),
            COALESCE(NEW.community_name, 'N/A'),
            COALESCE(NEW.donor_name, ''),
            COALESCE(NEW.donor_email, ''),
            COALESCE(NEW.is_primary, 0)
        )
        ON CONFLICT(platform, campaign_name, code) DO UPDATE SET
            community_name = excluded.community_name,
            donor_name = COALESCE(NULLIF(excluded.donor_name, ''), platform_campaign_mappings.donor_name),
            donor_email = COALESCE(NULLIF(excluded.donor_email, ''), platform_campaign_mappings.donor_email),
            is_primary = excluded.is_primary;
    END;
    """)

    cur.execute("DROP TRIGGER IF EXISTS trg_paysuite_classifications_delete")
    cur.execute("""
    CREATE TRIGGER trg_paysuite_classifications_delete
    INSTEAD OF DELETE ON paysuite_classifications
    BEGIN
        DELETE FROM platform_campaign_mappings 
        WHERE platform = 'paysuite' 
          AND LOWER(campaign_name) = LOWER(OLD.campaign_name)
          AND (OLD.code IS NULL OR LOWER(code) = LOWER(OLD.code));
    END;
    """)

    # Triggers for rethink_website_classifications
    cur.execute("DROP TRIGGER IF EXISTS trg_rethink_website_classifications_insert")
    cur.execute("""
    CREATE TRIGGER trg_rethink_website_classifications_insert
    INSTEAD OF INSERT ON rethink_website_classifications
    BEGIN
        INSERT INTO master_project_codes (code, department, office, portfolio, country, zakat_eligibility)
        VALUES (
            UPPER(TRIM(NEW.code)), 
            COALESCE(NULLIF(NEW.department, ''), NULLIF(NEW.heading, ''), 'Unassigned'),
            COALESCE(NULLIF(NEW.office, ''), NULLIF(NEW.sub_heading, ''), 'Unassigned'),
            COALESCE(NEW.portfolio, ''),
            COALESCE(NEW.country, 'Unassigned'),
            COALESCE(NEW.zakat_eligibility, 'Zakat')
        )
        ON CONFLICT(code) DO UPDATE SET
            department = CASE WHEN excluded.department != 'Unassigned' THEN excluded.department ELSE master_project_codes.department END,
            office = CASE WHEN excluded.office != 'Unassigned' THEN excluded.office ELSE master_project_codes.office END,
            portfolio = CASE WHEN excluded.portfolio != '' THEN excluded.portfolio ELSE master_project_codes.portfolio END,
            country = CASE WHEN excluded.country != 'Unassigned' THEN excluded.country ELSE master_project_codes.country END,
            zakat_eligibility = CASE WHEN excluded.zakat_eligibility != 'Unassigned' THEN excluded.zakat_eligibility ELSE master_project_codes.zakat_eligibility END;

        INSERT INTO platform_campaign_mappings (platform, campaign_name, code, community_name, is_primary)
        VALUES (
            'website',
            TRIM(NEW.campaign_name),
            UPPER(TRIM(NEW.code)),
            COALESCE(NEW.community_name, 'N/A'),
            COALESCE(NEW.is_primary, 0)
        )
        ON CONFLICT(platform, campaign_name, code) DO UPDATE SET
            community_name = excluded.community_name,
            is_primary = excluded.is_primary;
    END;
    """)

    cur.execute("DROP TRIGGER IF EXISTS trg_rethink_website_classifications_delete")
    cur.execute("""
    CREATE TRIGGER trg_rethink_website_classifications_delete
    INSTEAD OF DELETE ON rethink_website_classifications
    BEGIN
        DELETE FROM platform_campaign_mappings 
        WHERE platform IN ('website', 'rethink_website') 
          AND LOWER(campaign_name) = LOWER(OLD.campaign_name)
          AND (OLD.code IS NULL OR LOWER(code) = LOWER(OLD.code));
    END;
    """)

    conn.commit()
    print("All INSTEAD OF triggers created successfully!")

    # Step 7: Verification Query
    print("\n--- Migration Verification ---")
    cur.execute("SELECT COUNT(*) FROM master_project_codes")
    code_cnt = cur.fetchone()[0]
    print(f"Total Master Project Codes: {code_cnt}")

    cur.execute("SELECT platform, COUNT(*) FROM platform_campaign_mappings GROUP BY platform")
    print(f"Platform Campaign Mappings breakdown: {cur.fetchall()}")

    for v in ["campaign_classifications", "givebright_classifications", "paysuite_classifications", "rethink_website_classifications"]:
        cur.execute(f"SELECT COUNT(*) FROM {v}")
        print(f"View {v} row count: {cur.fetchone()[0]}")

    conn.close()
    print("Migration finished cleanly!")

if __name__ == "__main__":
    run_migration()
