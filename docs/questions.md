We're building the full Ramadhan 1448 (Feb/Mar 2027) campaign plan now, targeting £2m. To do that properly I need the complete picture of last Ramadhan (1447, Feb–Mar 2026). Please pull the following — raw exports (CSV) are better than summaries, from GiveBrite, LaunchGood and anything that came through the website, plus bank statements covering Feb–Apr 2026.

1. TOTALS BY SOURCE
- Gross raised by channel: GiveBrite, LaunchGood, website, bank transfers, masjid cash collections — separately, not combined.
- Gross raised by appeal/fund (e.g. Gaza, Syria, Afghanistan, Sudan; zakat vs sadaqah vs unrestricted).
- Daily totals across the month if possible — especially the last 10 nights vs the first 20 days.

2. PEER-TO-PEER DRIVE
- Number of individual fundraiser pages created, and total raised through P2P.
- Average and median raised per page, plus the top 10 pages (names and amounts).
- When pages were created (dates) — I want to see how early people signed up.
- Any team/group pages, and which masjids or community groups they came from.

3. DONORS
- Total unique donors, and new vs returning if the platforms show it.
- Average gift size.
- Top 50 donors by total giving across all sources (for major donor work).
- Email list: how many contactable addresses we hold, and where they're stored.

4. GIFT AID
- What declarations were captured on each platform.
- What's been claimed from HMRC vs still outstanding — I understand we're behind, so an honest picture of the backlog by platform and rough £ value.

5. PARTNERS AND DEPLOYMENTS
- Which masjids/organisations ran collections or promoted us, and roughly what each brought in.
- Anyone who fundraised around a deployment — who, when, how much.

6. RECURRING
- Any standing orders or recurring gifts set up during/after Ramadhan, and how many are still active.

If any of this simply doesn't exist, say so — "not tracked" is a useful answer and tells us what to fix this year.



Viewed questions.md:1-31
Ran command: `python -c "
import sqlite3
import pandas as pd
from config.settings import LOCAL_DB_PATH, PARQUET_PATH, PAYOUTS_PARQUET_PATH

print('--- PARQUET DONATIONS ---')
df = pd.read_parquet(PARQUET_PATH)
print('Shape:', df.shape)
print('Columns:', df.columns.tolist())
if 'Platform' in df.columns:
    print('Platforms:', df['Platform'].value_counts().to_dict())
if 'Created Date (UTC)' in df.columns:
    df['dt'] = pd.to_datetime(df['Created Date (UTC)'], errors='coerce')
    print('Date Range:', df['dt'].min(), 'to', df['dt'].max())

print('\n--- SQLITE TABLES ---')
conn = sqlite3.connect(LOCAL_DB_PATH)
cur = conn.cursor()
cur.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")
tables = [r[0] for r in cur.fetchall()]
print('Tables:', tables)
"`
Created inspect_data_sources.py
Ran command: `python scratch/inspect_data_sources.py`
Edited inspect_data_sources.py
Ran command: `python scratch/inspect_data_sources.py`
Created test_ramadhan_queries.py
Ran command: `python scratch/test_ramadhan_queries.py`
Created export_ramadhan_1447_report.py
Ran command: `python scripts/export_ramadhan_1447_report.py`

Here is the complete step-by-step extraction guide and data breakdown for your **Ramadhan 1447 (Feb–Mar 2026)** analysis to build the **Ramadhan 1448 (£2m target)** campaign plan.

---

### Quick Data Summary for Ramadhan 1447 (Feb 18 – Mar 20, 2026)

Based on the local database and parquet dataset, here is the baseline summary already extracted:

| Metric | Result in Current Dataset | Notes |
| :--- | :--- | :--- |
| **Total Gross Raised** | **£435,730.84** | Across 10,262 transactions in the database |
| **First 20 Days vs Last 10 Nights** | First 20 Days: **£235,922.64** (54.1%)<br>Last 10 Nights: **£199,808.20** (45.9%) | Last 10 nights generated nearly half the revenue in 1/3 of the time |
| **Unique Donors** | **3,035 unique donors** | **1,563 New (51.5%)** vs **1,472 Returning (48.5%)** |
| **Average Gift Size** | **£42.46** | High recurring volume keeps average gift size consistent |
| **Zakat vs Non-Zakat** | Zakat: **£111,746.28** (5,250 txns)<br>Non-Zakat: **£240,310.32** (4,088 txns) | £83.6k unassigned/general |
| **Gift Aid Declarations** | **1,515 'Yes'** (£173,207.31 eligible)<br>Est. Claim Value: **~£43,301.83** | 8,745 'No' / uncaptured |
| **Recurring vs One-Time** | Recurring: **£375,100.97** (8,808 txns)<br>One-Time: **£60,629.87** (1,454 txns) | 86% of total revenue came through daily/monthly recurring gifts |

---

### Step-by-Step Guide to Pull Every Detail

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                 DATA EXTRACTION PIPELINE                                 │
├──────────────────────────────┬─────────────────────────────┬─────────────────────────────┤
│ 1. CRM Dashboard UI          │ 2. Automated Python Script  │ 3. External Platform Exports│
│ (Instant visual filtering &  │ (Generates ready-to-use     │ (For P2P sub-reports, bank  │
│  CSV exports from browser)   │  CSVs in `reports/` folder) │  statements & cash logs)    │
└──────────────────────────────┴─────────────────────────────┴─────────────────────────────┘
```

---

### 1. TOTALS BY SOURCE

#### A. Gross Raised by Channel (GiveBrite, LaunchGood, Website, Bank, Masjid Cash)
* **In the CRM Dashboard**:
  1. Go to **Overview** or **Data Explorer** tab.
  2. Open the date filter and set `From: 2026-02-18` to `To: 2026-03-20`.
  3. Under the **Platform** dropdown, toggle between `LaunchGood`, `GiveBright`, `Paysuite`, and `Rethink Website`.
  4. The summary KPI cards will update immediately with the gross total, donation count, and average gift.
* **Via Automated Script**:
  - Run `python scripts/export_ramadhan_1447_report.py`.
  - Check [reports/1_totals_by_channel.csv](file:///c:/Users/Lenovo/Documents/Antigravity/Python_Visualization/reports/1_totals_by_channel.csv).
* **Missing / Raw Exports Needed**:
  - **Bank Transfers & Masjid Cash Collections**: These are currently **NOT TRACKED** in the digital platform datasets. 
  - *Action*: Export Feb–Apr 2026 bank statements (CSV) and any masjid collection count sheets. They can be imported into the CRM via the **Admin & Data** tab (`Upload Offline / Bank CSV`).

#### B. Gross Raised by Appeal / Fund & Zakat vs Sadaqah
* **In the CRM Dashboard**:
  1. Go to **Data Explorer** &rarr; filter date range `2026-02-18` to `2026-03-20`.
  2. Group or filter by **Heading** (e.g. `General Fund`, `Emergency Aid`, `Sponsorships`, `Food`, `Zakat Direct`).
  3. Filter by **Zakat Status** (`Zakat` vs `Non-Zakat`).
* **Via Automated Script**:
  - Check [reports/1_totals_by_fund_heading.csv](file:///c:/Users/Lenovo/Documents/Antigravity/Python_Visualization/reports/1_totals_by_fund_heading.csv).

#### C. Daily Totals across the Month (First 20 Days vs Last 10 Nights)
* **In the CRM Dashboard**:
  - In **Overview**, the timeline chart displays the daily breakdown.
* **Via Automated Script**:
  - Check [reports/1_daily_totals.csv](file:///c:/Users/Lenovo/Documents/Antigravity/Python_Visualization/reports/1_daily_totals.csv).
  - *Calculation Breakdown*:
    - **First 20 Days (Feb 18 – Mar 09)**: £235,922.64 across 6,249 transactions.
    - **Last 10 Nights (Mar 10 – Mar 20)**: £199,808.20 across 4,013 transactions (Odd nights spiked over 2.5x vs even nights).

---

### 2. PEER-TO-PEER (P2P) DRIVE

* **What exists in current database**:
  - `Community Name` and `Community URL` track 32 community drives.
* **Individual Fundraiser Pages (Average, Median, Top 10, Signup Dates)**:
  - In the main LaunchGood transaction export, individual sub-page IDs are often rolled up under the parent campaign name.
* **Steps to Get the Full P2P Picture**:
  1. **LaunchGood Export**: Log in to LaunchGood Admin &rarr; **Campaigns** &rarr; **Teams & Fundraisers** &rarr; **Export Fundraiser Pages Report (CSV)**. This report contains:
     - Fundraiser Page Name, Creator Name & Email.
     - Page Creation Date (shows how early people signed up).
     - Target Goal vs Amount Raised.
  2. **GiveBrite Export**: Log in to GiveBrite Admin &rarr; **Fundraising Pages** &rarr; **Export All Pages (CSV)**.
  3. **In the CRM**:
     - Once exported, open the **Fundraiser Tracking** tab.
     - You can see assigned campaigns, inception dates, and leaderboard rankings with median/average metrics.

---

### 3. DONORS

#### A. Total Unique Donors & New vs Returning
* **Calculation**:
  - **Total Unique Donors**: **3,035** (deduplicated by email).
  - **New Donors (51.5%)**: 1,563 donors had their first-ever recorded gift during Ramadhan 1447.
  - **Returning Donors (48.5%)**: 1,472 donors had donated prior to Feb 18, 2026.

#### B. Top 50 Major Donors
* **Via Automated Script**:
  - Generated in [reports/3_top_50_major_donors.csv](file:///c:/Users/Lenovo/Documents/Antigravity/Python_Visualization/reports/3_top_50_major_donors.csv).
  - Contains: Donor Email, Full Name, Billing Country, Total Given, and Donation Count.
* **In the CRM Dashboard**:
  1. Go to **Lifetime LTV** or **Data Explorer**.
  2. Filter by date `2026-02-18` to `2026-03-20`.
  3. Click the table column header **Total LTV / Amount** to sort descending.
  4. Click on any donor to open the **Donor 360° Profile Drawer**.

#### C. Contactable Email List & Storage
* **Where Stored**: Stored in `data/database.sqlite` (table `donations`) and `data/donations.parquet`.
* **Marketing Consent**:
  - In Ramadhan 1447 data: **243 donors explicitly opted in (`yes`)**; 10,017 were recorded as `no` (or platform default un-ticked).
  - *Recommendation for 1448*: Check the platform checkout settings to optimize the opt-in checkbox language and capture more GDPR-compliant subscribers.

---

### 4. GIFT AID

* **Captured Declarations in Dataset**:
  - **1,515 donations** opted in for Gift Aid (£173,207.31 total).
  - **Potential Gift Aid Reclaim Value**: **£43,301.83** (25% on eligible donations).
  - **8,745 donations** were non-Gift Aid / uncaptured (£262,523.53).
* **HMRC Claims vs Outstanding Backlog**:
  - **Not tracked in donor CSVs**: The raw donation exports only show if the donor ticked the Gift Aid box (`yes`/`no`), not whether an HMRC claim submission was filed.
* **Steps to Get the Claim Backlog**:
  1. **GiveBrite**: Check if GiveBrite's automated Gift Aid distribution was enabled (GiveBrite claims on your behalf and pays out separately).
  2. **LaunchGood / Website**: Check HMRC Charities Online portal or your Gift Aid submission logs for claim reference numbers covering Feb–Apr 2026.
  3. Any `Gift Aid == 'yes'` transaction without an HMRC submission reference in your finance records is currently **outstanding backlog**.

---

### 5. PARTNERS AND DEPLOYMENTS

* **Masjids / Organisations Collections**:
  - Pull from the `Community Name` column in the LaunchGood dataset (32 community partner campaigns identified).
  - For offline collections (e.g. Friday bucket collections), check the cash log / bank deposit slips referencing the specific masjid name.
* **Deployment-Specific Fundraisers**:
  - In the CRM, search for campaign codes prefixed with `DEP-` or deployment destinations (e.g. `SYR-`, `AFG-`, `TUR-`).
  - Cross-reference with the volunteer/deployment roster list.

---

### 6. RECURRING GIVING

* **In Dataset**:
  - **Recurring Payments during Ramadhan**: **8,808 transactions** (£375,100.97).
  - **One-Time Payments**: **1,454 transactions** (£60,629.87).
* **Checking Currently Active Recurring Subscriptions**:
  - `Payment Frequency` in transaction files indicates the donation was part of a recurring plan (e.g. Daily 30-day Ramadhan giving or Monthly sponsorship).
  - To check how many are **still active today**:
    1. **Stripe / Payment Gateway**: Log in to Stripe/Paysuite &rarr; **Billing &rarr; Subscriptions** &rarr; Filter by `Created: Feb–Apr 2026` &rarr; Check status (`Active` vs `Canceled`).
    2. **LaunchGood Auto-Giving**: LaunchGood Ramadhan daily giving automatically ends after 30 days unless the donor opted for monthly ongoing giving.

---

### Summary Checklist of What to Run / Pull:

1. **Local Report (Ready Now)**:
   - Run the script in terminal:
     ```bash
     python scripts/export_ramadhan_1447_report.py
     ```
   - Generated CSVs are in the `reports/` folder:
     - [1_totals_by_channel.csv](file:///c:/Users/Lenovo/Documents/Antigravity/Python_Visualization/reports/1_totals_by_channel.csv)
     - [1_totals_by_fund_heading.csv](file:///c:/Users/Lenovo/Documents/Antigravity/Python_Visualization/reports/1_totals_by_fund_heading.csv)
     - [1_daily_totals.csv](file:///c:/Users/Lenovo/Documents/Antigravity/Python_Visualization/reports/1_daily_totals.csv)
     - [3_top_50_major_donors.csv](file:///c:/Users/Lenovo/Documents/Antigravity/Python_Visualization/reports/3_top_50_major_donors.csv)
     - [4_gift_aid_summary.csv](file:///c:/Users/Lenovo/Documents/Antigravity/Python_Visualization/reports/4_gift_aid_summary.csv)

2. **External Files to Collect (Not in current database)**:
   - **Bank statements (Feb–Apr 2026)** for direct BACS/standing orders & cash deposits.
   - **LaunchGood Team / P2P Fundraiser report** (for individual page creator signup dates).
   - **GiveBrite Ramadhan 2026 raw transaction export** (if not already merged).
   - **HMRC Gift Aid submission history** to confirm what portion of the £43.3k Gift Aid has been claimed.