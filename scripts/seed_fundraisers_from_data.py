import os
import sys
import math
import uuid
import sqlite3
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATHS = [
    os.path.join(PROJECT_ROOT, "launchgood_donations.db"),
    os.path.join(PROJECT_ROOT, "data_cache", "seed_database.sqlite")
]

def calculate_benchmark_goal(raised_amount: float) -> float:
    """Calculates an intelligent round target goal based on raised amount."""
    if raised_amount <= 0:
        return 1000.0
    if raised_amount <= 500:
        return 500.0
    elif raised_amount <= 1000:
        return 1000.0
    elif raised_amount <= 5000:
        return math.ceil(raised_amount / 1000.0) * 1000.0
    elif raised_amount <= 20000:
        return math.ceil(raised_amount / 5000.0) * 5000.0
    elif raised_amount <= 100000:
        return math.ceil(raised_amount / 10000.0) * 10000.0
    else:
        return math.ceil(raised_amount / 25000.0) * 25000.0

def init_tables(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fundraisers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            target_goal REAL DEFAULT 0.0,
            start_date TEXT DEFAULT '',
            status TEXT DEFAULT 'ACTIVE',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fundraiser_campaigns (
            id TEXT PRIMARY KEY,
            fundraiser_id TEXT NOT NULL,
            campaign_name TEXT NOT NULL,
            code TEXT NOT NULL DEFAULT 'ALL',
            platform TEXT DEFAULT 'ALL',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fundraiser_id) REFERENCES fundraisers(id) ON DELETE CASCADE
        );
    """)
    conn.commit()

def seed_fundraisers():
    primary_db = DB_PATHS[0]
    if not os.path.exists(primary_db):
        print(f"Error: Primary DB not found at {primary_db}")
        return

    conn = sqlite3.connect(primary_db)
    init_tables(conn)

    # 1. Query unique trimmed fundraisers grouped case-insensitively from donations
    query_fundraisers = """
    SELECT 
        MAX(TRIM(fundraiser_name)) as fundraiser_name,
        LOWER(TRIM(fundraiser_name)) as lower_name,
        ROUND(SUM([Total Online Donations Net Amount in Settled Currency]), 2) as total_raised,
        COUNT(*) as total_donations,
        MIN([Created Date (UTC)]) as earliest_gift,
        MAX([Created Date (UTC)]) as latest_gift
    FROM donations
    WHERE fundraiser_name IS NOT NULL AND TRIM(fundraiser_name) != ''
    GROUP BY LOWER(TRIM(fundraiser_name))
    ORDER BY total_raised DESC
    """
    df_f = pd.read_sql_query(query_fundraisers, conn)
    print(f"Found {len(df_f)} unique fundraisers (case-deduplicated) in donations table.")

    # 2. Query distinct campaign mappings with trimmed values
    query_camps = """
    SELECT DISTINCT
        LOWER(TRIM(fundraiser_name)) as lower_name,
        TRIM([Campaign Name]) as campaign_name,
        COALESCE(TRIM(Code), 'ALL') as code,
        COALESCE(TRIM(Platform), 'LaunchGood') as platform
    FROM donations
    WHERE fundraiser_name IS NOT NULL AND TRIM(fundraiser_name) != ''
      AND [Campaign Name] IS NOT NULL AND TRIM([Campaign Name]) != ''
    """
    df_c = pd.read_sql_query(query_camps, conn)
    print(f"Found {len(df_c)} distinct (fundraiser, campaign, code) mappings.")

    # Prepare batch records
    fundraiser_rows = []
    mapping_rows = []

    for _, row in df_f.iterrows():
        fname = str(row["fundraiser_name"]).strip()
        lname = str(row["lower_name"]).strip()
        raised = float(row["total_raised"] or 0.0)
        goal = calculate_benchmark_goal(raised)
        start_dt = str(row["earliest_gift"] or "").split("T")[0].split(" ")[0].strip()
        fid = f"fund_{uuid.uuid5(uuid.NAMESPACE_DNS, lname).hex[:16]}"

        fundraiser_rows.append((
            fid,
            fname,
            "",  # email
            "",  # phone
            goal,
            start_dt,
            "ACTIVE",
            f"Auto-seeded from historical donor data. Lifetime raised: £{raised:,.2f}",
            pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        # Associated campaigns
        subs = df_c[df_c["lower_name"] == lname]
        if subs.empty:
            map_id = f"fc_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{fid}_General_ALL').hex[:16]}"
            mapping_rows.append((
                map_id,
                fid,
                "General Appeal",
                "ALL",
                "ALL",
                pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
        else:
            for _, c_row in subs.iterrows():
                cname = str(c_row["campaign_name"]).strip()
                code = str(c_row["code"]).strip() if c_row["code"] else "ALL"
                plat = str(c_row["platform"]).strip() if c_row["platform"] else "ALL"
                map_id = f"fc_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{fid}_{cname}_{code}').hex[:16]}"
                mapping_rows.append((
                    map_id,
                    fid,
                    cname,
                    code,
                    plat,
                    pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
                ))

    # Apply to all DB targets
    for db_path in DB_PATHS:
        if not os.path.exists(os.path.dirname(db_path)):
            os.makedirs(os.path.dirname(db_path), exist_ok=True)

        target_conn = sqlite3.connect(db_path)
        init_tables(target_conn)
        cur = target_conn.cursor()

        # Clear and re-populate cleanly
        cur.execute("DELETE FROM fundraiser_campaigns")
        cur.execute("DELETE FROM fundraisers")

        cur.executemany("""
            INSERT INTO fundraisers (id, name, email, phone, target_goal, start_date, status, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, fundraiser_rows)

        cur.executemany("""
            INSERT OR IGNORE INTO fundraiser_campaigns (id, fundraiser_id, campaign_name, code, platform, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, mapping_rows)

        target_conn.commit()
        
        # Verify counts
        cur.execute("SELECT COUNT(*) FROM fundraisers")
        f_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM fundraiser_campaigns")
        fc_count = cur.fetchone()[0]
        target_conn.close()

        print(f"Successfully seeded {db_path}: {f_count} fundraisers, {fc_count} campaign mappings.")

    conn.close()

if __name__ == "__main__":
    seed_fundraisers()
