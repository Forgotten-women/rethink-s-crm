"""
Payout Enrichment & Reconciliation Service for GiveBrite Payouts (Rethink & Iqra).

Features:
- Native in-database reference loading from SQLite `donations` table with zero dependency on loose Excel files.
- Platform A: Rethink GiveBrite Transfers / Payouts (matched on charge_id / Donation ID).
- Platform B: Iqra GiveBrite Payouts (4-tier fallback matching: charge_id, (name+net), (name+gross), name).
- 10-Sheet Executive Accounting Pack Generator (OpenPyXL) with professional styling and audit tables.
- Automatic ledger ingestion into `payout_settlements` and fast sync to mark donations as `Payout Settled = 'Yes'`.
"""

import io
import os
import re
import uuid
import sqlite3
import datetime
import logging
import pandas as pd
import numpy as np
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from config.settings import LOCAL_DB_PATH, PARQUET_PATH, PAYOUTS_PARQUET_PATH

logger = logging.getLogger("payout_enrichment")

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data_cache", "payout_reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


# ==============================================================================
# Helper Normalization Functions
# ==============================================================================

def clean_name(s):
    """Normalize names: remove emojis, special characters, extra spaces, and lowercase."""
    if pd.isna(s):
        return ""
    s_str = str(s).strip()
    if s_str.lower() in ("nan", "none", "null", "n/a", "<na>"):
        return ""
    s_str = re.sub(r"[^\w\s]", " ", s_str)
    return " ".join(s_str.lower().split())


def get_full_name(fn, ln):
    """Combine first and last name cleanly."""
    c_fn = clean_name(fn)
    c_ln = clean_name(ln)
    if c_fn and c_ln:
        return f"{c_fn} {c_ln}"
    return c_fn or c_ln


def find_column(df, candidate_names):
    """Find a column in df matching any name in candidate_names (case-insensitive, normalized)."""
    df_cols = list(df.columns)
    for name in candidate_names:
        if name in df.columns:
            return name

    def normalize(s):
        return str(s).lower().replace(" ", "").replace("_", "").replace("-", "")

    normalized_candidates = [normalize(c) for c in candidate_names]
    for col in df_cols:
        if normalize(col) in normalized_candidates:
            return col
    return None


# ==============================================================================
# Reference Data Loading (Live DB -> Memory)
# ==============================================================================

def load_donor_reference(company_id: str = "rethink"):
    """
    Loads donor reference dictionaries strictly from the CRM database's `donations` table.
    Filters by the target company_id to guarantee multi-tenant charity isolation.
    """
    cid = str(company_id or "rethink").strip().lower()
    logger.info(f"Loading live reference donor metadata for company '{cid}'...")

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    query = """
        SELECT 
            "Donation ID", charge_id, "First Name", "Last Name", 
            "Heading", "Sub-Heading", "Department", "Office",
            "Code", "Country", "Billing Country", "Target Country",
            "Zakat Eligibility", "is_zakat", "donation_type",
            "payment_method_type", gateway, "Payment Type",
            "Campaign Name", "Programme Fund", "Portfolio",
            "Total Online Donations Net Amount in Settled Currency",
            "Total Online Donation Gross Amount in Settled Currency",
            "Created Date (UTC)"
        FROM donations
        WHERE LOWER(TRIM(company_id)) = ?
    """
    try:
        df_ref = pd.read_sql_query(query, conn, params=(cid,))
    finally:
        conn.close()

    if df_ref.empty:
        logger.warning(f"No donor records found in donations table for company '{cid}'!")
        return {"by_cid": {}, "by_name_net": {}, "by_name_gross": {}, "by_name": {}}

    by_cid = {}
    by_name_net = {}
    by_name_gross = {}
    by_name = {}

    for _, row in df_ref.iterrows():
        # Standardize charge_id / Donation ID
        c_id = str(row.get("charge_id") or "").strip()
        d_id = str(row.get("Donation ID") or "").strip()
        
        # Primary identifiers
        cids_to_register = []
        if c_id and c_id.lower() not in ("nan", "none", ""):
            cids_to_register.append(c_id)
            cids_to_register.append(c_id.lower())
        if d_id and d_id.lower() not in ("nan", "none", ""):
            cids_to_register.append(d_id)
            cids_to_register.append(d_id.lower())

        # Heading & Subheading (Department & Office)
        heading = row.get("Heading") or row.get("Department") or row.get("Campaign Name")
        subheading = row.get("Sub-Heading") or row.get("Office")
        code = row.get("Code")
        country = row.get("Country") or row.get("Target Country") or row.get("Billing Country")
        
        zakat = row.get("Zakat Eligibility")
        if pd.isna(zakat) or not str(zakat).strip():
            is_z = row.get("is_zakat")
            if is_z in (True, 1, "1", "True", "true", "yes", "Yes"):
                zakat = "Zakat"
            else:
                zakat = "Non-Zakat"

        c_date = row.get("Created Date (UTC)")
        c_date_str = str(c_date).split(" ")[0].split("T")[0] if pd.notna(c_date) else None

        dt_val = row.get("donation_type") or row.get("Payment Type")
        pm_val = row.get("payment_method_type") or row.get("gateway") or "GiveBrite"

        record = {
            "Country": str(country).strip() if pd.notna(country) else "Global / Unspecified",
            "Donation Type": str(dt_val).strip() if pd.notna(dt_val) else "One-off",
            "donation_type": str(dt_val).strip() if pd.notna(dt_val) else "One-off",
            "payment method": str(pm_val).strip() if pd.notna(pm_val) else "GiveBrite",
            "Heading": str(heading).strip() if pd.notna(heading) else "General",
            "Subheading": str(subheading).strip() if pd.notna(subheading) else "General",
            "Code": str(code).strip() if pd.notna(code) else "ALL-GEN-GEN-GEN",
            "Zakat Eligibility": str(zakat).strip() if pd.notna(zakat) else "Non-Zakat",
            "Created Date (UTC)": c_date_str,
            "Campaign Name": str(row.get("Campaign Name") or "").strip() or "General Campaign",
            "Programme Fund": str(row.get("Programme Fund") or "").strip() or "General Fund",
            "Portfolio": str(row.get("Portfolio") or "").strip() or "General",
        }

        for cid_key in cids_to_register:
            if cid_key not in by_cid:
                by_cid[cid_key] = record

        # Name + Amount Indexing for fallback matching
        full = get_full_name(row.get("First Name"), row.get("Last Name"))
        if full:
            net_val = None
            try:
                raw_net = row.get("Total Online Donations Net Amount in Settled Currency")
                if pd.notna(raw_net):
                    net_val = round(float(str(raw_net).replace("£", "").replace(",", "").strip()), 2)
            except Exception:
                pass

            gross_val = None
            try:
                raw_gross = row.get("Total Online Donation Gross Amount in Settled Currency")
                if pd.notna(raw_gross):
                    gross_val = round(float(str(raw_gross).replace("£", "").replace(",", "").strip()), 2)
            except Exception:
                pass

            if net_val is not None and (full, net_val) not in by_name_net:
                by_name_net[(full, net_val)] = record
            if gross_val is not None and (full, gross_val) not in by_name_gross:
                by_name_gross[(full, gross_val)] = record
            if full not in by_name:
                by_name[full] = record

    logger.info(f"Loaded reference for {cid}: {len(by_cid)} charge IDs, {len(by_name_net)} (name+net) pairs, {len(by_name)} unique donor names.")
    return {
        "by_cid": by_cid,
        "by_name_net": by_name_net,
        "by_name_gross": by_name_gross,
        "by_name": by_name,
    }


# ==============================================================================
# OpenPyXL Styles & Format Constants
# ==============================================================================

NAVY_DARK = "0F2C59"
NAVY_HEADER = "1B365D"
SLATE_HEADER = "2B4C7E"
ROW_ZEBRA = "F9FAFC"
TOTAL_FILL = "E8EEF5"
BORDER_GRAY = "D0D7DE"

font_banner = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
font_subtitle = Font(name="Calibri", size=10, italic=True, color="E0E0E0")
font_section = Font(name="Calibri", size=11, bold=True, color="1B365D")
font_header = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
font_data = Font(name="Calibri", size=10)
font_total = Font(name="Calibri", size=10, bold=True, color="0F2C59")

fill_banner = PatternFill(start_color=NAVY_DARK, end_color=NAVY_DARK, fill_type="solid")
fill_header = PatternFill(start_color=NAVY_HEADER, end_color=NAVY_HEADER, fill_type="solid")
fill_header_slate = PatternFill(start_color=SLATE_HEADER, end_color=SLATE_HEADER, fill_type="solid")
fill_zebra = PatternFill(start_color=ROW_ZEBRA, end_color=ROW_ZEBRA, fill_type="solid")
fill_total = PatternFill(start_color=TOTAL_FILL, end_color=TOTAL_FILL, fill_type="solid")

thin_side = Side(style="thin", color=BORDER_GRAY)
border_cell = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
border_total = Border(
    left=thin_side,
    right=thin_side,
    top=Side(style="thin", color=NAVY_HEADER),
    bottom=Side(style="double", color=NAVY_HEADER)
)

align_left = Alignment(horizontal="left", vertical="center")
align_right = Alignment(horizontal="right", vertical="center")
align_center = Alignment(horizontal="center", vertical="center")
align_header = Alignment(horizontal="center", vertical="center", wrap_text=True)

FMT_CURRENCY = "£#,##0.00"
FMT_COUNT = "#,##0"
FMT_PCT = "0.00%"


def auto_fit_columns(ws, min_col=1, max_col=None, padding=3, min_width=11, max_width=45):
    """Auto-adjust worksheet column widths so content is clean and legible."""
    if max_col is None:
        max_col = ws.max_column
    for col_idx in range(min_col, max_col + 1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for cell in ws[col_letter]:
            if cell.row in (1, 2) and ws.cell(row=cell.row, column=1).value and ws.cell(row=cell.row, column=1).font.size > 11:
                continue
            val = cell.value
            if val is not None:
                val_str = str(val)
                if isinstance(val, float):
                    val_str = f"£{val:,.2f}"
                max_len = max(max_len, len(val_str))
        ws.column_dimensions[col_letter].width = max(min_width, min(max_width, max_len + padding))


# ==============================================================================
# Multi-Sheet Accounting Report Generator (OpenPyXL)
# ==============================================================================

def build_executive_summary_sheet(ws, df, payout_filename, company_title="IQRA CHARITY"):
    """Generate the Executive Summary dashboard sheet for accounts."""
    ws.views.sheetView[0].showGridLines = True
    
    ws.merge_cells("A1:F1")
    ws["A1"] = f"{company_title.upper()} — PAYOUT RECONCILIATION & ACCOUNTS AUDIT REPORT"
    ws["A1"].font = font_banner
    ws["A1"].fill = fill_banner
    ws["A1"].alignment = align_center
    ws.row_dimensions[1].height = 28

    earliest_date = str(df["Created Date (UTC)"].dropna().min()) if "Created Date (UTC)" in df.columns and df["Created Date (UTC)"].dropna().any() else "N/A"
    latest_date = str(df["Created Date (UTC)"].dropna().max()) if "Created Date (UTC)" in df.columns and df["Created Date (UTC)"].dropna().any() else "N/A"
    currency = "GBP"

    ws.merge_cells("A2:F2")
    ws["A2"] = f"Source Batch: {payout_filename}  |  Period: {earliest_date} to {latest_date}  |  Settlement Currency: {currency}"
    ws["A2"].font = font_subtitle
    ws["A2"].fill = fill_banner
    ws["A2"].alignment = align_center
    ws.row_dimensions[2].height = 18

    total_tx = len(df)
    gross_total = float(df["amount"].sum()) if "amount" in df.columns else (float(df["Gross Amount"].sum()) if "Gross Amount" in df.columns else 0.0)
    fee_total = float(df["fee_amount"].sum()) if "fee_amount" in df.columns else (float(df["Fees"].sum()) if "Fees" in df.columns else 0.0)
    net_total = float(df["amount_charity"].sum()) if "amount_charity" in df.columns else (float(df["Net Amount"].sum()) if "Net Amount" in df.columns else (gross_total - fee_total))
    
    fee_ratio = (fee_total / gross_total) if gross_total > 0 else 0.0
    avg_donation = (gross_total / total_tx) if total_tx > 0 else 0.0

    zakat_mask = df["Zakat Eligibility"].astype(str).str.lower() == "zakat"
    zakat_net = float(df[zakat_mask]["amount_charity"].sum()) if "amount_charity" in df.columns else float(df[zakat_mask]["net_amt"].sum() if "net_amt" in df.columns else 0.0)
    zakat_count = int(zakat_mask.sum())
    zakat_share = (zakat_net / net_total) if net_total > 0 else 0.0

    non_zakat_net = net_total - zakat_net
    non_zakat_count = total_tx - zakat_count
    non_zakat_share = (non_zakat_net / net_total) if net_total > 0 else 0.0

    giftaid_col = find_column(df, ["is_giftaid", "Gift Aid", "Gift Aid (yes or no)"])
    if giftaid_col:
        giftaid_mask = df[giftaid_col].astype(str).str.strip().isin(["1", "1.0", "true", "True", "yes", "Yes"])
        giftaid_count = int(giftaid_mask.sum())
        giftaid_gross = float(df[giftaid_mask]["amount"].sum()) if "amount" in df.columns else (float(df[giftaid_mask]["gross_amt"].sum()) if "gross_amt" in df.columns else 0.0)
    else:
        giftaid_count = 0
        giftaid_gross = 0.0
    giftaid_claimable = round(giftaid_gross * 0.25, 2)

    # Section 1: Financial Reconciliation Summary
    ws.cell(row=4, column=1, value="1. Financial Reconciliation Summary").font = font_section
    headers_sec1 = ["Metric Description", "Value", "Notes / Effective Rate"]
    for col_idx, h in enumerate(headers_sec1, start=1):
        cell = ws.cell(row=5, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = border_cell
    ws.row_dimensions[5].height = 22

    rows_sec1 = [
        ("Total Gross Donor Contributions", gross_total, FMT_CURRENCY, f"{total_tx:,} transactions received"),
        ("Payment Processing & Gateway Fees", fee_total, FMT_CURRENCY, f"Effective Fee Rate: {fee_ratio:.2%}"),
        ("Net Settlement / Disbursed to Charity", net_total, FMT_CURRENCY, "100.00% of net payout funds"),
        ("Effective Overall Fee Ratio", fee_ratio, FMT_PCT, "Total fees paid / Gross donations"),
        ("Average Contribution Size", avg_donation, FMT_CURRENCY, "Gross donations / Total transactions"),
    ]

    for r_idx, (desc, val, fmt, note) in enumerate(rows_sec1, start=6):
        c1 = ws.cell(row=r_idx, column=1, value=desc)
        c2 = ws.cell(row=r_idx, column=2, value=val)
        c3 = ws.cell(row=r_idx, column=3, value=note)
        
        c1.font = font_total if "Net" in desc or "Gross" in desc else font_data
        c2.font = font_total if "Net" in desc or "Gross" in desc else font_data
        c3.font = font_data
        c2.number_format = fmt
        
        c1.alignment = align_left
        c2.alignment = align_right
        c3.alignment = align_left
        
        c1.border = border_cell
        c2.border = border_cell
        c3.border = border_cell
        
        if "Net" in desc:
            c1.fill = fill_total; c2.fill = fill_total; c3.fill = fill_total
        elif r_idx % 2 == 1:
            c1.fill = fill_zebra; c2.fill = fill_zebra; c3.fill = fill_zebra
        ws.row_dimensions[r_idx].height = 20

    # Section 2: Zakat Fund Allocation
    curr_row = 13
    ws.cell(row=curr_row, column=1, value="2. Zakat vs Non-Zakat Fund Allocation").font = font_section
    curr_row += 1
    
    headers_sec2 = ["Classification", "Transactions", "Net Amount (£)", "% Share of Payout"]
    for col_idx, h in enumerate(headers_sec2, start=1):
        cell = ws.cell(row=curr_row, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_slate
        cell.alignment = align_center
        cell.border = border_cell
    ws.row_dimensions[curr_row].height = 22

    rows_sec2 = [
        ("Zakat Eligible Donations", zakat_count, zakat_net, zakat_share),
        ("Non-Zakat / General Donations", non_zakat_count, non_zakat_net, non_zakat_share),
    ]

    for item in rows_sec2:
        curr_row += 1
        c1 = ws.cell(row=curr_row, column=1, value=item[0])
        c2 = ws.cell(row=curr_row, column=2, value=item[1])
        c3 = ws.cell(row=curr_row, column=3, value=item[2])
        c4 = ws.cell(row=curr_row, column=4, value=item[3])

        c1.font = font_data; c2.font = font_data; c3.font = font_data; c4.font = font_data
        c2.number_format = FMT_COUNT
        c3.number_format = FMT_CURRENCY
        c4.number_format = FMT_PCT

        c1.alignment = align_left; c2.alignment = align_right; c3.alignment = align_right; c4.alignment = align_right
        c1.border = border_cell; c2.border = border_cell; c3.border = border_cell; c4.border = border_cell
        ws.row_dimensions[curr_row].height = 20

    # Total row for Zakat
    curr_row += 1
    t1 = ws.cell(row=curr_row, column=1, value="Total Payout Allocation")
    t2 = ws.cell(row=curr_row, column=2, value=total_tx)
    t3 = ws.cell(row=curr_row, column=3, value=net_total)
    t4 = ws.cell(row=curr_row, column=4, value=1.0)
    for c in [t1, t2, t3, t4]:
        c.font = font_total
        c.fill = fill_total
        c.border = border_total
    t2.number_format = FMT_COUNT
    t3.number_format = FMT_CURRENCY
    t4.number_format = FMT_PCT
    t1.alignment = align_left; t2.alignment = align_right; t3.alignment = align_right; t4.alignment = align_right
    ws.row_dimensions[curr_row].height = 22

    # Section 3: Gift Aid & Compliance
    curr_row += 3
    ws.cell(row=curr_row, column=1, value="3. Gift Aid Audit Metrics").font = font_section
    curr_row += 1
    
    headers_sec3 = ["Gift Aid Line Item", "Value", "Estimated HMRC Claim"]
    for col_idx, h in enumerate(headers_sec3, start=1):
        cell = ws.cell(row=curr_row, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_slate
        cell.alignment = align_center
        cell.border = border_cell
    ws.row_dimensions[curr_row].height = 22

    rows_sec3 = [
        ("Gift Aid Declared Transactions", f"{giftaid_count} donors", "Eligible for 25% tax reclaim"),
        ("Gross Amount with Gift Aid Declaration", giftaid_gross, "Subject to Gift Aid submission"),
        ("Potential Gift Aid Reclaim (25%)", giftaid_claimable, "Additional funds reclaimable from HMRC"),
    ]

    for item in rows_sec3:
        curr_row += 1
        c1 = ws.cell(row=curr_row, column=1, value=item[0])
        c2 = ws.cell(row=curr_row, column=2, value=item[1])
        c3 = ws.cell(row=curr_row, column=3, value=item[2])

        c1.font = font_total if "Potential" in item[0] else font_data
        c2.font = font_total if "Potential" in item[0] else font_data
        c3.font = font_data
        if isinstance(item[1], (int, float)):
            c2.number_format = FMT_CURRENCY

        c1.alignment = align_left
        c2.alignment = align_right if isinstance(item[1], (int, float)) else align_left
        c3.alignment = align_left
        
        c1.border = border_cell; c2.border = border_cell; c3.border = border_cell
        if "Potential" in item[0]:
            c1.fill = fill_total; c2.fill = fill_total; c3.fill = fill_total
        ws.row_dimensions[curr_row].height = 20

    auto_fit_columns(ws, max_col=6)


def build_breakdown_sheet(ws, title, group_cols, df, col_headers):
    """Generic builder for Code, Campaign, Department, Country, and Zakat breakdown sheets."""
    ws.views.sheetView[0].showGridLines = True
    
    num_cols = len(col_headers)
    end_col_letter = get_column_letter(num_cols)
    ws.merge_cells(f"A1:{end_col_letter}1")
    ws["A1"] = title.upper()
    ws["A1"].font = font_banner
    ws["A1"].fill = fill_banner
    ws["A1"].alignment = align_center
    ws.row_dimensions[1].height = 26

    # Determine amount columns
    amt_col = "amount" if "amount" in df.columns else ("Total Online Donation Gross Amount in Settled Currency" if "Total Online Donation Gross Amount in Settled Currency" in df.columns else "gross_amt")
    fee_col = "fee_amount" if "fee_amount" in df.columns else ("Total Processing Fees Paid by CC In Settled Currency" if "Total Processing Fees Paid by CC In Settled Currency" in df.columns else "fee_amt")
    net_col = "amount_charity" if "amount_charity" in df.columns else ("Total Online Donations Net Amount in Settled Currency" if "Total Online Donations Net Amount in Settled Currency" in df.columns else "net_amt")

    # Safe fallback if grouping column is missing
    valid_group_cols = [c for c in group_cols if c in df.columns]
    if not valid_group_cols:
        return

    agg_df = df.groupby(valid_group_cols, dropna=False).agg(
        donations_count=(amt_col, "count"),
        gross_amount=(amt_col, "sum"),
        fee_amount=(fee_col, "sum"),
        net_amount=(net_col, "sum")
    ).reset_index()

    total_net = float(agg_df["net_amount"].sum())
    total_gross = float(agg_df["gross_amount"].sum())
    total_fee = float(agg_df["fee_amount"].sum())
    total_count = int(agg_df["donations_count"].sum())

    agg_df["fee_ratio"] = (agg_df["fee_amount"] / agg_df["gross_amount"].replace(0, pd.NA)).fillna(0)
    agg_df["share_pct"] = (agg_df["net_amount"] / total_net) if total_net > 0 else 0
    agg_df = agg_df.sort_values(by="net_amount", ascending=False)

    header_row = 3
    for col_idx, h in enumerate(col_headers, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_header
        cell.border = border_cell
    ws.row_dimensions[header_row].height = 26

    curr_row = header_row
    for _, row in agg_df.iterrows():
        curr_row += 1
        ws.row_dimensions[curr_row].height = 19
        zebra = (curr_row % 2 == 1)

        for g_idx, g_col in enumerate(valid_group_cols, start=1):
            val = row[g_col]
            cell = ws.cell(row=curr_row, column=g_idx, value=str(val) if pd.notna(val) else "Unassigned")
            cell.font = font_data
            cell.alignment = align_center if g_col in ("Code", "Country", "Zakat Eligibility") else align_left
            cell.border = border_cell
            if zebra:
                cell.fill = fill_zebra

        base_col = len(valid_group_cols) + 1
        c_count = ws.cell(row=curr_row, column=base_col, value=int(row["donations_count"]))
        c_gross = ws.cell(row=curr_row, column=base_col + 1, value=float(row["gross_amount"]))
        c_fee = ws.cell(row=curr_row, column=base_col + 2, value=float(row["fee_amount"]))
        c_ratio = ws.cell(row=curr_row, column=base_col + 3, value=float(row["fee_ratio"]))
        c_net = ws.cell(row=curr_row, column=base_col + 4, value=float(row["net_amount"]))
        c_share = ws.cell(row=curr_row, column=base_col + 5, value=float(row["share_pct"]))

        c_count.number_format = FMT_COUNT
        c_gross.number_format = FMT_CURRENCY
        c_fee.number_format = FMT_CURRENCY
        c_ratio.number_format = FMT_PCT
        c_net.number_format = FMT_CURRENCY
        c_share.number_format = FMT_PCT

        for c in [c_count, c_gross, c_fee, c_ratio, c_net, c_share]:
            c.font = font_data
            c.alignment = align_right
            c.border = border_cell
            if zebra:
                cell.fill = fill_zebra

    # Total Row
    curr_row += 1
    ws.row_dimensions[curr_row].height = 24
    
    t_label = ws.cell(row=curr_row, column=1, value="TOTAL ALLOCATIONS")
    t_label.font = font_total
    t_label.fill = fill_total
    t_label.border = border_total
    t_label.alignment = align_left

    for g_idx in range(2, len(valid_group_cols) + 1):
        cell = ws.cell(row=curr_row, column=g_idx, value="")
        cell.font = font_total
        cell.fill = fill_total
        cell.border = border_total

    base_col = len(valid_group_cols) + 1
    t_count = ws.cell(row=curr_row, column=base_col, value=total_count)
    t_gross = ws.cell(row=curr_row, column=base_col + 1, value=total_gross)
    t_fee = ws.cell(row=curr_row, column=base_col + 2, value=total_fee)
    t_ratio = ws.cell(row=curr_row, column=base_col + 3, value=(total_fee / total_gross) if total_gross > 0 else 0)
    t_net = ws.cell(row=curr_row, column=base_col + 4, value=total_net)
    t_share = ws.cell(row=curr_row, column=base_col + 5, value=1.0)

    t_count.number_format = FMT_COUNT
    t_gross.number_format = FMT_CURRENCY
    t_fee.number_format = FMT_CURRENCY
    t_ratio.number_format = FMT_PCT
    t_net.number_format = FMT_CURRENCY
    t_share.number_format = FMT_PCT

    for c in [t_count, t_gross, t_fee, t_ratio, t_net, t_share]:
        c.font = font_total
        c.fill = fill_total
        c.border = border_total
        c.alignment = align_right

    ws.freeze_panes = f"A{header_row + 1}"
    auto_fit_columns(ws, max_col=num_cols)


def build_daily_breakdown_sheet(ws, df):
    """Generate daily timeline breakdown of donations."""
    ws.views.sheetView[0].showGridLines = True
    
    date_col = "Created Date (UTC)" if "Created Date (UTC)" in df.columns else ("created_at" if "created_at" in df.columns else "Created")
    if date_col not in df.columns:
        return

    amt_col = "amount" if "amount" in df.columns else ("gross_amt" if "gross_amt" in df.columns else "Gross Amount")
    fee_col = "fee_amount" if "fee_amount" in df.columns else ("fee_amt" if "fee_amt" in df.columns else "Fees")
    net_col = "amount_charity" if "amount_charity" in df.columns else ("net_amt" if "net_amt" in df.columns else "Net Amount")

    col_headers = ["Date (UTC)", "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)"]
    num_cols = len(col_headers)
    end_col_letter = get_column_letter(num_cols)

    ws.merge_cells(f"A1:{end_col_letter}1")
    ws["A1"] = "DAILY SETTLEMENT & RECONCILIATION BREAKDOWN"
    ws["A1"].font = font_banner
    ws["A1"].fill = fill_banner
    ws["A1"].alignment = align_center
    ws.row_dimensions[1].height = 26

    daily_df = df.groupby(date_col, dropna=False).agg(
        donations_count=(amt_col, "count"),
        gross_amount=(amt_col, "sum"),
        fee_amount=(fee_col, "sum"),
        net_amount=(net_col, "sum")
    ).reset_index()

    total_net = float(daily_df["net_amount"].sum())
    total_gross = float(daily_df["gross_amount"].sum())
    total_fee = float(daily_df["fee_amount"].sum())
    total_count = int(daily_df["donations_count"].sum())

    daily_df["fee_ratio"] = (daily_df["fee_amount"] / daily_df["gross_amount"].replace(0, pd.NA)).fillna(0)
    daily_df = daily_df.sort_values(by=date_col, ascending=True)

    header_row = 3
    for col_idx, h in enumerate(col_headers, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_header
        cell.border = border_cell
    ws.row_dimensions[header_row].height = 26

    curr_row = header_row
    for _, row in daily_df.iterrows():
        curr_row += 1
        ws.row_dimensions[curr_row].height = 19
        zebra = (curr_row % 2 == 1)

        d_val = str(row[date_col]).split("T")[0] if pd.notna(row[date_col]) else "Unspecified"
        c1 = ws.cell(row=curr_row, column=1, value=d_val)
        c2 = ws.cell(row=curr_row, column=2, value=int(row["donations_count"]))
        c3 = ws.cell(row=curr_row, column=3, value=float(row["gross_amount"]))
        c4 = ws.cell(row=curr_row, column=4, value=float(row["fee_amount"]))
        c5 = ws.cell(row=curr_row, column=5, value=float(row["fee_ratio"]))
        c6 = ws.cell(row=curr_row, column=6, value=float(row["net_amount"]))

        c1.alignment = align_center
        c2.number_format = FMT_COUNT; c2.alignment = align_right
        c3.number_format = FMT_CURRENCY; c3.alignment = align_right
        c4.number_format = FMT_CURRENCY; c4.alignment = align_right
        c5.number_format = FMT_PCT; c5.alignment = align_right
        c6.number_format = FMT_CURRENCY; c6.alignment = align_right

        for c in [c1, c2, c3, c4, c5, c6]:
            c.font = font_data
            c.border = border_cell
            if zebra:
                c.fill = fill_zebra

    # Total Row
    curr_row += 1
    ws.row_dimensions[curr_row].height = 24
    t1 = ws.cell(row=curr_row, column=1, value="TOTAL PERIOD")
    t2 = ws.cell(row=curr_row, column=2, value=total_count)
    t3 = ws.cell(row=curr_row, column=3, value=total_gross)
    t4 = ws.cell(row=curr_row, column=4, value=total_fee)
    t5 = ws.cell(row=curr_row, column=5, value=(total_fee / total_gross) if total_gross > 0 else 0)
    t6 = ws.cell(row=curr_row, column=6, value=total_net)

    t2.number_format = FMT_COUNT
    t3.number_format = FMT_CURRENCY
    t4.number_format = FMT_CURRENCY
    t5.number_format = FMT_PCT
    t6.number_format = FMT_CURRENCY

    for c in [t1, t2, t3, t4, t5, t6]:
        c.font = font_total
        c.fill = fill_total
        c.border = border_total
        c.alignment = align_left if c == t1 else align_right

    ws.freeze_panes = f"A{header_row + 1}"
    auto_fit_columns(ws, max_col=num_cols)


def build_giftaid_schedule_sheet(ws, df):
    """Generate HMRC-compliant Gift Aid Claim Schedule sheet for tax reclaim."""
    ws.views.sheetView[0].showGridLines = True
    
    giftaid_col = find_column(df, ["is_giftaid", "Gift Aid", "Gift Aid (yes or no)"])
    if giftaid_col:
        giftaid_mask = df[giftaid_col].astype(str).str.strip().isin(["1", "1.0", "true", "True", "yes", "Yes"])
        ga_df = df[giftaid_mask].copy()
    else:
        ga_df = pd.DataFrame()

    col_headers = [
        "Donation Date", "First Name", "Last Name", "Address Line 1", "Address Line 2", "Postcode",
        "Donation Amount (£)", "25% Gift Aid Reclaim (£)", "Campaign Name", "Classification Code", "Payment Gateway"
    ]
    num_cols = len(col_headers)
    end_col_letter = get_column_letter(num_cols)

    ws.merge_cells(f"A1:{end_col_letter}1")
    ws["A1"] = "HMRC GIFT AID RECLAIM SCHEDULE & AUDIT"
    ws["A1"].font = font_banner
    ws["A1"].fill = fill_banner
    ws["A1"].alignment = align_center
    ws.row_dimensions[1].height = 26

    header_row = 3
    for col_idx, h in enumerate(col_headers, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_header
        cell.border = border_cell
    ws.row_dimensions[header_row].height = 26

    amt_col = "amount" if "amount" in df.columns else ("gross_amt" if "gross_amt" in df.columns else "Gross Amount")
    total_gross = 0.0
    total_reclaim = 0.0
    curr_row = header_row

    for _, row in ga_df.iterrows():
        curr_row += 1
        ws.row_dimensions[curr_row].height = 18
        zebra = (curr_row % 2 == 1)

        d_date = str(row.get("Created Date (UTC)") or row.get("created_at", "")).split("T")[0]
        amt = float(row.get(amt_col, 0.0) or 0.0)
        reclaim = round(amt * 0.25, 2)
        total_gross += amt
        total_reclaim += reclaim

        vals = [
            d_date,
            str(row.get("first_name", "") or "") if pd.notna(row.get("first_name")) else "",
            str(row.get("last_name", "") or "") if pd.notna(row.get("last_name")) else "",
            str(row.get("address_line_1", "") or "") if pd.notna(row.get("address_line_1")) else "",
            str(row.get("address_line_2", "") or "") if pd.notna(row.get("address_line_2")) else "",
            str(row.get("postcode", "") or "") if pd.notna(row.get("postcode")) else "",
            amt,
            reclaim,
            str(row.get("Campaign Name", "") or "") if pd.notna(row.get("Campaign Name")) else "",
            str(row.get("Code", "") or "") if pd.notna(row.get("Code")) else "",
            str(row.get("payment method", "") or "") if pd.notna(row.get("payment method")) else "GiveBrite",
        ]

        for col_idx, val in enumerate(vals, start=1):
            cell = ws.cell(row=curr_row, column=col_idx, value=val)
            cell.font = font_data
            cell.border = border_cell
            if zebra:
                cell.fill = fill_zebra
            if col_idx in (7, 8):
                cell.number_format = FMT_CURRENCY
                cell.alignment = align_right
            elif col_idx in (1, 6, 10, 11):
                cell.alignment = align_center
            else:
                cell.alignment = align_left

    # Total Row
    curr_row += 1
    ws.row_dimensions[curr_row].height = 24
    for c_idx in range(1, num_cols + 1):
        cell = ws.cell(row=curr_row, column=c_idx)
        cell.font = font_total
        cell.fill = fill_total
        cell.border = border_total
        if c_idx == 1:
            cell.value = f"TOTAL ({len(ga_df)} ELIGIBLE CLAIMS)"
            cell.alignment = align_left
        elif c_idx == 7:
            cell.value = total_gross
            cell.number_format = FMT_CURRENCY
            cell.alignment = align_right
        elif c_idx == 8:
            cell.value = total_reclaim
            cell.number_format = FMT_CURRENCY
            cell.alignment = align_right
        else:
            cell.value = ""

    ws.freeze_panes = f"A{header_row + 1}"
    auto_fit_columns(ws, max_col=num_cols)


def build_transactions_sheet(ws, df):
    """Write the complete raw itemized transactions sheet with formatting."""
    ws.views.sheetView[0].showGridLines = True
    
    for col_idx, col_name in enumerate(df.columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_header
        cell.border = border_cell
    ws.row_dimensions[1].height = 24

    for row_idx, row in enumerate(df.itertuples(index=False), start=2):
        ws.row_dimensions[row_idx].height = 18
        zebra = (row_idx % 2 == 1)
        
        for col_idx, val in enumerate(row, start=1):
            col_name = df.columns[col_idx - 1]
            cell = ws.cell(row=row_idx, column=col_idx)
            
            if pd.isna(val):
                cell.value = ""
            else:
                cell.value = val

            cell.font = font_data
            cell.border = border_cell
            if zebra:
                cell.fill = fill_zebra

            if col_name in ("amount", "fee_amount", "amount_charity", "gross_amt", "fee_amt", "net_amt", "Gross Amount", "Fees", "Net Amount"):
                if isinstance(val, (int, float)):
                    cell.number_format = FMT_CURRENCY
                    cell.alignment = align_right
            elif col_name in ("charge_id", "ID", "donation_id", "Donation ID", "is_giftaid", "is_zakat", "Code", "Country", "Zakat Eligibility", "Created Date (UTC)"):
                cell.alignment = align_center
            else:
                cell.alignment = align_left

    ws.freeze_panes = "A2"
    auto_fit_columns(ws, max_col=len(df.columns), min_width=10, max_width=35)


def generate_10_sheet_accounting_workbook(df, payout_filename, company_id="iqra"):
    """
    Constructs the professional 10-sheet audit & accounts reconciliation Excel workbook.
    """
    df = df.copy()
    if "amount" not in df.columns:
        df["amount"] = pd.to_numeric(df.get("Total Online Donation Gross Amount in Settled Currency", df.get("Amount", 0.0)), errors="coerce").fillna(0.0)
    if "fee_amount" not in df.columns:
        df["fee_amount"] = pd.to_numeric(df.get("Total Processing Fees Paid by CC In Settled Currency", df.get("fee", df.get("Fees", 0.0))), errors="coerce").fillna(0.0)
    if "amount_charity" not in df.columns:
        df["amount_charity"] = pd.to_numeric(df.get("Total Online Donations Net Amount in Settled Currency", df.get("Net Amount", df.get("net", df["amount"] - df["fee_amount"]))), errors="coerce").fillna(0.0)

    for col, default_val in [
        ("Campaign Name", "General Campaign"),
        ("Heading", "General"),
        ("Subheading", "General"),
        ("Code", "ALL-GEN-GEN-GEN"),
        ("Country", "Global / Unspecified"),
        ("Zakat Eligibility", "Non-Zakat"),
        ("Programme Fund", "General Fund"),
        ("Portfolio", "General"),
        ("payment method", "GiveBrite"),
        ("Donation Type", "One-off"),
        ("Created Date (UTC)", datetime.date.today().isoformat()),
    ]:
        if col not in df.columns:
            df[col] = default_val
        else:
            df[col] = df[col].fillna(default_val)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    company_title = "IQRA CHARITY" if str(company_id).lower() == "iqra" else "RETHINK CHARITY"

    # Sheet 1: Executive Summary Dashboard
    ws_exec = wb.create_sheet(title="Executive Summary")
    build_executive_summary_sheet(ws_exec, df, payout_filename, company_title=company_title)

    # Sheet 2: Campaign Breakdown
    ws_camp = wb.create_sheet(title="Campaign Breakdown")
    camp_headers = [
        "Campaign Name", "Classification Code", "Heading", "Sub-Heading", "Country", "Zakat Eligibility",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_camp, "Campaign Performance & Fund Allocation Breakdown", ["Campaign Name", "Code", "Heading", "Subheading", "Country", "Zakat Eligibility"], df, camp_headers)

    # Sheet 3: Code Breakdown
    ws_code = wb.create_sheet(title="Code Breakdown")
    code_headers = [
        "Classification Code", "Heading", "Sub-Heading", "Country", "Zakat Eligibility",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_code, "Fund Code Allocation & Classification Breakdown", ["Code", "Heading", "Subheading", "Country", "Zakat Eligibility"], df, code_headers)

    # Sheet 4: Department Breakdown
    ws_dept = wb.create_sheet(title="Department Breakdown")
    dept_headers = [
        "Department / Heading", "Programme Fund",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_dept, "Department & Programme Fund Allocation Breakdown", ["Heading", "Programme Fund"], df, dept_headers)

    # Sheet 5: Country Breakdown
    ws_country = wb.create_sheet(title="Country Breakdown")
    country_headers = [
        "Country", "Department / Heading", "Zakat Eligibility",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_country, "Country & Geographical Fund Allocation Breakdown", ["Country", "Heading", "Zakat Eligibility"], df, country_headers)

    # Sheet 6: Payment Method Breakdown
    ws_pay = wb.create_sheet(title="Payment Method Breakdown")
    pay_headers = [
        "Payment Gateway", "Donation Type",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_pay, "Payment Gateway & Donation Type Reconciliation", ["payment method", "Donation Type"], df, pay_headers)

    # Sheet 7: Zakat Reconciliation
    ws_zakat = wb.create_sheet(title="Zakat Reconciliation")
    zakat_headers = [
        "Zakat Eligibility",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_zakat, "Zakat vs Non-Zakat Audit Reconciliation", ["Zakat Eligibility"], df, zakat_headers)

    # Sheet 8: Gift Aid Schedule
    ws_ga = wb.create_sheet(title="Gift Aid Schedule")
    build_giftaid_schedule_sheet(ws_ga, df)

    # Sheet 9: Daily Settlement Breakdown
    ws_daily = wb.create_sheet(title="Daily Settlement")
    build_daily_breakdown_sheet(ws_daily, df)

    # Sheet 10: Transactions Audit (Raw Enriched Ledger)
    ws_trans = wb.create_sheet(title="Transactions Audit")
    build_transactions_sheet(ws_trans, df)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ==============================================================================
# Main Orchestration Pipelines
# ==============================================================================

def enrich_rethink_givebrite_payout(df_raw: pd.DataFrame, company_id: str = "rethink"):
    """
    Implements the exact logic of `enrich_transfers_from_main_donors.py` / `fill_donor_data.bat`
    for Rethink's GiveBrite payout transfers, matched against live CRM donations.
    """
    cid = str(company_id or "rethink").strip().lower()
    ref = load_donor_reference(cid)
    by_cid = ref["by_cid"]

    df = df_raw.copy()
    if len(df) == 0:
        return df, 0, 0, 0.0

    id_col = find_column(df, ["ID", "charge_id", "Charge ID", "Charge Id", "charge id", "Transaction ID", "id"])
    if not id_col:
        raise ValueError(f"Could not identify a charge_id / transaction ID column in uploaded transfer file. Columns: {list(df.columns)}")

    target_cols = [
        "Country", "Donation Type", "payment method", "Heading",
        "Subheading", "Code", "Zakat Eligibility", "Created Date (UTC)", "donation_type"
    ]

    clean_ids = df[id_col].astype(str).str.strip()
    matched_count = 0

    enriched_cols = {col: [] for col in target_cols}

    for idx, c_id in enumerate(clean_ids):
        match = by_cid.get(c_id) or by_cid.get(c_id.lower())
        if match:
            matched_count += 1
            for col in target_cols:
                enriched_cols[col].append(match.get(col))
        else:
            for col in target_cols:
                if col == "payment method":
                    enriched_cols[col].append("GiveBrite")
                elif col in ("Heading", "Subheading"):
                    enriched_cols[col].append("General")
                elif col == "Code":
                    enriched_cols[col].append("ALL-GEN-GEN-GEN")
                elif col == "Country":
                    enriched_cols[col].append("Global / Unspecified")
                elif col == "Zakat Eligibility":
                    enriched_cols[col].append("Non-Zakat")
                else:
                    enriched_cols[col].append(None)

    for col in target_cols:
        df[col] = enriched_cols[col]

    # Created Date fallback
    created_col = find_column(df, ["Created", "created_at", "Date", "Created Date"])
    if created_col:
        created_fallback = df[created_col].astype(str).str.split(" ").str[0].str.split("T").str[0]
        df["Created Date (UTC)"] = df["Created Date (UTC)"].fillna(created_fallback)

    match_pct = (matched_count / len(df) * 100) if len(df) > 0 else 0.0
    logger.info(f"Rethink GiveBrite Payout: Matched & Filled {matched_count} / {len(df)} rows ({match_pct:.1f}%).")
    return df, matched_count, len(df), match_pct


def enrich_iqra_givebrite_payout(df_raw: pd.DataFrame, company_id: str = "iqra"):
    """
    Implements the exact logic of `enrich_iqra_payouts.py` for Iqra's GiveBrite payouts,
    executing 4-tier fallback matching against live CRM Iqra donations.
    """
    cid = str(company_id or "iqra").strip().lower()
    ref = load_donor_reference(cid)
    by_cid = ref["by_cid"]
    by_name_net = ref["by_name_net"]
    by_name_gross = ref["by_name_gross"]
    by_name = ref["by_name"]

    df = df_raw.copy()
    if len(df) == 0:
        return df, 0, 0, 0.0

    # Ensure transaction rows
    essential_cols = [c for c in df.columns if c in ["charge_id", "ID", "first_name", "First Name", "amount", "Amount", "amount_charity"]]
    if essential_cols:
        df = df.dropna(subset=essential_cols, how="all").copy()

    id_col = find_column(df, ["charge_id", "Charge ID", "ID", "Transaction ID", "id"])
    fn_col = find_column(df, ["first_name", "First Name", "Donor First Name", "FirstName"])
    ln_col = find_column(df, ["last_name", "Last Name", "Donor Last Name", "LastName", "Surname"])
    net_col = find_column(df, ["amount_charity", "Net Amount", "Net", "Total Online Donations Net Amount in Settled Currency"])
    gross_col = find_column(df, ["amount", "Amount", "Total LTV", "Donation Amount", "Gross"])
    gateway_col = find_column(df, ["gateway", "Payment Method", "Payment Type", "payment_method_type"])
    created_col = find_column(df, ["created_at", "Created", "Created Date (UTC)", "Date", "Created At"])

    target_cols = [
        "Country", "Donation Type", "payment method", "Heading",
        "Subheading", "Code", "Zakat Eligibility", "Created Date (UTC)",
        "donation_type", "Campaign Name", "Programme Fund", "Portfolio"
    ]

    matched_count = 0
    enriched_data = {col: [] for col in target_cols}

    for idx, row in df.iterrows():
        cid_val = str(row[id_col]).strip() if id_col and pd.notna(row[id_col]) else None
        fn = row[fn_col] if fn_col else None
        ln = row[ln_col] if ln_col else None
        full = get_full_name(fn, ln)

        net_val = None
        if net_col and pd.notna(row.get(net_col)):
            try:
                net_val = round(float(str(row.get(net_col)).replace("£", "").replace(",", "").strip()), 2)
            except Exception:
                pass

        gross_val = None
        if gross_col and pd.notna(row.get(gross_col)):
            try:
                gross_val = round(float(str(row.get(gross_col)).replace("£", "").replace(",", "").strip()), 2)
            except Exception:
                pass

        # 4-Tier Matching Fallback
        match = None
        if cid_val and (cid_val in by_cid or cid_val.lower() in by_cid):
            match = by_cid.get(cid_val) or by_cid.get(cid_val.lower())
        elif full and net_val is not None and (full, net_val) in by_name_net:
            match = by_name_net[(full, net_val)]
        elif full and gross_val is not None and (full, gross_val) in by_name_gross:
            match = by_name_gross[(full, gross_val)]
        elif full and full in by_name:
            match = by_name[full]

        if match:
            matched_count += 1
            for c in target_cols:
                if c == "payment method":
                    pm = row.get(gateway_col) if gateway_col and pd.notna(row.get(gateway_col)) else "GiveBrite"
                    enriched_data[c].append(str(pm))
                elif c == "Created Date (UTC)":
                    c_date = row.get(created_col) if created_col and pd.notna(row.get(created_col)) else None
                    c_date_str = str(c_date).split(" ")[0].split("T")[0] if pd.notna(c_date) else match.get("Created Date (UTC)")
                    enriched_data[c].append(c_date_str)
                elif c in ("Donation Type", "donation_type"):
                    freq = match.get(c) or (row.get("frequency") if "frequency" in df.columns else "One-off")
                    enriched_data[c].append(str(freq))
                else:
                    enriched_data[c].append(match.get(c))
        else:
            for c in target_cols:
                if c == "payment method":
                    pm = row.get(gateway_col) if gateway_col and pd.notna(row.get(gateway_col)) else "GiveBrite"
                    enriched_data[c].append(str(pm))
                elif c == "Created Date (UTC)":
                    c_date = row.get(created_col) if created_col and pd.notna(row.get(created_col)) else None
                    c_date_str = str(c_date).split(" ")[0].split("T")[0] if pd.notna(c_date) else None
                    enriched_data[c].append(c_date_str)
                elif c in ("Donation Type", "donation_type"):
                    freq = row.get("frequency") if "frequency" in df.columns else "One-off"
                    enriched_data[c].append(str(freq))
                elif c in ("Heading", "Subheading"):
                    enriched_data[c].append("General")
                elif c == "Code":
                    enriched_data[c].append("ALL-GEN-GEN-GEN")
                elif c == "Country":
                    enriched_data[c].append("Global / Unspecified")
                elif c == "Zakat Eligibility":
                    enriched_data[c].append("Non-Zakat")
                elif c == "Campaign Name":
                    c_name = row.get("campaign_name") if "campaign_name" in df.columns else "GiveBrite General"
                    enriched_data[c].append(str(c_name))
                elif c == "Programme Fund":
                    enriched_data[c].append("General Fund")
                elif c == "Portfolio":
                    enriched_data[c].append("General")
                else:
                    enriched_data[c].append(None)

    for col_name in target_cols:
        df[col_name] = enriched_data[col_name]

    match_pct = (matched_count / len(df) * 100) if len(df) > 0 else 0.0
    logger.info(f"Iqra GiveBrite Payout: 4-Tier Matched & Filled {matched_count} / {len(df)} rows ({match_pct:.1f}%).")
    return df, matched_count, len(df), match_pct


def process_payout_upload_pipeline(file_buffer, filename: str, company_id: str, upload_mode: str = "merge"):
    """
    Main orchestration endpoint handler:
    1. Reads uploaded CSV or XLSX file.
    2. Runs appropriate enrichment pipeline based on company_id (Rethink vs Iqra).
    3. Generates 10-Sheet Executive Accounting Pack (.xlsx) and persists to disk.
    4. Ingests enriched payout transactions into `payout_settlements` table.
    5. Marks matching donations in `donations` table as `Payout Settled = 'Yes'`.
    6. Invalidates caches and triggers frontend notification events.
    """
    cid = str(company_id or "rethink").strip().lower()
    
    # 1. Parse File
    if hasattr(file_buffer, "seek"):
        file_buffer.seek(0)
    
    is_excel = filename.lower().endswith((".xlsx", ".xls"))
    if is_excel:
        xl = pd.ExcelFile(file_buffer)
        sheet_to_read = "Transactions Audit" if "Transactions Audit" in xl.sheet_names else xl.sheet_names[0]
        df_raw = xl.parse(sheet_to_read)
    else:
        df_raw = pd.read_csv(file_buffer)

    if df_raw.empty:
        raise ValueError(f"Uploaded file '{filename}' contains 0 records.")

    # 2. Enrich based on Company Partition
    if cid == "iqra":
        df_enriched, matched_count, total_count, match_pct = enrich_iqra_givebrite_payout(df_raw, company_id=cid)
    else:
        df_enriched, matched_count, total_count, match_pct = enrich_rethink_givebrite_payout(df_raw, company_id=cid)

    # 3. Standardize Schema for payout_settlements
    df_settlements = df_enriched.copy()
    df_settlements["company_id"] = cid
    df_settlements["Platform"] = "GiveBrite Payout"

    # Map amount fields
    amt_col = find_column(df_settlements, ["amount", "Gross Amount", "amount_charity", "Total Online Donation Gross Amount in Settled Currency", "Amount"])
    fee_col = find_column(df_settlements, ["fee_amount", "Fees", "fee", "Total Processing Fees Paid by CC In Settled Currency"])
    net_col = find_column(df_settlements, ["amount_charity", "Net Amount", "net", "Total Online Donations Net Amount in Settled Currency"])

    if amt_col:
        df_settlements["Total Online Donation Gross Amount in Settled Currency"] = pd.to_numeric(df_settlements[amt_col], errors="coerce").fillna(0.0)
    if fee_col:
        df_settlements["Total Processing Fees Paid by CC In Settled Currency"] = pd.to_numeric(df_settlements[fee_col], errors="coerce").fillna(0.0)
    if net_col:
        df_settlements["Total Online Donations Net Amount in Settled Currency"] = pd.to_numeric(df_settlements[net_col], errors="coerce").fillna(0.0)
    else:
        df_settlements["Total Online Donations Net Amount in Settled Currency"] = (
            df_settlements.get("Total Online Donation Gross Amount in Settled Currency", 0.0) -
            df_settlements.get("Total Processing Fees Paid by CC In Settled Currency", 0.0)
        )

    # Transfer ID & Batch attribution
    batch_base = os.path.splitext(os.path.basename(filename))[0]
    tid_col = find_column(df_settlements, ["Transfer ID", "transfer_id", "payout_id", "Payout ID", "Batch ID"])
    if tid_col:
        df_settlements["Transfer ID"] = df_settlements[tid_col].fillna(batch_base).astype(str)
    else:
        df_settlements["Transfer ID"] = batch_base

    df_settlements["Batch Label"] = batch_base
    df_settlements["Type"] = "donation"
    df_settlements["Status"] = "Paid"

    # Donation ID mapping
    id_col = find_column(df_settlements, ["charge_id", "ID", "Donation ID", "Transaction ID", "id"])
    if id_col:
        df_settlements["Donation ID"] = df_settlements[id_col].astype(str)

    # 4. Generate 10-Sheet Executive Accounting Pack
    batch_report_id = f"{cid}_givebrite_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    report_filename = f"{batch_report_id}.xlsx"
    company_reports_dir = os.path.join(REPORTS_DIR, cid)
    os.makedirs(company_reports_dir, exist_ok=True)
    report_file_path = os.path.join(company_reports_dir, report_filename)

    workbook_bytes = generate_10_sheet_accounting_workbook(df_settlements, filename, company_id=cid)
    with open(report_file_path, "wb") as f:
        f.write(workbook_bytes)

    # 5. Persist to payout_settlements Table & Parquet Cache
    try:
        from core.data_processor import atomic_write_parquet, sanitize_df_dtypes_for_parquet, load_payouts_data, load_data

        existing_payouts = None
        if os.path.exists(PAYOUTS_PARQUET_PATH):
            try:
                existing_payouts = pd.read_parquet(PAYOUTS_PARQUET_PATH)
            except Exception:
                pass

        if upload_mode in ["merge", "append"] and existing_payouts is not None and not existing_payouts.empty:
            df_combined = pd.concat([existing_payouts, df_settlements], ignore_index=True)
            if "Donation ID" in df_combined.columns:
                valid_mask = df_combined["Donation ID"].notna() & (~df_combined["Donation ID"].astype(str).str.strip().str.lower().isin(["", "nan", "none", "n/a", "<na>"]))
                df_valid = df_combined[valid_mask].drop_duplicates(subset=["Donation ID"], keep="last")
                df_invalid = df_combined[~valid_mask]
                df_save = pd.concat([df_valid, df_invalid], ignore_index=True)
            else:
                df_save = df_combined
        else:
            df_save = df_settlements

        df_save = sanitize_df_dtypes_for_parquet(df_save)
        atomic_write_parquet(df_save, PAYOUTS_PARQUET_PATH)

        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=60.0)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(payout_settlements)")
        existing_db_cols = {r[1] for r in cur.fetchall()}

        # Harmonize standard aliases
        if "Sub-Heading" in existing_db_cols and "Subheading" in df_settlements.columns and "Sub-Heading" not in df_settlements.columns:
            df_settlements["Sub-Heading"] = df_settlements["Subheading"]
        if "DonationType" in existing_db_cols and "Donation Type" in df_settlements.columns and "DonationType" not in df_settlements.columns:
            df_settlements["DonationType"] = df_settlements["Donation Type"]

        for col in df_settlements.columns:
            if col not in existing_db_cols:
                try:
                    cur.execute(f'ALTER TABLE payout_settlements ADD COLUMN "{col}" TEXT')
                    conn.commit()
                    existing_db_cols.add(col)
                except Exception:
                    pass

        cols_to_insert = [c for c in df_settlements.columns if c in existing_db_cols]
        df_settlements[cols_to_insert].to_sql("payout_settlements", con=conn, if_exists="append", index=False, chunksize=2000)
        conn.close()

    except Exception as ex:
        logger.warning(f"Error persisting payout settlements to cache/DB: {ex}")

    # 6. Mark Matching Donations in Raw donations Table as Payout Settled = 'Yes'
    try:
        settled_ids = [str(x).strip() for x in df_settlements["Donation ID"].dropna().unique() if str(x).strip()]
        if settled_ids:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
            cur = conn.cursor()
            cur.executemany(
                "UPDATE donations SET \"Payout Settled\" = 'Yes' WHERE LOWER(TRIM(\"Donation ID\")) = LOWER(TRIM(?)) OR LOWER(TRIM(charge_id)) = LOWER(TRIM(?))",
                [(sid, sid) for sid in settled_ids]
            )
            conn.commit()
            conn.close()

            # Parquet update
            if os.path.exists(PARQUET_PATH):
                don_df = pd.read_parquet(PARQUET_PATH)
                if not don_df.empty:
                    s_set = set(s.lower() for s in settled_ids)
                    m_id = don_df["Donation ID"].astype(str).str.lower().str.strip().isin(s_set) if "Donation ID" in don_df.columns else pd.Series(False, index=don_df.index)
                    m_ch = don_df["charge_id"].astype(str).str.lower().str.strip().isin(s_set) if "charge_id" in don_df.columns else pd.Series(False, index=don_df.index)
                    mask_matched = m_id | m_ch
                    if mask_matched.any():
                        don_df.loc[mask_matched, "Payout Settled"] = "Yes"
                        don_df = sanitize_df_dtypes_for_parquet(don_df)
                        atomic_write_parquet(don_df, PARQUET_PATH)
    except Exception as ex:
        logger.warning(f"Notice updating Payout Settled flag: {ex}")

    # Invalidate Caches
    try:
        from backend.api.payouts import invalidate_payouts_cache
        invalidate_payouts_cache()
    except Exception:
        pass

    try:
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("PAYOUTS_UPDATED", {"source": "upload", "company_id": cid, "batch": batch_base})
        broadcast_event_sync("DONORS_UPDATED", {"source": "payout_upload", "company_id": cid})
    except Exception:
        pass

    net_sum = float(df_settlements["Total Online Donations Net Amount in Settled Currency"].sum())
    gross_sum = float(df_settlements["Total Online Donation Gross Amount in Settled Currency"].sum())
    fee_sum = float(df_settlements["Total Processing Fees Paid by CC In Settled Currency"].sum())

    return {
        "status": "success",
        "company_id": cid,
        "platform": "GiveBrite Payout",
        "filename": filename,
        "batch_id": batch_base,
        "report_id": batch_report_id,
        "report_download_url": f"/api/payouts/reports/{cid}/{report_filename}",
        "total_rows": total_count,
        "matched_rows": matched_count,
        "match_percentage": round(match_pct, 2),
        "total_gross": round(gross_sum, 2),
        "total_fees": round(fee_sum, 2),
        "net_payout": round(net_sum, 2),
        "message": (
            f"Successfully processed and enriched {filename} for {cid.upper()}! "
            f"{matched_count:,} of {total_count:,} transactions ({match_pct:.1f}%) were matched and enriched with live project codes and departments. "
            f"10-Sheet Executive Accounting Pack has been generated."
        )
    }
