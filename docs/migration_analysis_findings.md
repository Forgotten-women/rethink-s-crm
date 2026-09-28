# Analysis & Gap Assessment: Rethink Humama Final Register Migration

**Document Version:** 1.0  
**Date:** September 9, 2026  
**Source File:** `Rethink_Humama_Final.xlsx` (Sheet: `MASTER FINAL REGISTER`)  
**Target Database:** `launchgood_donations.db`  

---

## 1. Executive Summary

This document analyzes the newly provided master register (`Rethink_Humama_Final.xlsx`) for migrating Rethink Charity's project classification hierarchy. 

The new register expands the classification model from a 54-code flat taxonomy into a granular **184 Final Allocation Code** taxonomy structured across **Portfolio**, **Department**, **Office**, and a 6-pillar **Programme Fund** governance model, backed by **Legacy Non-Zakat / Zakat Chart-of-Accounts** codes for financial expense reconciliation.

---

## 2. Structure of the New Register

The register contains **184 operational rows** with the following 11 attributes:

| Column Name | Type | Description / Purpose |
|---|---|---|
| **Final Allocation Code** | Primary Key | 4-part hierarchical code `<CTY>-<PORT>-<DEPT>-<OFF>` (e.g. `AFG-EDU-INS-QIN`, `SYR-INF-VIL-BAK`). Total: 184 unique codes. |
| **Country** | Dimension | Country or operational territory (10 distinct: Afghanistan, Egypt, Gaza, Global / Unspecified, South Africa, Syria, Turkey, United Kingdom, Yemen, Country To Be Confirmed). |
| **Portfolio** | Dimension (Top-level) | Organizational portfolio: `Education`, `General`, `Infrastructure`, `Social & Shelter`, `Medical`, `Livelihood`, `Admin`. |
| **Department** | Dimension (Mid-level) | Functional department (e.g. `Institutes`, `Schools`, `Sponsorships`, `Misc Infrastructure`, `Village`, `Residential Management`). |
| **Office** | Dimension (Sub-level) | Specific operational project / facility / initiative (e.g. `Quran Institute`, `Madrasah`, `Hope Village`). |
| **Programme Fund** | Governance Pillar | 6 core organizational funds. Used for high-level donor and executive reporting. |
| **Fund Code** | Identifier | Standard fund identifier (`F1-EMR`, `F2-OWH`, `F3-FAM`, `F4-EDU`, `F5-WAI`, `F6-ZKT`). |
| **Zakat Eligible (legacy basis)** | Compliance Flag | Canonical Zakat status (`Yes` or `No`). |
| **Legacy Non-Zakat Code(s)** | Expense Tracking | Numeric GL / Accounting ledger code for non-Zakat expenditure (e.g. `42030201101`). |
| **Legacy Zakat Code(s)** | Expense Tracking | Numeric GL / Accounting ledger code for Zakat-eligible expenditure (e.g. `42030201201`). |
| **Old Code(s)** | Mapping Reference | Semicolon/comma-separated legacy project codes previously used in CRM (e.g. `AFG-ONE-MAD; AFG-ONE-SPK`). |

---

## 3. Programme Funds & Fund Codes (New Data Explorer Filter)

The register introduces a 6-pillar fund hierarchy:

| Programme Fund Name | Fund Code | Code Count in Register |
|---|---|---|
| **1. Emergency / Most-Needed Fund** | `F1-EMR` | 33 codes |
| **2. Orphan / Widows / Hafidh Fund** | `F2-OWH` | 15 codes |
| **3. Families & Livelihoods Fund** | `F3-FAM` | 27 codes |
| **4. Education Fund** | `F4-EDU` | 18 codes |
| **5. Water & Infrastructure Fund** | `F5-WAI` | 89 codes |
| **6. Zakat Fund** | `F6-ZKT` | 2 codes |

*Requirement:* As requested, a new filter for **Programme Fund** will be added to the Data Explorer.

---

## 4. Database vs. Excel Comparison: The 54 Active DB Codes

Our database currently contains **54 active project codes** in `master_project_codes` (representing 106,834 donations, £3.8M+ raised, and 1,815 campaign mappings).

### Status Breakdown
- **Matched Exactly via `Old Code(s)`:** 45 codes
- **Discrepancies / Gaps Requiring Alignment:** 9 codes

### The 4 Completely Missing Project Operations
The user noted that **4 old codes are missing in the sheet**. Our analysis confirms that 4 projects and territories are entirely absent from `Rethink_Humama_Final.xlsx`:

| # | Missing DB Code | Country in DB | Department in DB | Office in DB | Donations Affected | Total Raised (£) | Campaigns Mapped | Reason in Sheet |
|---|---|---|---|---|---|---|---|---|
| **1** | `MAR-EMR-EQR` | Morocco | Emergency Aid | Earthquake Relief | **290** | **£16,746.43** | 1 | **Morocco** does not exist as a country in the new sheet (0 rows). |
| **2** | `SDN-EMR` | Sudan | Emergency Aid | Emergency Aid | **151** | **£9,298.26** | 3 | **Sudan** does not exist as a country in the new sheet (0 rows). |
| **3** | `UK-SP-HRDF` | UK | Sisters Project | Hardship Fund | **1,109** | **£40,776.65** | 1 | UK in sheet only has Food Bank (`GBR-SOC-AID-FBK`) and Containers (`GBR-SOC-AID-CTR`). The Sisters Project Hardship Fund is unlisted. |
| **4** | `ALL-WAT-WEL` | ALL | Water | Wells and Boreholes | **5** | **£180.00** | 1 | Global/All country in sheet has General Fund, Fidya, Fitrana, and Qurbani, but no global water well code. |

---

### 5 Additional Mapping Nuances Identified

Beyond the 4 completely missing operations above, our deep analysis revealed 5 additional codes that require explicit alignment:

| # | DB Code | Details & Financial Footprint | Finding in `Rethink_Humama_Final.xlsx` | Proposed Action / Question |
|---|---|---|---|---|
| **5** | `SYR-ONE-DEN` | Syria Dentist Scholarship<br>(57 donations, £12,089.56, 2 campaigns) | In Excel row 173, listed under `Country To Be Confirmed` with Old Code `TBC-ONE-DEN` and Final Code `TBC-EDU-SPN-DEN`. | Confirm if `SYR-ONE-DEN` should map to `TBC-EDU-SPN-DEN` or be renamed `SYR-EDU-SPN-DEN`. |
| **6** | `GAZ-ONE-SCH` | Gaza School<br>(**6,621 donations**, **£216,261.57**, 1 campaign) | In Excel, Gaza has NO school or general school code (only Quran Institute `GAZ-EDU-INS-QIN`). | High financial impact! Should `GAZ-ONE-SCH` map to a new code like `GAZ-EDU-SCH-GEN` or an existing Gaza code? |
| **7** | `GAZ-ONE-MUS` | Gaza Musallah<br>(**844 donations**, **£58,540.94**, 4 campaigns) | In Excel, Gaza has no Musallah or Masjid code under Infrastructure or Aid. | Should a new final code `GAZ-INF-MIS-MUS` (Gaza Musallah) be created, or mapped to General? |
| **8** | `GAZ-ONE-PRO` | Gaza Prosthetic Limbs<br>(200 donations, £6,504.76, 8 campaigns) | In Excel row 31, there is `GAZ-MED-SUP-ASD` (Gaza Medical Support - Assistive Device) with `Old Code(s)` currently blank (`nan`). | Confirm if `GAZ-ONE-PRO` (Prosthetic Limbs) maps to `GAZ-MED-SUP-ASD` (Assistive Device). |
| **9** | `AFG-INF` | Afghanistan General Infrastructure<br>(22 donations, £258.74, 1 campaign) | Excel has 5 specific Afghan infra codes: Housing (`AFG-INF-MIS-HOU`), Solar (`AFG-INF-MIS-SOL`), Masjid (`AFG-INF-MIS-MAS`), Water Well (`AFG-INF-MIS-WEL`), and Ashbal Renovation (`AFG-INF-MIS-AOR`), but no general infrastructure. | Confirm if `AFG-INF` maps to one of these or a general code. |

---

## 5. One-to-Many Split Mappings (Multi-Country / General Codes)

Several legacy codes were multi-country or umbrella codes, which the new register splits into country-specific final codes:

1. **`ALL-SEA-QUR`** (Qurbani) splits into:
   - `AFG-SOC-AID-QAA` (Afghanistan)
   - `GAZ-SOC-AID-QAA` (Gaza)
   - `SYR-SOC-AID-QAA` (Syria)
   - `YEM-SOC-AID-QAA` (Yemen)
2. **`ALL-ZKT`** (Zakat Direct) splits into:
   - `AFG-SOC-AID-ZKT` (Afghanistan)
   - `ALL-SOC-AID-ZKT` (Global / Unspecified)
   - `GAZ-SOC-AID-ZKT` (Gaza)
   - `SYR-SOC-AID-ZKT` (Syria)
3. **`ALL-GEN-GEN-GEN`** consolidates:
   - `ALL-GFN` (General Fund)
   - `ALL-DIV` (Diversify)
   - `ALL-SEA-FIT` (Fitrana)
   - `ALL-SEA-FID` (Fidya)

---

## 6. Expense Tracking & Legacy Accounting Ledger Codes

The columns `Legacy Non-Zakat Code(s)` (76 rows) and `Legacy Zakat Code(s)` (42 rows) contain numeric chart-of-accounts codes (e.g. `42030201101` and `42030201201`).

### Observations for Expense Tracking Architecture
1. **Expense Submission:** Currently, `/api/expenses/submit` allows selecting a project `code`. When users submit an expense, should they be able to select or see the ledger code (e.g. `42030201101`), or should the system auto-attach the appropriate Non-Zakat vs. Zakat ledger code based on whether the expense is marked Zakat?
2. **Export / Reconciliation:** Are these ledger codes required in the Excel/CSV exports from the Expense Tracker for finance/ERP import (e.g. Xero, Sage, QuickBooks)?
3. **Historical Expenses:** Existing expenses in `expense_requests` currently store the old project code. They will need to be re-keyed or mapped to the new codes.

---

## 7. Migration Execution Plan (Draft)

1. **Resolve Missing & Ambiguous Codes:** Agree on resolution for the 4 missing codes and 5 nuance codes via `/grill-me`.
2. **Update Master Project Codes Schema:** Add `programme_fund`, `fund_code`, `legacy_non_zakat_code`, `legacy_zakat_code`, and `old_codes` to `master_project_codes`.
3. **Import All 184 Final Allocation Codes:** Populate the Tier 1 registry with all 184 codes, retaining full mappings.
4. **Migrate Existing Donations & Platform Mappings:**
   - Map 1-to-1 legacy codes directly to their new Final Allocation Code.
   - For 1-to-many split codes (e.g. `ALL-SEA-QUR`, `ALL-ZKT`), use campaign country / platform metadata or maintain safe fallback.
   - Retain legacy code in `old_code` for historical traceability.
5. **Data Explorer & UI Enhancements:**
   - Add **Programme Fund** filter dropdown and horizontal pill in `HorizontalFilters.jsx` and `ExplorerView.jsx`.
   - Update `ClassificationView.jsx` and `ExpenseView.jsx` to support the new columns and ledger codes.
