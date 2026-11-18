import os
import sys
import glob
import re
import shutil
import argparse
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


def clean_name(s):
    """Normalize names: remove emojis, special characters, extra spaces, and lowercase."""
    if pd.isna(s):
        return ''
    s_str = str(s).strip()
    if s_str.lower() in ('nan', 'none', 'null'):
        return ''
    s_str = re.sub(r'[^\w\s]', ' ', s_str)
    return ' '.join(s_str.lower().split())


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
        return str(s).lower().replace(' ', '').replace('_', '').replace('-', '')
        
    normalized_candidates = [normalize(c) for c in candidate_names]
    for col in df_cols:
        if normalize(col) in normalized_candidates:
            return col
            
    return None


def find_latest_iqra_donors_file(work_dir='.'):
    """Find the most recent Iqra donor file in work_dir."""
    patterns = [
        "filtered_donors*.xlsx",
        "filtered_donors*.xls",
        "filtered_donors*.csv",
        "iqra_donors*.xlsx",
        "iqra_donors*.csv",
        "Iqra_donors*.xlsx",
        "Main_donors_iqra*.xlsx"
    ]
    candidates = []
    for pat in patterns:
        for f in glob.glob(os.path.join(work_dir, pat)):
            fname = os.path.basename(f)
            if fname.startswith('~$') or f.endswith('.bak') or f.endswith('.py') or f.endswith('.bat'):
                continue
            candidates.append(f)

    if not candidates:
        return None

    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def load_iqra_donors(donor_file_path):
    """Load reference metadata from Iqra donor reference file."""
    print(f"Loading Iqra reference donors from: {donor_file_path}")
    if donor_file_path.lower().endswith(('.xlsx', '.xls')):
        df_donors = pd.read_excel(donor_file_path)
    else:
        df_donors = pd.read_csv(donor_file_path)
        
    print(f"Total rows in Iqra Donors reference: {len(df_donors)}")

    fn_col = find_column(df_donors, ['First Name', 'first_name', 'Donor First Name', 'FirstName'])
    ln_col = find_column(df_donors, ['Last Name', 'last_name', 'Donor Last Name', 'LastName', 'Surname'])
    dept_col = find_column(df_donors, ['Department', 'department', 'Heading', 'heading'])
    office_col = find_column(df_donors, ['Office', 'office', 'Subheading', 'subheading', 'Sub-Heading'])
    code_col = find_column(df_donors, ['Code', 'code', 'Fund Code', 'New Code', 'Cause/Code'])
    country_col = find_column(df_donors, ['Country', 'country', 'Target Country', 'Billing Country'])
    zakat_col = find_column(df_donors, ['Zakat Eligibility', 'is_zakat', 'Zakat Status', 'Zakat (yes or no)'])
    campaign_col = find_column(df_donors, ['Campaign Name', 'campaign_name', 'Campaign'])
    prog_col = find_column(df_donors, ['Programme Fund', 'programme_fund', 'Program Fund'])
    port_col = find_column(df_donors, ['Portfolio', 'portfolio'])
    freq_col = find_column(df_donors, ['Payment Frequency', 'frequency', 'Donation Type', 'Payment Type'])
    
    net_col = find_column(df_donors, [
        'Total Online Donations Net Amount in Settled Currency',
        'Net Amount', 'amount_charity', 'Net'
    ])
    gross_col = find_column(df_donors, [
        'Total LTV', 'Donation Amount (in Donation Currency)', 'Donation Amount', 'amount', 'Gross'
    ])
    charge_id_col = find_column(df_donors, ['charge_id', 'Charge ID', 'ID', 'Transaction ID'])

    by_cid = {}
    by_name_net = {}
    by_name_gross = {}
    by_name = {}

    for idx, row in df_donors.iterrows():
        raw_fn = row.get(fn_col) if fn_col else None
        raw_ln = row.get(ln_col) if ln_col else None
        full = get_full_name(raw_fn, raw_ln)

        val_heading = row.get(dept_col) if dept_col else None
        if pd.isna(val_heading) or not str(val_heading).strip():
            val_heading = row.get(campaign_col) if campaign_col else None

        val_subheading = row.get(office_col) if office_col else None
        val_code = row.get(code_col) if code_col else None
        val_country = row.get(country_col) if country_col else None
        val_zakat = row.get(zakat_col) if zakat_col else None
        val_campaign = row.get(campaign_col) if campaign_col else None
        val_prog = row.get(prog_col) if prog_col else None
        val_port = row.get(port_col) if port_col else None
        val_freq = row.get(freq_col) if freq_col else None

        record = {
            'Heading': str(val_heading).strip() if pd.notna(val_heading) else None,
            'Subheading': str(val_subheading).strip() if pd.notna(val_subheading) else None,
            'Code': str(val_code).strip() if pd.notna(val_code) else None,
            'Country': str(val_country).strip() if pd.notna(val_country) else None,
            'Zakat Eligibility': str(val_zakat).strip() if pd.notna(val_zakat) else None,
            'Campaign Name': str(val_campaign).strip() if pd.notna(val_campaign) else None,
            'Programme Fund': str(val_prog).strip() if pd.notna(val_prog) else None,
            'Portfolio': str(val_port).strip() if pd.notna(val_port) else None,
            'Donation Type': str(val_freq).strip() if pd.notna(val_freq) else None,
            'donation_type': str(val_freq).strip() if pd.notna(val_freq) else None,
        }

        if charge_id_col and pd.notna(row.get(charge_id_col)):
            cid = str(row.get(charge_id_col)).strip()
            if cid and cid.lower() != 'nan' and cid not in by_cid:
                by_cid[cid] = record

        if full:
            net_val = None
            if net_col and pd.notna(row.get(net_col)):
                try:
                    net_val = round(float(row.get(net_col)), 2)
                except Exception:
                    pass

            gross_val = None
            if gross_col and pd.notna(row.get(gross_col)):
                try:
                    gross_val = round(float(row.get(gross_col)), 2)
                except Exception:
                    pass

            if net_val is not None and (full, net_val) not in by_name_net:
                by_name_net[(full, net_val)] = record

            if gross_val is not None and (full, gross_val) not in by_name_gross:
                by_name_gross[(full, gross_val)] = record

            if full not in by_name:
                by_name[full] = record

    print(f"Indexed: {len(by_cid)} charge IDs, {len(by_name_net)} (name + net) pairs, {len(by_name)} unique donor names.")
    return {
        'by_cid': by_cid,
        'by_name_net': by_name_net,
        'by_name_gross': by_name_gross,
        'by_name': by_name
    }


# ==============================================================================
# OpenPyXL Styles & Helpers for Accounts Presentation
# ==============================================================================

NAVY_DARK = '0F2C59'
NAVY_HEADER = '1B365D'
SLATE_HEADER = '2B4C7E'
ROW_ZEBRA = 'F9FAFC'
TOTAL_FILL = 'E8EEF5'
BORDER_GRAY = 'D0D7DE'

font_banner = Font(name='Calibri', size=14, bold=True, color='FFFFFF')
font_subtitle = Font(name='Calibri', size=10, italic=True, color='E0E0E0')
font_section = Font(name='Calibri', size=11, bold=True, color='1B365D')
font_header = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
font_data = Font(name='Calibri', size=10)
font_total = Font(name='Calibri', size=10, bold=True, color='0F2C59')

fill_banner = PatternFill(start_color=NAVY_DARK, end_color=NAVY_DARK, fill_type='solid')
fill_header = PatternFill(start_color=NAVY_HEADER, end_color=NAVY_HEADER, fill_type='solid')
fill_header_slate = PatternFill(start_color=SLATE_HEADER, end_color=SLATE_HEADER, fill_type='solid')
fill_zebra = PatternFill(start_color=ROW_ZEBRA, end_color=ROW_ZEBRA, fill_type='solid')
fill_total = PatternFill(start_color=TOTAL_FILL, end_color=TOTAL_FILL, fill_type='solid')

thin_side = Side(style='thin', color=BORDER_GRAY)
border_cell = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
border_total = Border(
    left=thin_side,
    right=thin_side,
    top=Side(style='thin', color=NAVY_HEADER),
    bottom=Side(style='double', color=NAVY_HEADER)
)

align_left = Alignment(horizontal='left', vertical='center')
align_right = Alignment(horizontal='right', vertical='center')
align_center = Alignment(horizontal='center', vertical='center')
align_header = Alignment(horizontal='center', vertical='center', wrap_text=True)

FMT_CURRENCY = '£#,##0.00'
FMT_COUNT = '#,##0'
FMT_PCT = '0.00%'


def auto_fit_columns(ws, min_col=1, max_col=None, padding=3, min_width=11, max_width=50):
    """Auto-adjust worksheet column widths so content is never cut off."""
    if max_col is None:
        max_col = ws.max_column
    for col_idx in range(min_col, max_col + 1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for cell in ws[col_letter]:
            if cell.row == 1 and ws.cell(row=1, column=1).value and ws.cell(row=1, column=1).font.size > 12:
                continue  # Skip title banner in width calculation
            val = cell.value
            if val is not None:
                val_str = str(val)
                # Avoid long decimals inflating widths
                if isinstance(val, float):
                    val_str = f"£{val:,.2f}"
                max_len = max(max_len, len(val_str))
        ws.column_dimensions[col_letter].width = max(min_width, min(max_width, max_len + padding))


# ==============================================================================
# Multi-Sheet Accounting Report Generator
# ==============================================================================

def build_executive_summary_sheet(ws, df, payout_filename):
    """Generate the Executive Summary dashboard sheet for accounts."""
    ws.views.sheetView[0].showGridLines = True
    
    # Title Banner
    ws.merge_cells('A1:F1')
    ws['A1'] = "IQRA CHARITY — PAYOUT RECONCILIATION & ACCOUNTS AUDIT REPORT"
    ws['A1'].font = font_banner
    ws['A1'].fill = fill_banner
    ws['A1'].alignment = align_center
    ws.row_dimensions[1].height = 28

    earliest_date = str(df['Created Date (UTC)'].dropna().min()) if 'Created Date (UTC)' in df.columns else 'N/A'
    latest_date = str(df['Created Date (UTC)'].dropna().max()) if 'Created Date (UTC)' in df.columns else 'N/A'
    currency = str(df['currency'].dropna().iloc[0]) if 'currency' in df.columns and len(df['currency'].dropna()) > 0 else 'GBP'

    ws.merge_cells('A2:F2')
    ws['A2'] = f"Source File: {payout_filename}  |  Period: {earliest_date} to {latest_date}  |  Currency: {currency}"
    ws['A2'].font = font_subtitle
    ws['A2'].fill = fill_banner
    ws['A2'].alignment = align_center
    ws.row_dimensions[2].height = 18

    # Metric calculations
    total_tx = len(df)
    gross_total = float(df['amount'].sum()) if 'amount' in df.columns else 0.0
    fee_total = float(df['fee_amount'].sum()) if 'fee_amount' in df.columns else 0.0
    net_total = float(df['amount_charity'].sum()) if 'amount_charity' in df.columns else 0.0
    fee_ratio = (fee_total / gross_total) if gross_total > 0 else 0.0
    avg_donation = (gross_total / total_tx) if total_tx > 0 else 0.0

    zakat_mask = df['Zakat Eligibility'].astype(str).str.lower() == 'zakat'
    zakat_net = float(df[zakat_mask]['amount_charity'].sum())
    zakat_count = int(zakat_mask.sum())
    zakat_share = (zakat_net / net_total) if net_total > 0 else 0.0

    non_zakat_net = net_total - zakat_net
    non_zakat_count = total_tx - zakat_count
    non_zakat_share = (non_zakat_net / net_total) if net_total > 0 else 0.0

    giftaid_mask = df.get('is_giftaid', pd.Series([0]*total_tx)).fillna(0).astype(float) == 1.0
    giftaid_count = int(giftaid_mask.sum())
    giftaid_gross = float(df[giftaid_mask]['amount'].sum()) if 'amount' in df.columns else 0.0
    giftaid_claimable = round(giftaid_gross * 0.25, 2)

    # Section 1: Key Financial Reconciliation
    ws.cell(row=4, column=1, value="1. Financial Reconciliation Summary").font = font_section
    headers_sec1 = ["Metric Description", "Value", "Notes / Percentage"]
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
        ("Net Settlement / Payout to Charity", net_total, FMT_CURRENCY, f"100.00% of disbursed payout"),
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
            c1.fill = fill_total
            c2.fill = fill_total
            c3.fill = fill_total
        elif r_idx % 2 == 1:
            c1.fill = fill_zebra
            c2.fill = fill_zebra
            c3.fill = fill_zebra
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
    """Generic builder for Code, Campaign, Department, and Zakat breakdown sheets."""
    ws.views.sheetView[0].showGridLines = True
    
    # Header Banner
    num_cols = len(col_headers)
    end_col_letter = get_column_letter(num_cols)
    ws.merge_cells(f'A1:{end_col_letter}1')
    ws['A1'] = title.upper()
    ws['A1'].font = font_banner
    ws['A1'].fill = fill_banner
    ws['A1'].alignment = align_center
    ws.row_dimensions[1].height = 26

    # Aggregations
    agg_df = df.groupby(group_cols, dropna=False).agg(
        donations_count=('amount', 'count'),
        gross_amount=('amount', 'sum'),
        fee_amount=('fee_amount', 'sum'),
        net_amount=('amount_charity', 'sum')
    ).reset_index()

    total_net = float(agg_df['net_amount'].sum())
    total_gross = float(agg_df['gross_amount'].sum())
    total_fee = float(agg_df['fee_amount'].sum())
    total_count = int(agg_df['donations_count'].sum())

    agg_df['fee_ratio'] = (agg_df['fee_amount'] / agg_df['gross_amount'].replace(0, pd.NA)).fillna(0)
    agg_df['share_pct'] = (agg_df['net_amount'] / total_net) if total_net > 0 else 0
    agg_df = agg_df.sort_values(by='net_amount', ascending=False)

    # Column Headers
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

        # Write grouping values
        for g_idx, g_col in enumerate(group_cols, start=1):
            val = row[g_col]
            cell = ws.cell(row=curr_row, column=g_idx, value=str(val) if pd.notna(val) else 'Unspecified')
            cell.font = font_data
            cell.alignment = align_center if g_col in ('Code', 'Country', 'Zakat Eligibility') else align_left
            cell.border = border_cell
            if zebra:
                cell.fill = fill_zebra

        # Metrics: Count, Gross, Fees, Fee Ratio, Net, Share %
        base_col = len(group_cols) + 1
        c_count = ws.cell(row=curr_row, column=base_col, value=int(row['donations_count']))
        c_gross = ws.cell(row=curr_row, column=base_col + 1, value=float(row['gross_amount']))
        c_fee = ws.cell(row=curr_row, column=base_col + 2, value=float(row['fee_amount']))
        c_ratio = ws.cell(row=curr_row, column=base_col + 3, value=float(row['fee_ratio']))
        c_net = ws.cell(row=curr_row, column=base_col + 4, value=float(row['net_amount']))
        c_share = ws.cell(row=curr_row, column=base_col + 5, value=float(row['share_pct']))

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
                c.fill = fill_zebra

    # Total Row
    curr_row += 1
    ws.row_dimensions[curr_row].height = 24
    
    t_label = ws.cell(row=curr_row, column=1, value="TOTAL ALLOCATIONS")
    t_label.font = font_total
    t_label.fill = fill_total
    t_label.border = border_total
    t_label.alignment = align_left

    # Blank fill for intermediate group columns
    for g_idx in range(2, len(group_cols) + 1):
        cell = ws.cell(row=curr_row, column=g_idx, value="")
        cell.font = font_total
        cell.fill = fill_total
        cell.border = border_total

    base_col = len(group_cols) + 1
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

    ws.freeze_panes = f'A{header_row + 1}'
    auto_fit_columns(ws, max_col=num_cols)


def build_daily_breakdown_sheet(ws, df):
    """Generate daily timeline breakdown of donations."""
    ws.views.sheetView[0].showGridLines = True
    
    date_col = 'Created Date (UTC)' if 'Created Date (UTC)' in df.columns else 'created_at'
    col_headers = ["Date (UTC)", "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)"]
    num_cols = len(col_headers)
    end_col_letter = get_column_letter(num_cols)

    ws.merge_cells(f'A1:{end_col_letter}1')
    ws['A1'] = "DAILY SETTLEMENT & RECONCILIATION BREAKDOWN"
    ws['A1'].font = font_banner
    ws['A1'].fill = fill_banner
    ws['A1'].alignment = align_center
    ws.row_dimensions[1].height = 26

    daily_df = df.groupby(date_col, dropna=False).agg(
        donations_count=('amount', 'count'),
        gross_amount=('amount', 'sum'),
        fee_amount=('fee_amount', 'sum'),
        net_amount=('amount_charity', 'sum')
    ).reset_index()

    total_net = float(daily_df['net_amount'].sum())
    total_gross = float(daily_df['gross_amount'].sum())
    total_fee = float(daily_df['fee_amount'].sum())
    total_count = int(daily_df['donations_count'].sum())

    daily_df['fee_ratio'] = (daily_df['fee_amount'] / daily_df['gross_amount'].replace(0, pd.NA)).fillna(0)
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

        d_val = str(row[date_col]).split('T')[0] if pd.notna(row[date_col]) else 'Unspecified'
        c1 = ws.cell(row=curr_row, column=1, value=d_val)
        c2 = ws.cell(row=curr_row, column=2, value=int(row['donations_count']))
        c3 = ws.cell(row=curr_row, column=3, value=float(row['gross_amount']))
        c4 = ws.cell(row=curr_row, column=4, value=float(row['fee_amount']))
        c5 = ws.cell(row=curr_row, column=5, value=float(row['fee_ratio']))
        c6 = ws.cell(row=curr_row, column=6, value=float(row['net_amount']))

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

    ws.freeze_panes = f'A{header_row + 1}'
    auto_fit_columns(ws, max_col=num_cols)


def build_transactions_sheet(ws, df):
    """Write the complete raw itemized transactions sheet with formatting."""
    ws.views.sheetView[0].showGridLines = True
    
    # Header row
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

            # Number formatting
            if col_name in ('amount', 'fee_amount', 'amount_charity', 'exchange_rate'):
                if isinstance(val, (int, float)):
                    cell.number_format = FMT_CURRENCY
                    cell.alignment = align_right
            elif col_name in ('donation_id', 'is_giftaid', 'is_zakat', 'offline', 'is_anonymous'):
                cell.alignment = align_center
            elif col_name in ('Code', 'Country', 'Zakat Eligibility', 'Created Date (UTC)'):
                cell.alignment = align_center
            else:
                cell.alignment = align_left

    ws.freeze_panes = 'A2'
    auto_fit_columns(ws, max_col=len(df.columns), min_width=10, max_width=35)


def build_giftaid_schedule_sheet(ws, df):
    """Generate HMRC-compliant Gift Aid Claim Schedule sheet for tax reclaim."""
    ws.views.sheetView[0].showGridLines = True
    
    giftaid_col = 'is_giftaid' if 'is_giftaid' in df.columns else None
    if giftaid_col:
        giftaid_mask = df[giftaid_col].astype(str).str.strip().isin(['1', '1.0', 'true', 'True', 'yes', 'Yes'])
        ga_df = df[giftaid_mask].copy()
    else:
        ga_df = pd.DataFrame()

    col_headers = [
        "Donation Date", "First Name", "Last Name", "Address Line 1", "Address Line 2", "Postcode",
        "Donation Amount (£)", "25% Gift Aid Reclaim (£)", "Campaign Name", "Classification Code", "Payment Gateway"
    ]
    num_cols = len(col_headers)
    end_col_letter = get_column_letter(num_cols)

    ws.merge_cells(f'A1:{end_col_letter}1')
    ws['A1'] = "HMRC GIFT AID RECLAIM SCHEDULE & AUDIT"
    ws['A1'].font = font_banner
    ws['A1'].fill = fill_banner
    ws['A1'].alignment = align_center
    ws.row_dimensions[1].height = 26

    header_row = 3
    for col_idx, h in enumerate(col_headers, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_header
        cell.border = border_cell
    ws.row_dimensions[header_row].height = 26

    total_gross = 0.0
    total_reclaim = 0.0
    curr_row = header_row

    for _, row in ga_df.iterrows():
        curr_row += 1
        ws.row_dimensions[curr_row].height = 18
        zebra = (curr_row % 2 == 1)

        d_date = str(row.get('Created Date (UTC)') or row.get('created_at', '')).split('T')[0]
        amt = float(row.get('amount', 0.0) or 0.0)
        reclaim = round(amt * 0.25, 2)
        total_gross += amt
        total_reclaim += reclaim

        vals = [
            d_date,
            str(row.get('first_name', '') or '') if pd.notna(row.get('first_name')) else '',
            str(row.get('last_name', '') or '') if pd.notna(row.get('last_name')) else '',
            str(row.get('address_line_1', '') or '') if pd.notna(row.get('address_line_1')) else '',
            str(row.get('address_line_2', '') or '') if pd.notna(row.get('address_line_2')) else '',
            str(row.get('postcode', '') or '') if pd.notna(row.get('postcode')) else '',
            amt,
            reclaim,
            str(row.get('Campaign Name', '') or '') if pd.notna(row.get('Campaign Name')) else '',
            str(row.get('Code', '') or '') if pd.notna(row.get('Code')) else '',
            str(row.get('payment method', '') or '') if pd.notna(row.get('payment method')) else 'Stripe',
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

    ws.freeze_panes = f'A{header_row + 1}'
    auto_fit_columns(ws, max_col=num_cols)


def generate_accounts_workbook(df, file_path, payout_filename):
    """Construct the full multi-sheet audit & accounts reconciliation Excel workbook."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default blank sheet

    # Sheet 1: Executive Summary Dashboard
    ws_exec = wb.create_sheet(title='Executive Summary')
    build_executive_summary_sheet(ws_exec, df, payout_filename)

    # Sheet 2: Campaign Breakdown
    ws_camp = wb.create_sheet(title='Campaign Breakdown')
    camp_headers = [
        "Campaign Name", "Classification Code", "Heading", "Sub-Heading", "Country", "Zakat Eligibility",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_camp, "Campaign Performance & Fund Allocation Breakdown", ['Campaign Name', 'Code', 'Heading', 'Subheading', 'Country', 'Zakat Eligibility'], df, camp_headers)

    # Sheet 3: Code Breakdown
    ws_code = wb.create_sheet(title='Code Breakdown')
    code_headers = [
        "Classification Code", "Heading", "Sub-Heading", "Country", "Zakat Eligibility",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_code, "Fund Code Allocation & Classification Breakdown", ['Code', 'Heading', 'Subheading', 'Country', 'Zakat Eligibility'], df, code_headers)

    # Sheet 4: Department Breakdown
    ws_dept = wb.create_sheet(title='Department Breakdown')
    dept_headers = [
        "Department / Heading", "Programme Fund",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_dept, "Department & Programme Fund Allocation Breakdown", ['Heading', 'Programme Fund'], df, dept_headers)

    # Sheet 5: Country Breakdown
    ws_country = wb.create_sheet(title='Country Breakdown')
    country_headers = [
        "Country", "Department / Heading", "Zakat Eligibility",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_country, "Country & Geographical Fund Allocation Breakdown", ['Country', 'Heading', 'Zakat Eligibility'], df, country_headers)

    # Sheet 6: Payment Method Breakdown
    ws_pay = wb.create_sheet(title='Payment Method Breakdown')
    pay_headers = [
        "Payment Gateway", "Donation Type",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_pay, "Payment Gateway & Donation Type Reconciliation", ['payment method', 'Donation Type'], df, pay_headers)

    # Sheet 7: Zakat Reconciliation
    ws_zakat = wb.create_sheet(title='Zakat Reconciliation')
    zakat_headers = [
        "Zakat Eligibility",
        "Donations Count", "Gross Amount (£)", "Processing Fees (£)", "Fee Ratio (%)", "Net Settlement (£)", "% Share of Net"
    ]
    build_breakdown_sheet(ws_zakat, "Zakat vs Non-Zakat Audit Reconciliation", ['Zakat Eligibility'], df, zakat_headers)

    # Sheet 8: Gift Aid Schedule
    ws_ga = wb.create_sheet(title='Gift Aid Schedule')
    build_giftaid_schedule_sheet(ws_ga, df)

    # Sheet 9: Daily Settlement Breakdown
    ws_daily = wb.create_sheet(title='Daily Settlement')
    build_daily_breakdown_sheet(ws_daily, df)

    # Sheet 10: Transactions Audit (Raw Enriched Ledger)
    ws_trans = wb.create_sheet(title='Transactions Audit')
    build_transactions_sheet(ws_trans, df)

    # Save finalized multi-sheet workbook
    wb.save(file_path)


# ==============================================================================
# Main Orchestration Loop
# ==============================================================================

def enrich_payout_files(work_dir='.', donor_file=None, dry_run=False, make_backup=False):
    """Enrich all Iqra payout reconciliation files with donor metadata and accounting breakdown sheets."""
    if not donor_file:
        donor_file = find_latest_iqra_donors_file(work_dir)
        if not donor_file:
            print(f"[ERROR] Could not find Iqra donor reference file (e.g. filtered_donors_*.xlsx) in {work_dir}")
            return

    ref_indexes = load_iqra_donors(donor_file)
    by_cid = ref_indexes['by_cid']
    by_name_net = ref_indexes['by_name_net']
    by_name_gross = ref_indexes['by_name_gross']
    by_name = ref_indexes['by_name']

    all_files = (
        glob.glob(os.path.join(work_dir, "*.xlsx")) +
        glob.glob(os.path.join(work_dir, "*.xls")) +
        glob.glob(os.path.join(work_dir, "*.csv"))
    )

    donor_base = os.path.splitext(os.path.basename(donor_file))[0].lower()
    target_files = []
    for f in all_files:
        fname = os.path.basename(f)
        fname_lower = fname.lower()
        if fname.startswith('~$') or fname.endswith('.bak') or fname.endswith('.py') or fname.endswith('.bat'):
            continue
        if 'filtered_donors' in fname_lower or 'main_donors' in fname_lower:
            continue
        if os.path.splitext(fname)[0].lower() == donor_base:
            continue
        target_files.append(f)

    if not target_files:
        print("\n[INFO] No payout target files found to enrich in directory.")
        return

    print(f"\nFound {len(target_files)} payout file(s) to process.\n" + "=" * 65)

    target_cols = [
        'Country',
        'Donation Type',
        'payment method',
        'Heading',
        'Subheading',
        'Code',
        'Zakat Eligibility',
        'Created Date (UTC)',
        'donation_type',
        'Campaign Name',
        'Programme Fund',
        'Portfolio'
    ]

    total_files_processed = 0
    total_rows_updated = 0
    total_target_rows = 0
    locked_files = []

    for file_path in target_files:
        file_name = os.path.basename(file_path)
        is_excel = file_path.lower().endswith(('.xlsx', '.xls'))

        try:
            if is_excel:
                # Read from Transactions Audit if already processed, or first sheet
                xl = pd.ExcelFile(file_path)
                sheet_to_read = 'Transactions Audit' if 'Transactions Audit' in xl.sheet_names else xl.sheet_names[0]
                df = xl.parse(sheet_to_read)
            else:
                df = pd.read_csv(file_path)
        except Exception as e:
            print(f"[ERROR] Failed to read {file_name}: {e}")
            continue

        if len(df) == 0:
            print(f"[SKIP] {file_name} is empty.")
            continue

        essential_cols = [c for c in df.columns if c in ['charge_id', 'ID', 'first_name', 'First Name', 'amount', 'Amount']]
        if essential_cols:
            df = df.dropna(subset=essential_cols, how='all').copy()

        id_col = find_column(df, ['charge_id', 'Charge ID', 'ID', 'Transaction ID', 'id'])
        fn_col = find_column(df, ['first_name', 'First Name', 'Donor First Name', 'FirstName'])
        ln_col = find_column(df, ['last_name', 'Last Name', 'Donor Last Name', 'LastName', 'Surname'])
        net_col = find_column(df, ['amount_charity', 'Net Amount', 'Net', 'Total Online Donations Net Amount in Settled Currency'])
        gross_col = find_column(df, ['amount', 'Amount', 'Total LTV', 'Donation Amount'])
        gateway_col = find_column(df, ['gateway', 'Payment Method', 'Payment Type', 'payment_method_type'])
        created_col = find_column(df, ['created_at', 'Created', 'Created Date (UTC)', 'Date', 'Created At'])

        matched_count = 0
        enriched_data = {col: [] for col in target_cols}

        for idx, row in df.iterrows():
            cid = str(row[id_col]).strip() if id_col and pd.notna(row[id_col]) else None
            fn = row[fn_col] if fn_col else None
            ln = row[ln_col] if ln_col else None
            full = get_full_name(fn, ln)

            net_val = None
            if net_col and pd.notna(row[net_col]):
                try:
                    net_val = round(float(row[net_col]), 2)
                except Exception:
                    pass

            gross_val = None
            if gross_col and pd.notna(row[gross_col]):
                try:
                    gross_val = round(float(row[gross_col]), 2)
                except Exception:
                    pass

            match = None
            if cid and cid in by_cid:
                match = by_cid[cid]
            elif full and net_val is not None and (full, net_val) in by_name_net:
                match = by_name_net[(full, net_val)]
            elif full and gross_val is not None and (full, gross_val) in by_name_gross:
                match = by_name_gross[(full, gross_val)]
            elif full and full in by_name:
                match = by_name[full]

            if match:
                matched_count += 1
                for c in target_cols:
                    if c == 'payment method':
                        pm = row.get(gateway_col) if gateway_col and pd.notna(row.get(gateway_col)) else 'Stripe'
                        enriched_data[c].append(pm)
                    elif c == 'Created Date (UTC)':
                        c_date = row.get(created_col) if created_col and pd.notna(row.get(created_col)) else None
                        c_date_str = str(c_date).split(' ')[0].split('T')[0] if pd.notna(c_date) else None
                        enriched_data[c].append(c_date_str)
                    elif c in ('Donation Type', 'donation_type'):
                        freq = match.get(c) or (row.get('frequency') if 'frequency' in df.columns else None)
                        enriched_data[c].append(freq)
                    else:
                        enriched_data[c].append(match.get(c))
            else:
                for c in target_cols:
                    if c == 'payment method':
                        pm = row.get(gateway_col) if gateway_col and pd.notna(row.get(gateway_col)) else 'Stripe'
                        enriched_data[c].append(pm)
                    elif c == 'Created Date (UTC)':
                        c_date = row.get(created_col) if created_col and pd.notna(row.get(created_col)) else None
                        c_date_str = str(c_date).split(' ')[0].split('T')[0] if pd.notna(c_date) else None
                        enriched_data[c].append(c_date_str)
                    elif c in ('Donation Type', 'donation_type'):
                        freq = row.get('frequency') if 'frequency' in df.columns else None
                        enriched_data[c].append(freq)
                    else:
                        enriched_data[c].append(None)

        for col_name in target_cols:
            df[col_name] = enriched_data[col_name]

        match_pct = (matched_count / len(df) * 100) if len(df) > 0 else 0

        if not dry_run:
            if make_backup:
                backup_path = file_path + ".bak"
                if not os.path.exists(backup_path):
                    try:
                        shutil.copy2(file_path, backup_path)
                    except Exception:
                        pass

            try:
                # Build complete multi-sheet accounting workbook
                out_excel_path = file_path if is_excel else os.path.splitext(file_path)[0] + "_accounting_report.xlsx"
                generate_accounts_workbook(df, out_excel_path, file_name)
                
                # If original was CSV, also update CSV
                if not is_excel:
                    df.to_csv(file_path, index=False)

                print(f"[OK] {file_name:24} | Rows: {len(df):4} | Matched: {matched_count:4} / {len(df):4} ({match_pct:.1f}%)")
                print(f"     -> Generated 10 Accounts Sheets:")
                print(f"        1. Executive Summary     2. Campaign Breakdown    3. Code Breakdown")
                print(f"        4. Department Breakdown  5. Country Breakdown     6. Payment Method Breakdown")
                print(f"        7. Zakat Reconciliation  8. Gift Aid Schedule     9. Daily Settlement")
                print(f"        10. Transactions Audit (Raw Enriched Ledger)")
            except PermissionError:
                print(f"[LOCKED] {file_name:20} | Rows: {len(df):4} | File is open in Excel. Close it to save changes.")
                locked_files.append(file_name)
            except Exception as e:
                print(f"[ERROR] {file_name:22} | Error generating report: {e}")
        else:
            print(f"[DRY-RUN] {file_name:20} | Rows: {len(df):4} | Matched: {matched_count:4} / {len(df):4} ({match_pct:.1f}%)")
            print(f"          -> Would generate 10 complete accounts sheets (Executive Summary, Campaign, Code, Department, Country, Payment Method, Zakat, Gift Aid, Daily Settlement, Transactions Audit)")

        total_files_processed += 1
        total_rows_updated += matched_count
        total_target_rows += len(df)

    print("=" * 65)
    pct_total = (total_rows_updated / total_target_rows * 100) if total_target_rows > 0 else 0
    print(f"Summary: Processed {total_files_processed} file(s).")
    print(f"Matched and populated: {total_rows_updated} / {total_target_rows} rows ({pct_total:.1f}%).")

    if locked_files:
        print(f"\n[WARNING] {len(locked_files)} file(s) could not be saved because they are currently open in Excel: {', '.join(locked_files)}")
        print("Please close them and re-run fill_iqra_donor_data.bat to save changes.")
    elif dry_run:
        print("[NOTE] Dry-run mode: No files were modified.")
    else:
        print("Done! All Iqra payout reconciliation files now contain complete multi-sheet accounting breakdowns.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Enrich Iqra Charity payout files with donor metadata and multi-sheet accounting breakdowns.")
    parser.add_argument('--dir', default='.', help="Directory containing payout files (default: current directory)")
    parser.add_argument('--donors', default=None, help="Path to Iqra reference donor file (e.g. filtered_donors_*.xlsx)")
    parser.add_argument('--dry-run', action='store_true', help="Preview matches without modifying files")
    parser.add_argument('--backup', action='store_true', help="Create .bak backup of each modified file")

    args = parser.parse_args()
    enrich_payout_files(
        work_dir=args.dir,
        donor_file=args.donors,
        dry_run=args.dry_run,
        make_backup=args.backup
    )
