import os
import sys
import glob
import shutil
import argparse
import pandas as pd


def find_column(df, candidate_names):
    """Find a column in df matching any name in candidate_names (case-insensitive, ignoring underscores and spaces)."""
    df_cols = list(df.columns)
    
    # Exact match first
    for name in candidate_names:
        if name in df.columns:
            return name
            
    # Normalized check (ignore case, spaces, underscores, dashes)
    def normalize(s):
        return str(s).lower().replace(' ', '').replace('_', '').replace('-', '')
        
    normalized_candidates = [normalize(c) for c in candidate_names]
    for col in df_cols:
        if normalize(col) in normalized_candidates:
            return col
            
    return None


def get_first_valid_series(df, candidate_names):
    """Return a Series from df from the first candidate column that exists and has values."""
    for name in candidate_names:
        col = find_column(df, [name])
        if col is not None:
            series = df[col]
            if series.notna().any():
                return series
    return None


def load_main_donors(main_file_path):
    """Load and prepare reference dictionary strictly from Main_donors file only."""
    print(f"Loading reference data STRICTLY from: {main_file_path}")
    if main_file_path.lower().endswith(('.xlsx', '.xls')):
        df_main = pd.read_excel(main_file_path)
    else:
        df_main = pd.read_csv(main_file_path)
        
    print(f"Total rows in Main Donors: {len(df_main)}")
    
    # Find charge_id column in Main_donors
    charge_id_col = find_column(df_main, ['charge_id', 'Charge ID', 'ID', 'charge id', 'Transaction ID'])
    if not charge_id_col:
        raise ValueError(f"Could not find 'charge_id' column in {main_file_path}")
        
    # Filter rows with non-null charge_id
    df_main = df_main[df_main[charge_id_col].notna()].copy()
    df_main['_clean_charge_id'] = df_main[charge_id_col].astype(str).str.strip()
    df_main = df_main[df_main['_clean_charge_id'] != 'nan']
    
    # Deduplicate on charge_id, keeping first non-null entry
    df_main = df_main.drop_duplicates(subset=['_clean_charge_id'], keep='first')
    
    # Map each column strictly from Main_donors
    country_col = find_column(df_main, ['Country', 'Billing Country', 'Donor Address Country Code'])
    dt_col = find_column(df_main, ['donation_type', 'Donation Type', 'Payment Type'])
    pm_col = find_column(df_main, ['payment_method_type', 'Payment Type', 'payment method', 'Payment Method'])
    # CRITICAL: Heading is Department (NOT 'title' which contains salutations Mr/Mrs/Miss)
    heading_col = find_column(df_main, ['Heading', 'heading', 'Department', 'department', 'Campaign Name'])
    # CRITICAL: Subheading is Office
    subheading_col = find_column(df_main, ['Subheading', 'Sub-Heading', 'Sub Heading', 'subheading', 'Office', 'office'])
    code_col = find_column(df_main, ['Code', 'code', 'New Code', 'Fund Code', 'Cause/Code'])
    zakat_col = find_column(df_main, ['Zakat Eligibility', 'is_zakat', 'Zakat Status', 'Zakat (yes or no)'])
    created_date_col = find_column(df_main, ['Created Date (UTC)', 'created_at', 'Created At', 'Created Date', 'Date'])
    
    ref_dict = {}
    for idx, row in df_main.iterrows():
        cid = row['_clean_charge_id']
        
        c_date = row.get(created_date_col) if created_date_col else None
        if pd.notna(c_date):
            c_date_str = str(c_date).split(' ')[0].split('T')[0]
        else:
            c_date_str = None

        val_heading = row.get(heading_col) if heading_col else None
        if pd.isna(val_heading) or not str(val_heading).strip():
            val_heading = row.get('Department')

        val_subheading = row.get(subheading_col) if subheading_col else None
        if pd.isna(val_subheading) or not str(val_subheading).strip():
            val_subheading = row.get('Office')

        val_dt = row.get(dt_col) if dt_col else None
        val_pm = row.get(pm_col) if pm_col else None
        val_country = row.get(country_col) if country_col else None
        val_code = row.get(code_col) if code_col else None
        val_zakat = row.get(zakat_col) if zakat_col else None

        ref_dict[cid] = {
            'Country': val_country if pd.notna(val_country) else None,
            'Donation Type': val_dt if pd.notna(val_dt) else None,
            'payment method': val_pm if pd.notna(val_pm) else None,
            'Heading': val_heading if pd.notna(val_heading) else None,
            'Subheading': val_subheading if pd.notna(val_subheading) else None,
            'Code': val_code if pd.notna(val_code) else None,
            'Zakat Eligibility': val_zakat if pd.notna(val_zakat) else None,
            'Created Date (UTC)': c_date_str,
            'donation_type': val_dt if pd.notna(val_dt) else None,
        }
        
    print(f"Loaded {len(ref_dict)} unique charge IDs from Main Donors.")
    return ref_dict


def process_files(work_dir='.', main_donors_file=None, dry_run=False, make_backup=False):
    """Process all payout/transfer files in work_dir strictly matching against Main_donors."""
    if not main_donors_file:
        candidates = glob.glob(os.path.join(work_dir, "Main_donors*")) + glob.glob(os.path.join(work_dir, "main_donors*"))
        candidates = [c for c in candidates if not os.path.basename(c).startswith('~$') and not c.endswith('.bak') and not c.endswith('.py') and not c.endswith('.bat')]
        if not candidates:
            print(f"[ERROR] Could not find Main_donors file in {work_dir}")
            return
        main_donors_file = candidates[0]

    ref_dict = load_main_donors(main_donors_file)
    if not ref_dict:
        print("[ERROR] No reference donor records loaded from Main Donors.")
        return

    # Collect all target files in directory
    all_files = (
        glob.glob(os.path.join(work_dir, "*.csv")) +
        glob.glob(os.path.join(work_dir, "*.xlsx")) +
        glob.glob(os.path.join(work_dir, "*.xls"))
    )

    main_base = os.path.splitext(os.path.basename(main_donors_file))[0].lower()
    target_files = []
    for f in all_files:
        fname = os.path.basename(f)
        fname_lower = fname.lower()
        if fname.startswith('~$') or fname.endswith('.py') or fname.endswith('.bat') or fname.endswith('.bak'):
            continue
        if os.path.splitext(fname)[0].lower() == main_base:
            continue
        target_files.append(f)

    print(f"\nFound {len(target_files)} target file(s) to process.\n" + "-" * 60)

    target_cols = [
        'Country',
        'Donation Type',
        'payment method',
        'Heading',
        'Subheading',
        'Code',
        'Zakat Eligibility',
        'Created Date (UTC)',
        'donation_type'
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
                df = pd.read_excel(file_path)
            else:
                df = pd.read_csv(file_path)
        except Exception as e:
            print(f"[ERROR] Failed to read {file_name}: {e}")
            continue

        if len(df) == 0:
            print(f"[SKIP] {file_name} is empty.")
            continue

        id_col = find_column(df, ['ID', 'charge_id', 'Charge ID', 'Charge Id', 'charge id', 'Transaction ID', 'id'])
        if not id_col:
            print(f"[WARN] No charge ID column found in {file_name}. Columns: {list(df.columns)}")
            continue

        clean_ids = df[id_col].astype(str).str.strip()
        matched_mask = clean_ids.isin(ref_dict)
        matched_count = matched_mask.sum()

        for col_name in target_cols:
            mapped_values = clean_ids.map(lambda cid: ref_dict.get(cid, {}).get(col_name) if cid in ref_dict else None)
            df[col_name] = mapped_values

        # If Created Date (UTC) is missing for any row, use the date from transfer file's 'Created' column
        if 'Created' in df.columns:
            created_fallback = df['Created'].astype(str).str.split(' ').str[0].str.split('T').str[0]
            df['Created Date (UTC)'] = df['Created Date (UTC)'].fillna(created_fallback)

        if not dry_run:
            if make_backup:
                backup_path = file_path + ".bak"
                if not os.path.exists(backup_path):
                    try:
                        shutil.copy2(file_path, backup_path)
                    except Exception:
                        pass

            try:
                if is_excel:
                    df.to_excel(file_path, index=False)
                else:
                    df.to_csv(file_path, index=False)
                print(f"[OK] {file_name:22} | Rows: {len(df):3} | Matched & Filled: {matched_count:3} / {len(df):3}")
            except PermissionError:
                print(f"[LOCKED] {file_name:20} | Rows: {len(df):3} | Error: File is open in another app (close it to update).")
                locked_files.append(file_name)
            except Exception as e:
                print(f"[ERROR] {file_name:21} | Error saving: {e}")
        else:
            print(f"[DRY-RUN] {file_name:18} | Rows: {len(df):3} | Matched: {matched_count:3} / {len(df):3}")

        total_files_processed += 1
        total_rows_updated += matched_count
        total_target_rows += len(df)

    print("-" * 60)
    print(f"Summary: Processed {total_files_processed} files. Matched and populated values: {total_rows_updated} / {total_target_rows} rows.")
    if locked_files:
        print(f"\n[WARNING] {len(locked_files)} file(s) could not be saved because they are currently open in Excel/another program: {', '.join(locked_files)}")
        print("Please close them and re-run fill_donor_data.bat to save changes.")
    elif dry_run:
        print("[NOTE] Dry-run mode: No files were overwritten.")
    else:
        print("Done! All target files now contain ONLY verified values from Main_donors.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Enrich payout and transfer files with donor metadata strictly from Main_donors based on charge_id.")
    parser.add_argument('--dir', default='.', help="Directory containing payout/transfer files (default: current directory)")
    parser.add_argument('--main-donors', default=None, help="Path to Main_donors Excel/CSV file")
    parser.add_argument('--dry-run', action='store_true', help="Preview matches without modifying files")
    parser.add_argument('--backup', action='store_true', help="Create .bak backup of each modified file")

    args = parser.parse_args()
    process_files(
        work_dir=args.dir,
        main_donors_file=args.main_donors,
        dry_run=args.dry_run,
        make_backup=args.backup
    )
