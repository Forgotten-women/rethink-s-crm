"""
Ramadhan 1447 (Feb-Mar 2026) Analysis & Extraction Script
Pulls all metrics requested in questions.md from local Parquet & SQLite databases.
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath("."))
from config.settings import LOCAL_DB_PATH, PARQUET_PATH

def generate_ramadhan_report(
    start_date="2026-02-18",
    end_date="2026-03-20",
    output_dir="reports"
):
    os.makedirs(output_dir, exist_ok=True)
    df = pd.read_parquet(PARQUET_PATH)
    df['dt'] = pd.to_datetime(df['Created Date (UTC)'], errors='coerce')
    
    # Amount column
    amt_col = 'Total Online Donation Gross Amount in Settled Currency'
    if amt_col not in df.columns or df[amt_col].isna().all():
        amt_col = 'Donation Amount (in Donation Currency)'
    df['amount_num'] = pd.to_numeric(df[amt_col], errors='coerce').fillna(0.0)

    # Filter Ramadhan period
    r_df = df[(df['dt'] >= start_date) & (df['dt'] <= end_date)].copy()
    print(f"=== RAMADHAN 1447 REPORT ({start_date} to {end_date}) ===")
    print(f"Total Transactions: {len(r_df):,}")
    print(f"Total Gross Raised: £{r_df['amount_num'].sum():,.2f}\n")

    # 1. TOTALS BY SOURCE / CHANNEL
    print("--- 1. Totals by Platform / Channel ---")
    by_channel = r_df.groupby('Platform')['amount_num'].agg(
        Donations='count',
        Gross_Raised='sum',
        Avg_Donation='mean'
    ).reset_index()
    by_channel['Gross_Raised'] = by_channel['Gross_Raised'].round(2)
    by_channel['Avg_Donation'] = by_channel['Avg_Donation'].round(2)
    print(by_channel.to_string(index=False))
    by_channel.to_csv(f"{output_dir}/1_totals_by_channel.csv", index=False)

    # By Heading / Fund
    print("\n--- Totals by Appeal / Fund Heading ---")
    by_heading = r_df.groupby('Heading')['amount_num'].agg(
        Donations='count',
        Gross_Raised='sum'
    ).sort_values('Gross_Raised', ascending=False).reset_index()
    by_heading['Gross_Raised'] = by_heading['Gross_Raised'].round(2)
    print(by_heading.head(10).to_string(index=False))
    by_heading.to_csv(f"{output_dir}/1_totals_by_fund_heading.csv", index=False)

    # Zakat vs Sadaqah
    print("\n--- Zakat vs Non-Zakat Breakdown ---")
    z_col = 'Zakat Eligibility' if 'Zakat Eligibility' in r_df.columns else 'Zakat (yes or no)'
    by_zakat = r_df.groupby(z_col)['amount_num'].agg(
        Donations='count',
        Gross_Raised='sum'
    ).reset_index()
    by_zakat['Gross_Raised'] = by_zakat['Gross_Raised'].round(2)
    print(by_zakat.to_string(index=False))

    # Daily Totals: First 20 Days vs Last 10 Nights
    r_df['date_only'] = r_df['dt'].dt.strftime('%Y-%m-%d')
    daily = r_df.groupby('date_only')['amount_num'].agg(
        Donations='count',
        Gross_Raised='sum'
    ).reset_index().sort_values('date_only')
    daily.to_csv(f"{output_dir}/1_daily_totals.csv", index=False)

    # Split: First 20 Days (approx Feb 18 to Mar 9) vs Last 10 Nights (Mar 10 to Mar 20)
    first_20 = r_df[r_df['dt'] <= '2026-03-09']
    last_10 = r_df[r_df['dt'] > '2026-03-09']
    print(f"\n--- First 20 Days vs Last 10 Nights ---")
    print(f"First 20 Days: £{first_20['amount_num'].sum():,.2f} ({len(first_20):,} donations)")
    print(f"Last 10 Nights: £{last_10['amount_num'].sum():,.2f} ({len(last_10):,} donations)")

    # 2. DONORS (Unique, New vs Returning, Avg Gift, Top 50)
    print("\n--- 3. Donors Analysis ---")
    email_col = 'Email' if 'Email' in r_df.columns else 'Donor ID'
    unique_donors = r_df[email_col].dropna().astype(str).str.strip().str.lower().nunique()
    avg_gift = r_df['amount_num'].mean()
    print(f"Total Unique Donors: {unique_donors:,}")
    print(f"Average Gift Size: £{avg_gift:.2f}")

    # New vs Returning Donors
    # Donor's earliest gift in the entire database
    earliest_gifts = df.groupby(df['Email'].dropna().astype(str).str.strip().str.lower())['dt'].min()
    ramadhan_donor_emails = r_df[email_col].dropna().astype(str).str.strip().str.lower().unique()
    
    new_count = 0
    returning_count = 0
    for em in ramadhan_donor_emails:
        first_dt = earliest_gifts.get(em)
        if pd.notna(first_dt) and first_dt < pd.to_datetime(start_date):
            returning_count += 1
        else:
            new_count += 1
    
    print(f"New Donors in Ramadhan: {new_count:,} ({new_count/max(unique_donors, 1)*100:.1f}%)")
    print(f"Returning Donors: {returning_count:,} ({returning_count/max(unique_donors, 1)*100:.1f}%)")

    # Top 50 Donors
    top_50 = r_df.groupby([email_col, 'First Name', 'Last Name', 'Billing Country'])['amount_num'].agg(
        Total_Given='sum',
        Donation_Count='count'
    ).reset_index().sort_values('Total_Given', ascending=False).head(50)
    top_50['Total_Given'] = top_50['Total_Given'].round(2)
    top_50.to_csv(f"{output_dir}/3_top_50_major_donors.csv", index=False)
    print(f"Top 50 Major Donors exported to {output_dir}/3_top_50_major_donors.csv")

    # Email List & Marketing Consent
    mc_col = 'Marketing Consent' if 'Marketing Consent' in r_df.columns else 'optin'
    if mc_col in r_df.columns:
        print(f"\nMarketing Consent in Ramadhan: {r_df[mc_col].value_counts(dropna=False).to_dict()}")

    # 4. GIFT AID
    print("\n--- 4. Gift Aid Declarations ---")
    ga_col = 'Gift Aid (yes or no)' if 'Gift Aid (yes or no)' in r_df.columns else 'is_giftaid'
    if ga_col in r_df.columns:
        ga_summary = r_df.groupby(ga_col)['amount_num'].agg(
            Count='count',
            Eligible_Donations='sum'
        ).reset_index()
        ga_summary['Estimated_Gift_Aid_25pct'] = (ga_summary['Eligible_Donations'] * 0.25).round(2)
        print(ga_summary.to_string(index=False))
        ga_summary.to_csv(f"{output_dir}/4_gift_aid_summary.csv", index=False)

    # 5. RECURRING GIVING
    print("\n--- 6. Recurring Giving ---")
    if 'Payment Frequency' in r_df.columns:
        rec_summary = r_df.groupby('Payment Frequency')['amount_num'].agg(
            Count='count',
            Total_Raised='sum'
        ).reset_index()
        print(rec_summary.to_string(index=False))

    print(f"\nAll report CSVs generated successfully in folder: '{output_dir}/'")

if __name__ == "__main__":
    generate_ramadhan_report()
