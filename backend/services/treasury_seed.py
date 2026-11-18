"""Schema creator and reconciled baseline seeder for the Treasury & Project Pots module."""

import csv
import json
import os
import re
import sqlite3
from typing import Dict, List, Optional, Tuple

DEFAULT_ARCHIVE_DIR = "/home/ubuntu/Python_Visualization/scratch/fund_position_analysis/Fund_Position_Sources_2026-10-31"
DEFAULT_DB_PATH = "/home/ubuntu/Python_Visualization/launchgood_donations.db"

OVERHEAD_KEYWORDS = (
    "office", "commity", "committee", "transfer fees", "head office", "headoffice",
    "legal", "logistics", "clo ", "management", "admin", "meal", "finance",
    "central affairs", "internal media", "feedback", "souce africa", "deployment",
)

# Canonical treasury accounts reconciled at 31 Oct 2026 (USD total = 1,806,553.50)
BASELINE_ACCOUNTS: List[Dict[str, object]] = [
    # United Kingdom
    {"id": "uk_lloyds", "num": 5, "name": "Lloyds Bank Main", "name_ar": "Lloyd", "group": "United Kingdom", "type": "bank", "holder": "Yunus", "supervisor": "Homam", "cur": "GBP", "native": 303665.80, "fx": 1.33, "note": "Main UK operating account for LaunchGood, GiveBrite, Stripe & APS"},
    {"id": "uk_coop", "num": 6, "name": "Co-op Bank", "name_ar": "Coop", "group": "United Kingdom", "type": "bank", "holder": "Yunus", "supervisor": "Homam", "cur": "GBP", "native": 92895.71, "fx": 1.33, "note": ""},
    {"id": "uk_osman_box", "num": 8, "name": "Osman's Cash Box (UK-CH-25-OA)", "name_ar": "صندوق عثمان بريطانيا", "group": "United Kingdom", "type": "cash_safe", "holder": "Osman", "supervisor": "Homam", "cur": "GBP", "native": 35374.43, "fx": 1.33, "note": ""},
    {"id": "uk_aj_box", "num": 9, "name": "Abdul Jabbar's Box (AJ)", "name_ar": "صندوق عبد الجبار", "group": "United Kingdom", "type": "cash_safe", "holder": "Abdul Jabbar", "supervisor": "Homam", "cur": "GBP", "native": 3671.00, "fx": 1.33, "note": ""},

    # Turkey
    {"id": "tr_nisva", "num": 10, "name": "NISVA (Vakıf Bank)", "name_ar": "NISVA", "group": "Turkey", "type": "bank", "holder": "Ayman", "supervisor": "Abu Al-Majd", "cur": "USD", "native": 0.0, "fx": 1.0, "note": "All Oct transfers passed through to Syria; 2,532.53 residual + FX 500 is NISVA's own money"},
    {"id": "tr_ziraat_usd", "num": 17, "name": "Ziraat Bank USD", "name_ar": "زراعات دولار", "group": "Turkey", "type": "bank", "holder": "Ayman", "supervisor": "Abu Al-Majd", "cur": "USD", "native": 31366.36, "fx": 1.0, "note": "Main Turkey corporate USD bank"},
    {"id": "tr_ziraat_try", "num": 18, "name": "Ziraat Bank TRY (TL)", "name_ar": "زراعات ل.ت", "group": "Turkey", "type": "bank", "holder": "Ayman", "supervisor": "Abu Al-Majd", "cur": "TRY", "native": 229147.14, "fx": 0.02001, "note": "Turkey operating TRY account"},
    {"id": "tr_ziraat_gbp", "num": 20, "name": "Ziraat Bank GBP", "name_ar": "زراعات جينيه", "group": "Turkey", "type": "bank", "holder": "Ayman", "supervisor": "Abu Al-Majd", "cur": "GBP", "native": 5450.03, "fx": 1.33, "note": ""},
    {"id": "tr_ziraat_eur", "num": 19, "name": "Ziraat Bank EUR", "name_ar": "زراعات يورو", "group": "Turkey", "type": "bank", "holder": "Ayman", "supervisor": "Abu Al-Majd", "cur": "EUR", "native": 0.0, "fx": 1.12315, "note": ""},
    {"id": "tr_ziraat_don_usd", "num": 21, "name": "Ziraat Donation USD", "name_ar": "زراعات تبرع دولار", "group": "Turkey", "type": "bank", "holder": "Ayman", "supervisor": "Abu Al-Majd", "cur": "USD", "native": 716.44, "fx": 1.0, "note": ""},
    {"id": "tr_ziraat_don_try", "num": 22, "name": "Ziraat Donation TRY (TL)", "name_ar": "زراعات تبرع ل.ت", "group": "Turkey", "type": "bank", "holder": "Ayman", "supervisor": "Abu Al-Majd", "cur": "TRY", "native": 429877.48, "fx": 0.02001, "note": ""},
    {"id": "tr_ziraat_don_eur", "num": 23, "name": "Ziraat Donation EUR", "name_ar": "زراعات تبرع يورو", "group": "Turkey", "type": "bank", "holder": "Ayman", "supervisor": "Abu Al-Majd", "cur": "EUR", "native": 0.0, "fx": 1.12315, "note": ""},
    {"id": "tr_hanzala_crypto", "num": 11, "name": "Hanzala Crypto Wallet", "name_ar": "Crypto", "group": "Turkey", "type": "crypto", "holder": "Abu Hanzala", "supervisor": "Abu Al-Majd", "cur": "USDT", "native": 1433.00, "fx": 1.0, "note": ""},
    {"id": "tr_hanzala_usd", "num": 13, "name": "Hanzala Cash Safe USD", "name_ar": "صندوق ابو حنظلة تركيا دولار", "group": "Turkey", "type": "cash_safe", "holder": "Abu Hanzala", "supervisor": "Abu Al-Majd", "cur": "USD", "native": 13626.00, "fx": 1.0, "note": ""},
    {"id": "tr_hanzala_try", "num": 14, "name": "Hanzala Cash Safe TRY", "name_ar": "صندوق ابو حنظلة تركيا TL", "group": "Turkey", "type": "cash_safe", "holder": "Abu Hanzala", "supervisor": "Abu Al-Majd", "cur": "TRY", "native": 2320.92, "fx": 0.02001, "note": ""},
    {"id": "tr_hanzala_gbp", "num": 15, "name": "Hanzala Cash Safe GBP", "name_ar": "صندوق ابو حنظلة تركيا GBB", "group": "Turkey", "type": "cash_safe", "holder": "Abu Hanzala", "supervisor": "Abu Al-Majd", "cur": "GBP", "native": 9125.00, "fx": 1.33, "note": ""},
    {"id": "tr_hanzala_eur", "num": 16, "name": "Hanzala Cash Safe EUR", "name_ar": "صندوق ابو حنظلة تركيا يورو", "group": "Turkey", "type": "cash_safe", "holder": "Abu Hanzala", "supervisor": "Abu Al-Majd", "cur": "EUR", "native": 965.00, "fx": 1.12315, "note": ""},
    {"id": "tr_hanzala_reserve", "num": 12, "name": "Turkey Emergency Reserve", "name_ar": "صندوق الطوارئ تركيا", "group": "Turkey", "type": "reserve", "holder": "Abu Hanzala", "supervisor": "Abu Al-Majd", "cur": "USD", "native": 0.0, "fx": 1.0, "note": "Office safe"},
    {"id": "tr_umut_try", "num": 24, "name": "UMUT İnşası TRY", "name_ar": "وقف أموت ل.ت", "group": "Turkey", "type": "bank", "holder": "Abu Al-Majd", "supervisor": "Abu Al-Majd", "cur": "TRY", "native": 2040.57, "fx": 0.02001, "note": "UMUT is our organisation; its balance is our cash"},
    {"id": "tr_umut_usd", "num": 24, "name": "UMUT İnşası USD", "name_ar": "وقف أموت دولار", "group": "Turkey", "type": "bank", "holder": "Abu Al-Majd", "supervisor": "Abu Al-Majd", "cur": "USD", "native": 0.0, "fx": 1.0, "note": ""},

    # Syria
    {"id": "sy_humam_box", "num": 31, "name": "Humam's Box (H.S)", "name_ar": "صندوق همام $", "group": "Syria", "type": "cash_safe", "holder": "Humam", "supervisor": "Humam", "cur": "USD", "native": 541152.28, "fx": 1.0, "note": "Includes $400,000 Aleppo surplus moved 25 Oct & Sajjad/OGN amanahs"},
    {"id": "sy_azaz_box", "num": 26, "name": "Azaz Box (Radwan)", "name_ar": "صندوق اعزاز", "group": "Syria", "type": "cash_safe", "holder": "Radwan", "supervisor": "Accountant", "cur": "USD", "native": 175524.60, "fx": 1.0, "note": "Per Syria cash report 31 Oct"},
    {"id": "sy_damascus_box", "num": 27, "name": "Damascus Box (Anas)", "name_ar": "صندوق دمشق", "group": "Syria", "type": "cash_safe", "holder": "Anas", "supervisor": "Accountant", "cur": "USD", "native": 60018.54, "fx": 1.0, "note": "Per Syria cash report 31 Oct"},
    {"id": "sy_idleb_box", "num": 25, "name": "Idleb Box (Manar)", "name_ar": "صندوق ادلب", "group": "Syria", "type": "cash_safe", "holder": "Manar", "supervisor": "Accountant", "cur": "USD", "native": 34837.74, "fx": 1.0, "note": "Per Syria cash report 31 Oct"},
    {"id": "sy_emergency_reserve", "num": 29, "name": "Syria Emergency Reserve (Abdulkadir)", "name_ar": "صندوق الطوارئ سوريا", "group": "Syria", "type": "reserve", "holder": "Abdulkadir", "supervisor": "Accountant", "cur": "USD", "native": 25034.00, "fx": 1.0, "note": "Abdulkadir Reserve safe"},
    {"id": "sy_albaraka", "num": 26, "name": "Al Baraka Bank Syria", "name_ar": "مصرف البركة ل.س & دولار", "group": "Syria", "type": "bank", "holder": "Syria Accountant", "supervisor": "Accountant", "cur": "USD", "native": 1256.00, "fx": 1.0, "note": ""},
    {"id": "sy_bemo", "num": 28, "name": "Bemo Bank Syria (SYP eqv.)", "name_ar": "مصرف بيمو ل.س سوريا", "group": "Syria", "type": "bank", "holder": "Syria Accountant", "supervisor": "Accountant", "cur": "USD", "native": 875.00, "fx": 1.0, "note": ""},
    {"id": "sy_abuhusam_box", "num": 35, "name": "Abu Husam's Box", "name_ar": "صندوق أبو حسام", "group": "Syria", "type": "cash_safe", "holder": "Abu Husam", "supervisor": "Humam", "cur": "USD", "native": 900.00, "fx": 1.0, "note": ""},
    {"id": "sy_nael_debts", "num": 32, "name": "Debts Owed to Us (Nael)", "name_ar": "ديون نائل", "group": "Syria", "type": "cash_safe", "holder": "Nael", "supervisor": "Humam", "cur": "USD", "native": 1500.00, "fx": 1.0, "note": "Nael owed 3,000, repaid 1,500 on 7 Oct"},

    # South Africa
    {"id": "sa_fnb_inv", "num": 3, "name": "FNB Investment Account", "name_ar": "investment account", "group": "South Africa", "type": "bank", "holder": "Um Huzaifa / Mohsin", "supervisor": "Abu Al-Majd", "cur": "ZAR", "native": 1004328.35, "fx": 0.05981, "note": "19 Mar opening transfer adjusted by -100,000 reconciliation 1 Oct"},
    {"id": "sa_yp_box", "num": 4, "name": "Yusuf Patel's Box (YP)", "name_ar": "صندوق يوسف باتيل Yusuf Patel", "group": "South Africa", "type": "cash_safe", "holder": "Yusuf Patel", "supervisor": "Abu Al-Majd", "cur": "ZAR", "native": 322235.05, "fx": 0.05981, "note": ""},
    {"id": "sa_fnb_1", "num": 1, "name": "FNB Current Account 1", "name_ar": "SA-ZAR (FNB) 1", "group": "South Africa", "type": "bank", "holder": "Um Huzaifa", "supervisor": "Abu Al-Majd", "cur": "ZAR", "native": 273645.63, "fx": 0.05981, "note": "Primary South Africa bank account"},
    {"id": "sa_fnb_2", "num": 2, "name": "FNB Current Account 2", "name_ar": "SA-ZAR (FNB) 2", "group": "South Africa", "type": "bank", "holder": "Um Huzaifa", "supervisor": "Abu Al-Majd", "cur": "ZAR", "native": 16425.15, "fx": 0.05981, "note": ""},
    {"id": "sa_fnb_call", "num": 3, "name": "FNB Call Account", "name_ar": "Call Account", "group": "South Africa", "type": "bank", "holder": "Mohsin / Um Huzaifa", "supervisor": "Abu Al-Majd", "cur": "ZAR", "native": 10040.35, "fx": 0.05981, "note": ""},
    {"id": "sa_z_crypto", "num": 4, "name": "Z Crypto Wallet (Mohsin)", "name_ar": "Z Crypto", "group": "South Africa", "type": "crypto", "holder": "Mohsin", "supervisor": "Abu Al-Majd", "cur": "USDT", "native": 12500.00, "fx": 1.0, "note": "R211,250 (25 Sep) + R21,000 (6 Oct) converted; FX difference to Transfer fees"},

    # Afghanistan
    {"id": "af_abrar_box", "num": 10, "name": "Afghanistan Box (Abrar)", "name_ar": "صندوق أفغانستان", "group": "Afghanistan", "type": "cash_safe", "holder": "Abrar", "supervisor": "Homam", "cur": "USD", "native": 114706.00, "fx": 1.0, "note": "Includes Human Aid's second amanah of $99,000"},

    # Gaza & Egypt
    {"id": "gz_ajjour", "num": 36, "name": "Gaza Field (Ajjour)", "name_ar": "غزة محمد عجور", "group": "Gaza & Egypt", "type": "cash_safe", "holder": "Mohammed Ajjour", "supervisor": "Abu Al-Majd", "cur": "USD", "native": 0.0, "fx": 1.0, "note": "Ajjour treated as implementing partner from Oct; no cash held"},
    {"id": "eg_hosari_usd", "num": 38, "name": "Egypt Field Box (Hosari USD)", "name_ar": "مصر محمد الحصري دولار", "group": "Gaza & Egypt", "type": "cash_safe", "holder": "Mohamed El-Hosari", "supervisor": "Abu Al-Majd", "cur": "USD", "native": -3401.50, "fx": 1.0, "note": "USD box negative = owed by us to Hosari (-2,905 at 30 Sep)"},
    {"id": "eg_hosari_egp", "num": 38, "name": "Egypt Field Box (Hosari EGP)", "name_ar": "مصر محمد الحصري جنيه", "group": "Gaza & Egypt", "type": "cash_safe", "holder": "Mohamed El-Hosari", "supervisor": "Abu Al-Majd", "cur": "EGP", "native": 0.0, "fx": 0.020, "note": ""},

    # Platforms / Clearing
    {"id": "pl_madina", "num": 39, "name": "Madina Platform Clearing", "name_ar": "Platform Madina", "group": "Platforms", "type": "platform", "holder": "Abu Hanzala / Hosari", "supervisor": "Abu Al-Majd", "cur": "USD", "native": 47383.66, "fx": 1.0, "note": "Osman 4 Nov confirmed balance (sheet showed 57,383.66)"},
    {"id": "pl_launchgood", "num": 7, "name": "LaunchGood Clearing", "name_ar": "LG Launchgood", "group": "Platforms", "type": "platform", "holder": "Khairia", "supervisor": "Homam", "cur": "GBP", "native": 27619.37, "fx": 1.33, "note": "Payout #35970 (4 Nov) less £325.38 donated 1-4 Nov"},
    {"id": "pl_givebrite", "num": 40, "name": "GiveBrite Clearing", "name_ar": "Givebrite", "group": "Platforms", "type": "platform", "holder": "Yunus", "supervisor": "Homam", "cur": "GBP", "native": 0.0, "fx": 1.33, "note": "Settles directly into Lloyds Bank; £69,890.30 uncoded payouts pending breakdown"},
    {"id": "pl_stripe", "num": 41, "name": "Stripe Clearing", "name_ar": "Stripe", "group": "Platforms", "type": "platform", "holder": "Yunus", "supervisor": "Homam", "cur": "GBP", "native": 0.0, "fx": 1.33, "note": "Website card donations settled to Lloyds"},
    {"id": "pl_aps", "num": 42, "name": "APS Direct Debit Clearing", "name_ar": "APS", "group": "Platforms", "type": "platform", "holder": "Yunus", "supervisor": "Homam", "cur": "GBP", "native": 0.0, "fx": 1.33, "note": "Recurring direct debits settled to Lloyds"},
]

# Explicit mapping from (file, tab) in ledger.csv to canonical account_id
FILE_TAB_TO_ACCOUNT: Dict[Tuple[str, str], str] = {
    ("Abdulkadir Reserve Jul & Aug.xlsx", "Madina"): "sy_emergency_reserve",
    ("AnNahda_AJ - Jul & Aug.xlsx", "AJ Cash"): "uk_aj_box",
    ("AnNahda_AJ_Oct2026.xlsx", "AJ Cash"): "uk_aj_box",
    ("AnNahda_AJ_Sep2026.xlsx", "AJ Cash"): "uk_aj_box",
    ("AnNahda_Afghanistan_Oct2026.xlsx", "October 2026"): "af_abrar_box",
    ("AnNahda_Afghanistan_Sep2026 (1).xlsx", "Afghanistan"): "af_abrar_box",
    ("AnNahda_Ayman_Oct2026.xlsx", "GBP"): "tr_ziraat_gbp",
    ("AnNahda_Ayman_Oct2026.xlsx", "TL"): "tr_ziraat_don_try",
    ("AnNahda_Ayman_Oct2026.xlsx", "USD"): "tr_ziraat_usd",
    ("AnNahda_Ayman_Sep2026.xlsx", "IQ Ziraat Donation TL"): "tr_ziraat_don_try",
    ("AnNahda_Ayman_Sep2026.xlsx", "IQ Ziraat Donation USD"): "tr_ziraat_don_usd",
    ("AnNahda_Ayman_Sep2026.xlsx", "IQ Ziraat TL"): "tr_ziraat_try",
    ("AnNahda_Ayman_Sep2026.xlsx", "IQ Ziraat USD"): "tr_ziraat_usd",
    ("AnNahda_Ayman_Sep2026.xlsx", "NISVA"): "tr_nisva",
    ("AnNahda_Egypt_Sep2026.xlsx", "EG EGP Cash"): "eg_hosari_egp",
    ("AnNahda_Egypt_Sep2026.xlsx", "EG USD Cash"): "eg_hosari_usd",
    ("AnNahda_FNB2_Oct2026.xlsx", "October 2026"): "sa_fnb_2",
    ("AnNahda_FNB2_Sep2026_Final.xlsx", "FNB2"): "sa_fnb_2",
    ("AnNahda_Hanzala Jul & Aug.xlsx", "A.H Crypto"): "tr_hanzala_crypto",
    ("AnNahda_Hanzala Jul & Aug.xlsx", "A.H Euro Cash"): "tr_hanzala_eur",
    ("AnNahda_Hanzala Jul & Aug.xlsx", "A.H GBP Cash"): "tr_hanzala_gbp",
    ("AnNahda_Hanzala Jul & Aug.xlsx", "A.H GBP UK"): "tr_hanzala_gbp",
    ("AnNahda_Hanzala Jul & Aug.xlsx", "A.H TL Cash"): "tr_hanzala_try",
    ("AnNahda_Hanzala Jul & Aug.xlsx", "A.H USD Cash"): "tr_hanzala_usd",
    ("AnNahda_Hanzala_Oct2026.xlsx", "Crypto"): "tr_hanzala_crypto",
    ("AnNahda_Hanzala_Oct2026.xlsx", "GBP UK"): "tr_hanzala_gbp",
    ("AnNahda_Hanzala_Oct2026.xlsx", "TL Cash"): "tr_hanzala_try",
    ("AnNahda_Hanzala_Oct2026.xlsx", "USD Cash"): "tr_hanzala_usd",
    ("AnNahda_Hanzala_Sep2026_Final.xlsx", "A.H Crypto"): "tr_hanzala_crypto",
    ("AnNahda_Hanzala_Sep2026_Final.xlsx", "A.H GBP UK"): "tr_hanzala_gbp",
    ("AnNahda_Hanzala_Sep2026_Final.xlsx", "A.H TL Cash"): "tr_hanzala_try",
    ("AnNahda_Hanzala_Sep2026_Final.xlsx", "A.H USD Cash"): "tr_hanzala_usd",
    ("AnNahda_Hosari.xlsx", "Madina"): "pl_madina",
    ("AnNahda_Hosari_Oct2026.xlsx", "Hosari-USD"): "eg_hosari_usd",
    ("AnNahda_Hosari_Oct2026.xlsx", "Madina"): "pl_madina",
    ("AnNahda_Humam_Oct2026.xlsx", "October 2026"): "sy_humam_box",
    ("AnNahda_Humam_Sep2026.xlsx", "H.S"): "sy_humam_box",
    ("AnNahda_Lloyds_Sep2026.xlsx", "Lloyds"): "uk_lloyds",
    ("AnNahda_Mohsin_Oct2026.xlsx", "Call Account"): "sa_fnb_call",
    ("AnNahda_Mohsin_Oct2026.xlsx", "Investment"): "sa_fnb_inv",
    ("AnNahda_Mohsin_Sep2026.xlsx", "Call Account"): "sa_fnb_call",
    ("AnNahda_Mohsin_Sep2026.xlsx", "Investment"): "sa_fnb_inv",
    ("AnNahda_NISVA_Oct2026.xlsx", "NISVA"): "tr_nisva",
    ("AnNahda_SA_FNB_Oct2026.xlsx", "October 2026"): "sa_fnb_1",
    ("AnNahda_SA_FNB_Sep2026.xlsx", "SA FNB Bank"): "sa_fnb_1",
    ("AnNahda_SY-CH-26-TS_Oct2026.xlsx", "October 2026"): "sy_idleb_box",
    ("AnNahda_SY-CH-26-TS_Sep2026.xlsx", "SY-CH-26-TS"): "sy_idleb_box",
    ("AnNahda_UK-CH-25-OA_Sep2026.xlsx", "UK-CH-25-OA"): "uk_osman_box",
    ("AnNahda_Um_Huzaifa - July & Aug.xlsx", "FNB1"): "sa_fnb_1",
    ("AnNahda_Um_Huzaifa - July & Aug.xlsx", "FNB2"): "sa_fnb_2",
    ("AnNahda_YP_Jul-Sep2026_Adjusted.xlsx", "Y.P"): "sa_yp_box",
    ("Hosari Jul & Aug.xlsx", "EGP"): "eg_hosari_egp",
    ("Hosari Jul & Aug.xlsx", "USD"): "eg_hosari_usd",
    ("IQRA Ziraat Jul & Aug.xlsx", "IQ Ziraat Donation TL"): "tr_ziraat_don_try",
    ("IQRA Ziraat Jul & Aug.xlsx", "IQ Ziraat TL"): "tr_ziraat_try",
    ("IQRA Ziraat Jul & Aug.xlsx", "IQ Ziraat USD"): "tr_ziraat_usd",
    ("Lloyd July & Aug.xlsx", "Lloyds"): "uk_lloyds",
    ("Madina Jul & Aug.xlsx", "Madina"): "pl_madina",
    ("Mohsin Jul & Aug.xlsx", "Call Account"): "sa_fnb_call",
    ("Mohsin Jul & Aug.xlsx", "Investment"): "sa_fnb_inv",
    ("NISVA.xlsx", "NISVA"): "tr_nisva",
    ("Rethink Finance Sheet Jul &  Aug.xlsx", "APS"): "pl_aps",
    ("Rethink Finance Sheet Jul &  Aug.xlsx", "Afghanistan"): "af_abrar_box",
    ("Rethink Finance Sheet Jul &  Aug.xlsx", "Coop"): "uk_coop",
    ("Rethink Finance Sheet Jul &  Aug.xlsx", "GB"): "pl_givebrite",
    ("Rethink Finance Sheet Jul &  Aug.xlsx", "GiveBrite"): "pl_givebrite",
    ("Rethink Finance Sheet Jul &  Aug.xlsx", "LaunchGood"): "pl_launchgood",
    ("Rethink Finance Sheet Jul &  Aug.xlsx", "Stripe"): "pl_stripe",
    ("Rethink Finance Sheet Oct2026.xlsx", "APS"): "pl_aps",
    ("Rethink Finance Sheet Oct2026.xlsx", "Coop"): "uk_coop",
    ("Rethink Finance Sheet Oct2026.xlsx", "GiveBrite"): "pl_givebrite",
    ("Rethink Finance Sheet Oct2026.xlsx", "LaunchGood"): "pl_launchgood",
    ("Rethink Finance Sheet Oct2026.xlsx", "Lloyd"): "uk_lloyds",
    ("Rethink Finance Sheet Oct2026.xlsx", "Stripe"): "pl_stripe",
    ("Rethink Finance Sheet.xlsx", "APS"): "pl_aps",
    ("Rethink Finance Sheet.xlsx", "GB"): "pl_givebrite",
    ("Rethink Finance Sheet.xlsx", "GiveBrite"): "pl_givebrite",
    ("Rethink Finance Sheet.xlsx", "LaunchGood"): "pl_launchgood",
    ("Rethink Finance Sheet.xlsx", "Stripe"): "pl_stripe",
    ("Rethink_Coop_Sep2026.xlsx", "Coop"): "uk_coop",
    ("SY-CH-26-TS Jul & Aug.xlsx", "2026"): "sy_idleb_box",
    ("TR-CH-26-HS - Jul & Aug.xlsx", "2026"): "sy_humam_box",
    ("UK-CH-25-OA   Jul & Aug.xlsx", "2026"): "uk_osman_box",
    ("UMUT_Oct2026.xlsx", "UMUT TL"): "tr_umut_try",
    ("UMUT_Sep2026.xlsx", "UMUT TL"): "tr_umut_try",
    ("UMUT_Sep2026.xlsx", "UMUT USD"): "tr_umut_usd",
}

ACCOUNT_ALIASES: List[Tuple[str, str, str]] = [
    ("Lloyd", "uk_lloyds", "bank_transfer"),
    ("Llyods", "uk_lloyds", "bank_transfer"),
    ("Llyod", "uk_lloyds", "bank_transfer"),
    ("LLoyd", "uk_lloyds", "bank_transfer"),
    ("RT", "uk_lloyds", "bank_transfer"),
    ("GiveBrite", "pl_givebrite", "platform_payout"),
    ("Givebrite", "pl_givebrite", "platform_payout"),
    ("GB", "pl_givebrite", "platform_payout"),
    ("LaunchGood", "pl_launchgood", "platform_payout"),
    ("Launchgood", "pl_launchgood", "platform_payout"),
    ("Stripe", "pl_stripe", "platform_payout"),
    ("stripe", "pl_stripe", "platform_payout"),
    ("APS", "pl_aps", "platform_payout"),
    ("Madina", "pl_madina", "platform_payout"),
    ("madina", "pl_madina", "platform_payout"),
    ("NISVA", "tr_nisva", "bank_transfer"),
    ("NISVA own", "tr_nisva", "bank_transfer"),
    ("IQRA TR", "tr_ziraat_usd", "bank_transfer"),
    ("Ziraat Bank", "tr_ziraat_usd", "bank_transfer"),
    ("Umut Insaasi", "tr_umut_try", "bank_transfer"),
    ("Umat inşası", "tr_umut_try", "bank_transfer"),
    ("UMUT İnşası", "tr_umut_try", "bank_transfer"),
    ("H.S", "sy_humam_box", "field_safe"),
    ("Humam", "sy_humam_box", "field_safe"),
    ("Aleppo Finance", "sy_azaz_box", "field_safe"),
    ("Aleppo Finace", "sy_azaz_box", "field_safe"),
    ("Idleb Finance", "sy_idleb_box", "field_safe"),
    ("idleb finance", "sy_idleb_box", "field_safe"),
    ("Damscus Finance", "sy_damascus_box", "field_safe"),
    ("Abu Husam", "sy_abuhusam_box", "field_safe"),
    ("Abdulkadir Reserve", "sy_emergency_reserve", "field_safe"),
    ("Abrar", "af_abrar_box", "field_safe"),
    ("Ajjour", "gz_ajjour", "field_safe"),
    ("Ajjur", "gz_ajjour", "field_safe"),
    ("Gaza Finance", "gz_ajjour", "field_safe"),
    ("Egypt", "eg_hosari_usd", "field_safe"),
    ("FNB1", "sa_fnb_1", "bank_transfer"),
    ("FNB 1", "sa_fnb_1", "bank_transfer"),
    ("Iqra SA", "sa_fnb_1", "bank_transfer"),
    ("IQRA SA", "sa_fnb_1", "bank_transfer"),
    ("ZAR Account", "sa_fnb_1", "bank_transfer"),
    ("FNB 2 Cape Town", "sa_fnb_2", "bank_transfer"),
    ("Investment Account", "sa_fnb_inv", "bank_transfer"),
    ("transfer to investment acc", "sa_fnb_inv", "bank_transfer"),
    ("Z Crypto", "sa_z_crypto", "fx_exchange"),
    ("A.H Crypto", "tr_hanzala_crypto", "fx_exchange"),
    ("A.H Crypto transfer", "tr_hanzala_crypto", "fx_exchange"),
    ("A.H", "tr_hanzala_usd", "field_safe"),
    ("A.H USD", "tr_hanzala_usd", "field_safe"),
    ("O.A", "uk_osman_box", "field_safe"),
    ("AJ", "uk_aj_box", "field_safe"),
    ("T.S", "sy_idleb_box", "field_safe"),
]

ALIAS_LOOKUP = {alias.lower(): acc_id for alias, acc_id, _ in ACCOUNT_ALIASES}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def _is_overhead_pot(name: str, program: str) -> int:
    nl = (name or "").lower()
    pl = (program or "").lower()
    if pl in ("admin", "management", "gift aid", "intrest money"):
        return 1
    if any(kw in nl for kw in OVERHEAD_KEYWORDS):
        return 1
    return 0


def ensure_treasury_schema(conn: sqlite3.Connection) -> None:
    """Create Treasury & Pots tables and indexes if they do not exist."""
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS treasury_accounts (
            id TEXT PRIMARY KEY,
            account_number INTEGER,
            name TEXT NOT NULL,
            name_ar TEXT,
            group_name TEXT NOT NULL,
            account_type TEXT NOT NULL,
            holder TEXT,
            supervisor TEXT,
            currency TEXT NOT NULL,
            opening_balance_native REAL DEFAULT 0,
            current_balance_native REAL DEFAULT 0,
            reconciled_usd REAL DEFAULT 0,
            reconciled_fx_rate REAL DEFAULT 1.0,
            note TEXT,
            company_id TEXT DEFAULT 'rethink',
            is_active INTEGER DEFAULT 1,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS treasury_trust_amanahs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            holder TEXT NOT NULL,
            account_id TEXT,
            native_amount REAL,
            currency TEXT DEFAULT 'USD',
            usd_amount REAL NOT NULL,
            note TEXT,
            as_of_date TEXT DEFAULT '2026-10-31'
        );

        CREATE TABLE IF NOT EXISTS treasury_receivables (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            native_amount REAL,
            currency TEXT DEFAULT 'USD',
            usd_amount REAL NOT NULL,
            is_included_in_net_position INTEGER DEFAULT 1,
            note TEXT,
            as_of_date TEXT DEFAULT '2026-10-31'
        );

        CREATE TABLE IF NOT EXISTS treasury_account_aliases (
            alias TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            transfer_type TEXT
        );

        CREATE TABLE IF NOT EXISTS treasury_pots (
            id TEXT PRIMARY KEY,
            code TEXT,
            fund_num INTEGER,
            name TEXT NOT NULL,
            portfolio TEXT NOT NULL,
            program TEXT,
            country TEXT,
            pool TEXT NOT NULL,
            is_overhead INTEGER DEFAULT 0,
            opening_balance_usd REAL DEFAULT 0,
            fy_raised_usd REAL DEFAULT 0,
            fy_expenses_usd REAL DEFAULT 0,
            bal_jun_usd REAL DEFAULT 0,
            inc_jul_oct_usd REAL DEFAULT 0,
            exp_jul_oct_usd REAL DEFAULT 0,
            current_balance_usd REAL DEFAULT 0,
            months_json TEXT,
            notes_json TEXT,
            company_id TEXT DEFAULT 'rethink',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS treasury_pot_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pot_id TEXT NOT NULL,
            line_date TEXT,
            line_month TEXT,
            source TEXT,
            description TEXT,
            native_note TEXT,
            amount_usd REAL NOT NULL,
            line_kind TEXT,
            created_by TEXT DEFAULT 'seed_oct31',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS treasury_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_date TEXT,
            tx_month TEXT,
            account_id TEXT NOT NULL,
            source_file TEXT,
            source_tab TEXT,
            source_row INTEGER,
            description TEXT,
            currency TEXT,
            amount_native REAL NOT NULL,
            amount_usd REAL NOT NULL,
            fx_rate REAL DEFAULT 1.0,
            kind TEXT NOT NULL,
            category TEXT,
            counterparty_account_id TEXT,
            allocation TEXT,
            pot_id TEXT,
            zakat_status TEXT,
            country TEXT,
            person TEXT,
            flags TEXT,
            linked_transfer_group TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_ttx_account ON treasury_transactions(account_id);
        CREATE INDEX IF NOT EXISTS idx_ttx_kind ON treasury_transactions(kind);
        CREATE INDEX IF NOT EXISTS idx_ttx_month ON treasury_transactions(tx_month);
        CREATE INDEX IF NOT EXISTS idx_tpl_pot ON treasury_pot_lines(pot_id);
        CREATE INDEX IF NOT EXISTS idx_tpots_portfolio ON treasury_pots(portfolio);
        CREATE INDEX IF NOT EXISTS idx_tpots_country ON treasury_pots(country);
    """)
    conn.commit()


def seed_treasury_data(
    db_path: str = DEFAULT_DB_PATH,
    archive_dir: str = DEFAULT_ARCHIVE_DIR,
    force_reseed: bool = False,
) -> Dict[str, int]:
    """Seed treasury tables from archive JSON/CSV. Idempotent unless force_reseed=True."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    ensure_treasury_schema(conn)
    cur = conn.cursor()

    existing_accounts = cur.execute("SELECT COUNT(*) FROM treasury_accounts").fetchone()[0]
    if existing_accounts > 0 and not force_reseed:
        counts = {
            "accounts": existing_accounts,
            "pots": cur.execute("SELECT COUNT(*) FROM treasury_pots").fetchone()[0],
            "transactions": cur.execute("SELECT COUNT(*) FROM treasury_transactions").fetchone()[0],
        }
        conn.close()
        return counts

    if not os.path.exists(archive_dir):
        conn.close()
        return {"accounts": 0, "pots": 0, "transactions": 0}

    with open(os.path.join(archive_dir, "fund_position.json"), encoding="utf-8") as f:
        fp = json.load(f)

    # Clear existing seeded rows when force_reseed is requested
    for tbl in (
        "treasury_accounts",
        "treasury_trust_amanahs",
        "treasury_receivables",
        "treasury_account_aliases",
        "treasury_pots",
        "treasury_pot_lines",
        "treasury_transactions",
    ):
        cur.execute(f"DELETE FROM {tbl}")

    # 1. Seed Accounts
    for acc in BASELINE_ACCOUNTS:
        usd_val = round(float(acc["native"]) * float(acc["fx"]), 2)
        cur.execute(
            """
            INSERT INTO treasury_accounts (
                id, account_number, name, name_ar, group_name, account_type,
                holder, supervisor, currency, opening_balance_native,
                current_balance_native, reconciled_usd, reconciled_fx_rate, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                acc["id"], acc["num"], acc["name"], acc["name_ar"], acc["group"], acc["type"],
                acc["holder"], acc["supervisor"], acc["cur"], acc["native"],
                acc["native"], usd_val, acc["fx"], acc["note"],
            ),
        )

    # 2. Seed Trust Amanahs
    trust_account_map = {
        "Human Aid": ("af_abrar_box", 99000.0, "USD"),
        "OGN": ("sy_humam_box", 3321.0, "USD"),
        "Sajjad": ("sy_humam_box", 7580.0, "USD"),
        "Abdul Rahim": ("uk_lloyds", 2500.0, "GBP"),
    }
    for tr in fp["cash"].get("trust", []):
        acc_id, nat_amt, cur_code = trust_account_map.get(tr["holder"], ("", tr["usd"], "USD"))
        cur.execute(
            """
            INSERT INTO treasury_trust_amanahs (holder, account_id, native_amount, currency, usd_amount, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tr["holder"], acc_id, nat_amt, cur_code, tr["usd"], tr["note"]),
        )

    # 3. Seed Receivables
    rec = fp.get("receivables", {})
    rec_rows = [
        ("rec_one_nation", "One Nation Partner Settlement", "partner_settlement", rec.get("one_nation_gbp", 174240.77), "GBP", rec.get("one_nation", 231740.22), 1, "Joint deployments settlement due per Osman's 31 Oct sheet (~£178,170 by date rule; £3,929 variance under review)."),
        ("rec_staff_advances", "Syria Work & Salary Advances", "staff_advance", rec.get("staff_advances", 63152.38), "USD", rec.get("staff_advances", 63152.38), 1, "Operational & salary advances held by Syria field coordinators pending expense receipts."),
        ("rec_syria_amanah", "Syria Amanah Paid on Behalf of Others", "amanah_receivable", rec.get("syria_amanah_receivable", 28632.61), "USD", rec.get("syria_amanah_receivable", 28632.61), 1, "Abu Ibrahim $19,764 + Loulou nursery $7,200 + Abdul Rahim $4,117.50 + Nagena $338 + Abu Husam $86.49 less Bilal $9,232."),
        ("rec_turkey_intermediary", "Turkey Intermediary In-Transit", "in_transit", rec.get("turkey_intermediary", 0.0), "USD", rec.get("turkey_intermediary", 0.0), 1, "All in-transit AMAL KOY ($9,090) and crypto ($99,800 -> $99,000) arrived in October."),
        ("accrued_syria_liabilities", "Syria Accrued Salaries & Sponsorships (Memo)", "accrued_liability", rec.get("syria_accrued_liabilities", 148246.80), "USD", rec.get("syria_accrued_liabilities", 148246.80), 0, "Cash-basis memo only: Syria salaries $99,054 + sponsorships $49,192.80 accrued at 31 Oct."),
    ]
    cur.executemany(
        """
        INSERT INTO treasury_receivables (id, name, category, native_amount, currency, usd_amount, is_included_in_net_position, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rec_rows,
    )

    # 4. Seed Account Aliases
    cur.executemany(
        "INSERT OR REPLACE INTO treasury_account_aliases (alias, account_id, transfer_type) VALUES (?, ?, ?)",
        ACCOUNT_ALIASES,
    )

    # 5. Seed Pots & Itemized Pot Lines
    pot_id_by_name_country_pool: Dict[Tuple[str, str, str], str] = {}
    pot_count = 0
    for idx, fn in enumerate(fp.get("funds", []), start=1):
        code_raw = str(fn.get("code") or "").strip()
        slug = _slugify(f"{code_raw}_{fn.get('name')}_{fn.get('country')}_{fn.get('pool')}")
        pot_id = f"pot_{idx:03d}_{slug[:48]}"
        is_ovh = _is_overhead_pot(fn.get("name", ""), fn.get("program", ""))

        cur.execute(
            """
            INSERT INTO treasury_pots (
                id, code, fund_num, name, portfolio, program, country, pool, is_overhead,
                opening_balance_usd, fy_raised_usd, fy_expenses_usd, bal_jun_usd,
                inc_jul_oct_usd, exp_jul_oct_usd, current_balance_usd, months_json, notes_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pot_id,
                code_raw,
                fn.get("num"),
                fn.get("name", ""),
                fn.get("portfolio", "General"),
                fn.get("program", "General"),
                fn.get("country", "Unallocated"),
                fn.get("pool", "Non-Zakat"),
                is_ovh,
                float(fn.get("opening") or 0.0),
                float(fn.get("raised") or 0.0),
                float(fn.get("expenses") or 0.0),
                float(fn.get("bal_jun") or 0.0),
                float(fn.get("inc78") or 0.0),
                float(fn.get("exp78") or 0.0),
                float(fn.get("balance") or 0.0),
                json.dumps(fn.get("months") or {}),
                json.dumps(fn.get("notes") or []),
            ),
        )
        pot_id_by_name_country_pool[
            ((fn.get("name") or "").lower(), (fn.get("country") or "").lower(), (fn.get("pool") or "").lower())
        ] = pot_id

        for ln in fn.get("lines") or []:
            d_str = str(ln.get("d") or "")
            m_str = d_str[:7] if re.match(r"^\d{4}-\d{2}", d_str) else d_str
            cur.execute(
                """
                INSERT INTO treasury_pot_lines (
                    pot_id, line_date, line_month, source, description, native_note, amount_usd, line_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pot_id,
                    d_str,
                    m_str,
                    ln.get("s", ""),
                    ln.get("t", ""),
                    ln.get("n", ""),
                    float(ln.get("u") or 0.0),
                    ln.get("k", "ja"),
                ),
            )
        pot_count += 1

    # 6. Seed Ledger Transactions from ledger.csv
    tx_rows = []
    ledger_path = os.path.join(archive_dir, "ledger.csv")
    with open(ledger_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sfile = row.get("file", "")
            stab = row.get("tab", "")
            acc_id = FILE_TAB_TO_ACCOUNT.get((sfile, stab), "uk_lloyds")
            kind = row.get("kind", "uncoded") or "uncoded"
            cat = row.get("category") or ""
            cat_l = cat.strip().lower()
            counterparty = ALIAS_LOOKUP.get(cat_l) if kind == "internal" else None

            tx_date = row.get("date") or ""
            tx_month = tx_date[:7] if re.match(r"^\d{4}-\d{2}", tx_date) else "undated"
            amt_nat = float(row.get("amount_native") or 0.0)
            amt_usd = float(row.get("usd") or 0.0)
            fx_rate = round(abs(amt_usd / amt_nat), 6) if amt_nat else 1.0

            alloc = row.get("allocation") or ""
            ctry = row.get("country") or ""
            zakat = row.get("zakat") or ""
            pool_key = "zakat" if "zakat" in zakat.lower() and "not" not in zakat.lower() else "non-zakat"
            pot_id = pot_id_by_name_country_pool.get((alloc.lower(), ctry.lower(), pool_key))

            tx_rows.append((
                tx_date,
                tx_month,
                acc_id,
                sfile,
                stab,
                int(float(row.get("row") or 0)),
                row.get("description") or "",
                row.get("currency") or "USD",
                amt_nat,
                amt_usd,
                fx_rate,
                kind,
                cat,
                counterparty,
                alloc,
                pot_id,
                zakat,
                ctry,
                row.get("person") or "",
                row.get("flags") or "",
            ))

    cur.executemany(
        """
        INSERT INTO treasury_transactions (
            tx_date, tx_month, account_id, source_file, source_tab, source_row,
            description, currency, amount_native, amount_usd, fx_rate, kind,
            category, counterparty_account_id, allocation, pot_id, zakat_status,
            country, person, flags
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tx_rows,
    )

    conn.commit()
    result = {"accounts": len(BASELINE_ACCOUNTS), "pots": pot_count, "transactions": len(tx_rows)}
    conn.close()
    return result


def ensure_treasury_extras_schema(conn: sqlite3.Connection) -> None:
    """Tables for the fund-position workflow: corrections register, confirmation queue, source freshness,
    month-end balance history and the CRM activity log (every write, reversible)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS treasury_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adj_date TEXT,
            from_fund TEXT, from_country TEXT, from_pool TEXT,
            to_fund TEXT, to_country TEXT, to_pool TEXT,
            usd REAL NOT NULL,
            adj_type TEXT,
            approved_by TEXT,
            note TEXT,
            applied_to TEXT,
            source TEXT DEFAULT 'archive',
            activity_id INTEGER,
            company_id TEXT DEFAULT 'rethink',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS treasury_confirm_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT NOT NULL,
            usd REAL,
            status TEXT DEFAULT 'open',
            resolution TEXT,
            resolved_by TEXT,
            resolved_at TEXT,
            company_id TEXT DEFAULT 'rethink'
        );
        CREATE TABLE IF NOT EXISTS treasury_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file TEXT, tab TEXT, lines INTEGER,
            first_date TEXT, last_date TEXT,
            inc_usd REAL, exp_usd REAL, internal_usd REAL,
            account_id TEXT,
            company_id TEXT DEFAULT 'rethink'
        );
        CREATE TABLE IF NOT EXISTS treasury_balance_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            as_of TEXT,
            old_native REAL, new_native REAL, fx_rate REAL,
            note TEXT, actor TEXT,
            activity_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS treasury_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP,
            actor TEXT,
            action TEXT NOT NULL,
            summary TEXT,
            amount_usd REAL,
            payload_json TEXT,
            undo_json TEXT,
            reversed_by INTEGER,
            reversal_of INTEGER,
            company_id TEXT DEFAULT 'rethink'
        );
        CREATE TABLE IF NOT EXISTS treasury_approvals (
            id TEXT PRIMARY KEY,
            company_id TEXT DEFAULT 'rethink',
            transfer_type TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            amount_usd REAL DEFAULT 0.0,
            amount_native REAL DEFAULT 0.0,
            currency TEXT DEFAULT 'USD',
            source_ref TEXT,
            source_name TEXT,
            destination_ref TEXT,
            destination_name TEXT,
            details_json TEXT,
            requested_by TEXT NOT NULL,
            requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_by TEXT,
            reviewed_at TEXT,
            rejection_reason TEXT,
            execution_result_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tadj_date ON treasury_adjustments(adj_date);
        CREATE INDEX IF NOT EXISTS idx_tact_ts ON treasury_activity(ts);
        CREATE INDEX IF NOT EXISTS idx_tap_status ON treasury_approvals(status);
        CREATE INDEX IF NOT EXISTS idx_tap_comp ON treasury_approvals(company_id);
    """)
    for col, ddl in (("is_active", "INTEGER DEFAULT 1"), ("settled_at", "TEXT"), ("created_by", "TEXT")):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(treasury_trust_amanahs)")}
        if col not in cols:
            conn.execute(f"ALTER TABLE treasury_trust_amanahs ADD COLUMN {col} {ddl}")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(treasury_receivables)")}
    if "is_active" not in cols:
        conn.execute("ALTER TABLE treasury_receivables ADD COLUMN is_active INTEGER DEFAULT 1")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(treasury_pots)")}
    if "is_active" not in cols:
        conn.execute("ALTER TABLE treasury_pots ADD COLUMN is_active INTEGER DEFAULT 1")
    conn.commit()


def seed_treasury_extras(db_path: str = DEFAULT_DB_PATH, archive_dir: str = DEFAULT_ARCHIVE_DIR) -> Dict[str, int]:
    """Fill the corrections register, confirmation queue and source list from the archive - only tables that are
    still empty, so nothing recorded in the CRM is ever overwritten."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        ensure_treasury_schema(conn)
        ensure_treasury_extras_schema(conn)
        path = os.path.join(archive_dir, "fund_position.json")
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            fp = json.load(f)
        out: Dict[str, int] = {}
        cur = conn.cursor()
        if cur.execute("SELECT COUNT(*) FROM treasury_adjustments").fetchone()[0] == 0:
            rows = [(a.get("date"), a.get("from_fund"), a.get("from_country"), a.get("from_pool"), a.get("to_fund"),
                     a.get("to_country"), a.get("to_pool"), float(a.get("usd") or 0), a.get("type"), a.get("approved_by"),
                     a.get("note"), str(a.get("applied_to") or "")) for a in fp.get("adjustments") or []]
            cur.executemany("""INSERT INTO treasury_adjustments (adj_date, from_fund, from_country, from_pool, to_fund,
                to_country, to_pool, usd, adj_type, approved_by, note, applied_to, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'archive')""", rows)
            out["adjustments"] = len(rows)
        if cur.execute("SELECT COUNT(*) FROM treasury_confirm_items").fetchone()[0] == 0:
            rows = [(c.get("item"), float(c.get("usd") or 0)) for c in fp.get("confirm") or []]
            cur.executemany("INSERT INTO treasury_confirm_items (item, usd) VALUES (?, ?)", rows)
            out["confirm"] = len(rows)
        if cur.execute("SELECT COUNT(*) FROM treasury_sources").fetchone()[0] == 0:
            rows = [(s.get("file"), s.get("tab"), int(s.get("lines") or 0), s.get("first"), s.get("last"),
                     float(s.get("inc") or 0), float(s.get("exp") or 0), float(s.get("internal") or 0),
                     FILE_TAB_TO_ACCOUNT.get((s.get("file"), s.get("tab")))) for s in fp.get("sources") or []]
            cur.executemany("""INSERT INTO treasury_sources (file, tab, lines, first_date, last_date, inc_usd, exp_usd,
                internal_usd, account_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
            out["sources"] = len(rows)
        conn.commit()
        return out
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    if "--force" in sys.argv:
        # wipes every treasury table, including transfers and entries recorded in the CRM
        print("Seeded treasury tables:", seed_treasury_data(force_reseed=True))
    else:
        print("Seeded treasury tables:", seed_treasury_data())
    print("Seeded fund-position extras:", seed_treasury_extras())
