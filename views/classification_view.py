import os
import sqlite3
import pandas as pd
import streamlit as st

from config.settings import LOCAL_DB_PATH, PARQUET_PATH
from core.data_processor import (
    get_classification_matrix,
    save_classification_matrix,
    get_paysuite_classification_matrix,
    save_paysuite_classification_matrix,
    get_code_to_classification_map,
    sync_matrix_classifications_to_donors,
)


def get_givebright_classification_matrix(df_raw=None):
    """Returns GiveBright classification matrix DataFrame with (Campaign Name, Code) granularity."""
    target_cols_display = ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]

    # 1. Read SQLite stored GiveBright classifications
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        db_matrix = pd.read_sql_query("""
            SELECT 
                campaign_name as "Campaign Name",
                COALESCE(code, 'Unassigned') as "Code",
                COALESCE(campaign_url, '') as "Campaign URL",
                COALESCE(heading, 'Unassigned') as "Heading",
                COALESCE(sub_heading, 'Unassigned') as "Sub-Heading",
                COALESCE(country, 'Unassigned') as "Country",
                COALESCE(zakat_eligibility, 'Unassigned') as "Zakat Eligibility"
            FROM givebright_classifications
        """, conn)
    except Exception:
        db_matrix = pd.DataFrame(columns=["Campaign Name", "Code", "Campaign URL"] + [c for c in target_cols_display if c != "Code"])
    finally:
        conn.close()

    # 2. Extract distinct GiveBright campaigns from in-memory cached donations
    from core.data_processor import load_data
    df_donations = df_raw if (df_raw is not None and not df_raw.empty) else load_data()
    if df_donations is not None and not df_donations.empty and "Campaign Name" in df_donations.columns:
        platform_s = df_donations.get("Platform", pd.Series("", index=df_donations.index)).astype(str).str.lower()
        source_s = df_donations.get("Source", pd.Series("", index=df_donations.index)).astype(str).str.lower()
        gb_mask = (platform_s == "givebright") | source_s.str.contains("givebright|give_bright|file-", na=False)
        gb_df = df_donations[gb_mask] if gb_mask.any() else df_donations.iloc[0:0]

        if not gb_df.empty:
            c_name = gb_df["Campaign Name"].astype(str).str.strip()
            c_name = c_name[~c_name.str.lower().isin(['nan', 'none', 'n/a', '', 'unassigned'])]
            code_val = gb_df.loc[c_name.index, "Code"].astype(str).str.strip().replace({'nan': 'Unassigned', '': 'Unassigned', 'None': 'Unassigned'}) if "Code" in gb_df.columns else pd.Series("Unassigned", index=c_name.index)
            
            url_series = pd.Series("", index=gb_df.index)
            for u_col in ["Campaign URL", "campaign_url", "URL", "url"]:
                if u_col in gb_df.columns:
                    url_series = gb_df[u_col].fillna("").astype(str).replace({'nan': '', 'None': ''})
                    break

            donor_df = pd.DataFrame({"Campaign Name": c_name, "Code": code_val, "Campaign URL": url_series.loc[c_name.index]})
            for tc in target_cols_display:
                if tc in gb_df.columns and tc != "Code":
                    donor_df[tc] = gb_df.loc[c_name.index, tc].values

            donor_distinct = donor_df.drop_duplicates(subset=["Campaign Name", "Code"])

            if db_matrix.empty:
                return donor_distinct.fillna("Unassigned").reset_index(drop=True)

            merged = pd.merge(
                donor_distinct[["Campaign Name", "Code", "Campaign URL"]],
                db_matrix,
                on=["Campaign Name", "Code"],
                how="outer",
                suffixes=('', '_db')
            ).fillna("Unassigned")
            return merged.drop_duplicates(subset=["Campaign Name", "Code"]).reset_index(drop=True)

    if not db_matrix.empty:
        return db_matrix.fillna("Unassigned").reset_index(drop=True)

    return pd.DataFrame(columns=["Campaign Name", "Code", "Campaign URL"] + [c for c in target_cols_display if c != "Code"])


def save_givebright_classification_matrix(matrix_df):
    """Saves updated GiveBright classification matrix to SQLite and synchronizes to active donation records."""
    if matrix_df.empty:
        return 0

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)

    # 1. Reconcile codes per campaign: remove any codes in DB that are NOT in the submitted matrix for these campaigns
    cname_to_codes = {}
    for _, row in matrix_df.iterrows():
        cname = str(row.get("Campaign Name", "Unassigned")).strip().replace("’", "'").replace("‘", "'")
        code = str(row.get("Code", "Unassigned")).strip()
        if cname and cname.lower() not in ["nan", "none", "n/a", "", "campaign_name", "campaign name"]:
            cname_to_codes.setdefault(cname.lower(), set()).add(code.lower())

    for cname_lower, codes in cname_to_codes.items():
        placeholders = ','.join(['?'] * len(codes))
        conn.execute(f"DELETE FROM givebright_classifications WHERE LOWER(campaign_name) = ? AND LOWER(code) NOT IN ({placeholders})", [cname_lower] + list(codes))

    for _, row in matrix_df.iterrows():
        cname = str(row.get("Campaign Name", "Unassigned")).strip().replace("’", "'").replace("‘", "'")
        code = str(row.get("Code", "Unassigned")).strip()
        curl = str(row.get("Campaign URL") or row.get("campaign_url") or "")
        if not cname or cname.lower() in ["nan", "none", "n/a", "", "campaign_name", "campaign name"]:
            continue

        conn.execute("DELETE FROM givebright_classifications WHERE LOWER(campaign_name) = ? AND LOWER(code) = ?", (cname.lower(), code.lower()))
        conn.execute("""
            INSERT INTO givebright_classifications (campaign_name, code, campaign_url, heading, sub_heading, country, zakat_eligibility, is_primary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cname,
            code,
            curl,
            str(row.get("Heading", "Unassigned")),
            str(row.get("Sub-Heading", "Unassigned")),
            str(row.get("Country", "Unassigned")),
            str(row.get("Zakat Eligibility", "Unassigned")),
            1 if row.get("is_primary") in [1, True, "1", "true", "True"] else 0
        ))
    conn.commit()
    conn.close()

    # Re-apply to active dataset in Parquet and SQLite using sync_matrix_classifications_to_donors
    from core.data_processor import sync_matrix_classifications_to_donors
    sync_matrix_classifications_to_donors(matrix_df)

    return len(matrix_df)


def normalize_classification_import_df(raw_df):
    """Standardizes imported column names and auto-fills missing fields from recognized Codes."""
    col_mapping = {}
    for col in raw_df.columns:
        c_clean = str(col).strip().lower().replace("_", " ").replace("-", " ")
        if c_clean in ["campaign", "campaign name", "fundraiser name", "fundraiser", "bank ref", "direct debit ref", "project", "project name"]:
            col_mapping[col] = "Campaign Name"
        elif c_clean in ["community", "community name", "fundraiser by", "platform source"]:
            col_mapping[col] = "Community Name"
        elif c_clean in ["code", "campaign code", "project code", "cost code", "item code", "giving level fund code", "giving level campaign code", "fund code", "accounting code"]:
            col_mapping[col] = "Code"
        elif c_clean in ["heading", "main heading", "category", "main category"]:
            col_mapping[col] = "Heading"
        elif c_clean in ["sub heading", "subheading", "sub category", "subcategory", "sub_heading"]:
            col_mapping[col] = "Sub-Heading"
        elif c_clean in ["country", "beneficiary country", "target country"]:
            col_mapping[col] = "Country"
        elif c_clean in ["zakat eligibility", "zakat", "zakat eligibilty", "zakat status", "zakat_eligibility"]:
            col_mapping[col] = "Zakat Eligibility"
        elif c_clean in ["campaign url", "campaign link", "campaign page", "url", "link"]:
            col_mapping[col] = "Campaign URL"
        elif c_clean in ["fundraiser url", "fundraiser link", "fundraiser page"]:
            col_mapping[col] = "Fundraiser URL"

    df_norm = raw_df.rename(columns=col_mapping).copy()

    # Ensure required Campaign Name column exists
    if "Campaign Name" not in df_norm.columns:
        if len(df_norm.columns) > 0:
            df_norm.rename(columns={df_norm.columns[0]: "Campaign Name"}, inplace=True)

    if "Campaign URL" not in df_norm.columns:
        df_norm["Campaign URL"] = ""

    if "Community Name" not in df_norm.columns:
        df_norm["Community Name"] = "Unassigned"

    for col in ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]:
        if col not in df_norm.columns:
            df_norm[col] = "Unassigned"
        df_norm[col] = df_norm[col].fillna("Unassigned").astype(str).replace({'nan': 'Unassigned', '': 'Unassigned', 'None': 'Unassigned', 'TBC': 'To be confirmed'})

    # Auto-fill classifications based on Code mapping
    code_map = get_code_to_classification_map()
    for idx, row in df_norm.iterrows():
        code = str(row.get("Code") or "").strip()
        code_lower = code.lower()
        if code and code_lower not in ["unassigned", "nan", "none", "n/a", ""]:
            if code_lower in code_map:
                c_info = code_map[code_lower]
                for tc in ["Heading", "Sub-Heading", "Country", "Zakat Eligibility"]:
                    val = str(row.get(tc) or "").strip()
                    if not val or val.lower() in ["unassigned", "nan", "none", ""]:
                        df_norm.at[idx, tc] = c_info[tc]

    return df_norm


def render_classification_tab(df_raw, user_session):
    """Renders Campaign Classification matrix rules manager with strict RBAC."""
    st.header("🏷️ Campaign Classification Manager (Source of Truth)")
    st.markdown("This matrix is your **source of truth** for mapping Campaign Name ➔ Heading, Sub-Heading, Country, Code, and Zakat Eligibility.")

    matrix_platform = st.radio("Platform Matrix", options=["⚡ LaunchGood Matrix", "🎁 GiveBrite Matrix", "💳 Paysuite Matrix"], horizontal=True, key="matrix_platform_toggle")
    state_key = f"matrix_df_{matrix_platform}"

    if st.session_state.get("prev_matrix_platform") != matrix_platform:
        st.session_state.pop(state_key, None)
        st.session_state["prev_matrix_platform"] = matrix_platform

    if state_key not in st.session_state:
        if matrix_platform == "⚡ LaunchGood Matrix":
            matrix_df = get_classification_matrix()
        elif matrix_platform == "💳 Paysuite Matrix":
            matrix_df = get_paysuite_classification_matrix(df_raw)
        else:
            matrix_df = get_givebright_classification_matrix(df_raw)
    else:
        matrix_df = st.session_state[state_key]

    unassigned_count = (matrix_df["Heading"] == "Unassigned").sum() if "Heading" in matrix_df.columns else 0

    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1:
        st.metric(
            "Total Tracked Direct Debits" if matrix_platform == "💳 Paysuite Matrix" else "Total Tracked Campaigns", 
            f"{len(matrix_df):,}"
        )
    with col_c2:
        st.metric(
            "Fully Classified Debits" if matrix_platform == "💳 Paysuite Matrix" else "Fully Classified Campaigns", 
            f"{len(matrix_df) - unassigned_count:,}"
        )
    with col_c3:
        st.metric(
            "Unassigned Debits" if matrix_platform == "💳 Paysuite Matrix" else "Unassigned Campaigns", 
            f"{unassigned_count:,}"
        )

    st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

    # ── Export Row ───────────────────────────────────────────
    csv_matrix = matrix_df.to_csv(index=False).encode('utf-8')
    if matrix_platform == "⚡ LaunchGood Matrix":
        fname_export = "launchgood_classifications.csv"
    elif matrix_platform == "💳 Paysuite Matrix":
        fname_export = "paysuite_classifications.csv"
    else:
        fname_export = "givebright_classifications.csv"

    col_btn1, col_btn2 = st.columns([6, 4])
    with col_btn1:
        st.download_button(
            f"⬇️ Export {matrix_platform} Matrix (CSV)",
            csv_matrix,
            fname_export,
            "text/csv",
            use_container_width=True
        )

    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader(f"📝 {matrix_platform} Rules")

    if user_session.get("role") != "super_admin":
        st.info("🔒 **Read-Only Mode:** Logged in as Admin (`admin@analytics.com`). You can view and search classification rules. Rule editing, deletions, imports, and bulk updates are restricted to Super Admin accounts.")
        st.dataframe(matrix_df, use_container_width=True)
    else:
        # Bulk Upload / Import Form for Super Admin
        with st.expander(f"📂 Bulk Upload / Import {matrix_platform} Rules (CSV / Excel)", expanded=False):
            st.markdown(f"Upload a CSV or Excel spreadsheet containing classification mappings for **{matrix_platform}**. The system will auto-detect headers, map project codes, and automatically fill Headings, Countries, and Zakat status.")
            
            uploaded_rules_file = st.file_uploader(
                f"Choose {matrix_platform} Classification File (.csv or .xlsx)",
                type=["csv", "xlsx", "xls"],
                key=f"upload_rules_file_{matrix_platform}"
            )
            
            if uploaded_rules_file is not None:
                try:
                    if uploaded_rules_file.name.lower().endswith(".csv"):
                        raw_import_df = pd.read_csv(uploaded_rules_file)
                    else:
                        raw_import_df = pd.read_excel(uploaded_rules_file)
                    
                    parsed_rules_df = normalize_classification_import_df(raw_import_df)
                    
                    st.write(f"🔍 **Preview ({len(parsed_rules_df):,} rules detected):**")
                    if matrix_platform == "🎁 GiveBrite Matrix":
                        target_preview_cols = [c for c in ["Campaign Name", "Campaign URL", "Code", "Heading", "Sub-Heading", "Country", "Zakat Eligibility"] if c in parsed_rules_df.columns]
                    else:
                        target_preview_cols = [c for c in ["Campaign Name", "Community Name", "Code", "Heading", "Sub-Heading", "Country", "Zakat Eligibility"] if c in parsed_rules_df.columns]
                    st.dataframe(parsed_rules_df[target_preview_cols].head(10), use_container_width=True)
                    
                    col_imp1, col_imp2 = st.columns([6, 4])
                    with col_imp1:
                        import_mode = st.radio(
                            "Import Mode",
                            options=["Merge / Update Existing Rules", "Replace Entire Platform Matrix"],
                            horizontal=True,
                            key=f"import_mode_{matrix_platform}"
                        )
                    with col_imp2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        submit_import = st.button(f"📥 Import & Apply {len(parsed_rules_df):,} Rules Now", type="primary", use_container_width=True, key=f"btn_import_{matrix_platform}")
                    
                    if submit_import:
                        with st.spinner(f"Importing and applying rules to {matrix_platform}..."):
                            if import_mode == "Merge / Update Existing Rules" and not matrix_df.empty:
                                if matrix_platform == "🎁 GiveBrite Matrix":
                                    merged_target = pd.concat([matrix_df, parsed_rules_df], ignore_index=True).drop_duplicates(subset=["Campaign Name"], keep="last")
                                else:
                                    merged_target = pd.concat([matrix_df, parsed_rules_df], ignore_index=True).drop_duplicates(subset=["Campaign Name", "Community Name"], keep="last")
                            else:
                                merged_target = parsed_rules_df
                            
                            if matrix_platform == "⚡ LaunchGood Matrix":
                                n_saved = save_classification_matrix(merged_target)
                                sync_matrix_classifications_to_donors(merged_target)
                            elif matrix_platform == "💳 Paysuite Matrix":
                                n_saved = save_paysuite_classification_matrix(merged_target)
                                sync_matrix_classifications_to_donors(merged_target)
                            else:
                                n_saved = save_givebright_classification_matrix(merged_target)
                            
                            st.session_state.pop(state_key, None)
                            st.session_state.pop("df_raw", None)
                            st.cache_data.clear()
                            st.cache_resource.clear()
                            st.success(f"✅ Successfully imported and saved {n_saved:,} classification rules! Donor records have been re-classified.")
                            st.rerun()
                except Exception as e:
                    st.error(f"❌ Error parsing classification file: {e}")

        # Clear Platform Rules Danger Form for Super Admin
        with st.expander(f"🗑️ Clear / Reset All {matrix_platform} Rules", expanded=False):
            st.error(f"⚠️ **Caution:** This will permanently wipe all stored classification rules for {matrix_platform} and reset matching donor records to 'Unassigned'.")
            confirm_clear = st.checkbox(f"I understand this will delete all {matrix_platform} rules", key=f"confirm_clear_{matrix_platform}")
            if st.button(f"🚨 Delete All {matrix_platform} Rules Now", type="primary", disabled=not confirm_clear, key=f"btn_clear_{matrix_platform}"):
                conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
                try:
                    if matrix_platform == "🎁 GiveBrite Matrix":
                        conn.execute("DELETE FROM givebright_classifications;")
                    elif matrix_platform == "💳 Paysuite Matrix":
                        conn.execute("DELETE FROM paysuite_classifications;")
                    else:
                        conn.execute("DELETE FROM campaign_classifications;")
                    conn.commit()
                finally:
                    conn.close()
                st.session_state.pop(state_key, None)
                st.session_state.pop("df_raw", None)
                st.cache_data.clear()
                st.cache_resource.clear()
                st.success(f"✅ Cleared all rules for {matrix_platform}!")
                st.rerun()

        # Bulk Edit Form for Super Admin
        with st.expander("⚡ Bulk Edit Filtered Rows", expanded=False):
            with st.form(key=f"bulk_matrix_form_{matrix_platform}", clear_on_submit=False):
                b_col1, b_col2, b_col3, b_col4 = st.columns(4)
                with b_col1:
                    bulk_heading = st.text_input("New Heading", placeholder="e.g. Infrastructure", key=f"bulk_h_{matrix_platform}")
                with b_col2:
                    bulk_subheading = st.text_input("New Sub-Heading", placeholder="e.g. Clean Water", key=f"bulk_sh_{matrix_platform}")
                with b_col3:
                    bulk_country = st.text_input("New Country", placeholder="e.g. Gaza", key=f"bulk_c_{matrix_platform}")
                with b_col4:
                    bulk_zakat = st.selectbox("New Zakat Eligibility", ["Leave Unchanged", "Zakat", "Non-Zakat", "Unassigned"], key=f"bulk_z_{matrix_platform}")
                submit_bulk_matrix = st.form_submit_button("⚡ Apply Bulk Values to Filtered Rows", use_container_width=True)

            if submit_bulk_matrix:
                matrix_df_copy = matrix_df.copy()
                for idx in matrix_df_copy.index:
                    if bulk_heading.strip():
                        matrix_df_copy.at[idx, "Heading"] = bulk_heading.strip()
                    if bulk_subheading.strip():
                        matrix_df_copy.at[idx, "Sub-Heading"] = bulk_subheading.strip()
                    if bulk_country.strip():
                        matrix_df_copy.at[idx, "Country"] = bulk_country.strip()
                    if bulk_zakat != "Leave Unchanged":
                        matrix_df_copy.at[idx, "Zakat Eligibility"] = bulk_zakat
                st.session_state[state_key] = matrix_df_copy
                st.success("✅ Applied changes to rows in-memory! Click 'Save & Apply Rules Now' below to save.")
                st.rerun()

        # Custom column headers rename for data editor
        display_matrix_df = matrix_df.copy()
        if matrix_platform == "💳 Paysuite Matrix":
            display_matrix_df.rename(columns={
                "Campaign Name": "Direct Debit Ref (Bank Ref)",
                "Community Name": "Platform Source"
            }, inplace=True)

        column_config = {}
        if matrix_platform == "🎁 GiveBrite Matrix" and "Campaign URL" in display_matrix_df.columns:
            column_config["Campaign URL"] = st.column_config.LinkColumn("Campaign URL", display_text="Open Link")

        edited_df = st.data_editor(
            display_matrix_df,
            use_container_width=True,
            column_config=column_config,
            num_rows="dynamic",
            key=f"editor_{matrix_platform}"
        )

        # Restore column names before saving
        if matrix_platform == "💳 Paysuite Matrix":
            edited_df.rename(columns={
                "Direct Debit Ref (Bank Ref)": "Campaign Name",
                "Platform Source": "Community Name"
            }, inplace=True)

        if st.button(f"💾 Save & Apply {matrix_platform} Rules Now", type="primary", use_container_width=True):
            save_target_df = st.session_state.get(state_key, edited_df)
            with st.spinner("Saving rules to database..."):
                if matrix_platform == "⚡ LaunchGood Matrix":
                    n_saved = save_classification_matrix(save_target_df)
                    sync_matrix_classifications_to_donors(save_target_df)
                elif matrix_platform == "💳 Paysuite Matrix":
                    n_saved = save_paysuite_classification_matrix(save_target_df)
                    sync_matrix_classifications_to_donors(save_target_df)
                else:
                    n_saved = save_givebright_classification_matrix(save_target_df)
                st.session_state.pop(state_key, None)
                st.session_state.pop("df_raw", None)
                st.success(f"✅ Saved {n_saved:,} campaign rules!")
                st.rerun()
