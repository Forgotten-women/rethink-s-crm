import os

from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# Absolute path to SQLite DB and Parquet Cache
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DB_PATH = os.path.join(BASE_DIR, "launchgood_donations.db")
PARQUET_PATH = os.path.join(BASE_DIR, "donations_cache.parquet")
PAYOUTS_PARQUET_PATH = os.path.join(BASE_DIR, "payouts_cache.parquet")
PAYSUITE_PAYOUTS_PARQUET_PATH = os.path.join(BASE_DIR, "paysuite_payouts_cache.parquet")
CACHE_DIR = os.path.join(BASE_DIR, "data_cache")
LOGOS_DIR = os.path.join(CACHE_DIR, "logos")
os.makedirs(LOGOS_DIR, exist_ok=True)

# Default Multi-Company Registry
DEFAULT_COMPANIES = {
    "rethink": {"id": "rethink", "name": "Rethink Charity", "short_code": "Rethink", "accent_color": "cyan", "logo_url": ""},
    "iqra": {"id": "iqra", "name": "Iqra", "short_code": "Iqra", "accent_color": "emerald", "logo_url": ""},
}

# Database Connection URLs
LOCAL_DB_URL = f"sqlite:///{LOCAL_DB_PATH}"
raw_db_url = os.environ.get("DATABASE_URL", LOCAL_DB_URL).strip()
if raw_db_url.startswith("postgres://"):
    raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
DATABASE_URL = raw_db_url

# Supabase Auth Configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "").strip()

# Base URL for API & Approval Email Link Generation
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
APPROVAL_EMAIL = os.environ.get("APPROVAL_EMAIL", "office@rethinkcharity.org.uk").strip()

# SMTP Email Configuration
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Rethink Charity CRM").strip()
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", "").strip()

# Session Timeout Configuration
SESSION_TIMEOUT_MINUTES = 15
SESSION_TIMEOUT_SECONDS = SESSION_TIMEOUT_MINUTES * 60

# Country ISO Code Mapping
COUNTRY_ISO_MAP = {
    "GB": "United Kingdom", "UK": "United Kingdom", "GBR": "United Kingdom",
    "US": "United States", "USA": "United States",
    "CA": "Canada", "CAN": "Canada",
    "AU": "Australia", "AUS": "Australia",
    "AE": "United Arab Emirates", "ARE": "United Arab Emirates", "UAE": "United Arab Emirates",
    "SA": "Saudi Arabia", "SAU": "Saudi Arabia",
    "PK": "Pakistan", "PAK": "Pakistan",
    "IN": "India", "IND": "India",
    "MY": "Malaysia", "MYS": "Malaysia",
    "SG": "Singapore", "SGP": "Singapore",
    "NZ": "New Zealand", "NZL": "New Zealand", "DE": "Germany", "DEU": "Germany",
    "FR": "France", "FRA": "France", "NL": "Netherlands", "NLD": "Netherlands",
    "TR": "Turkey", "TUR": "Turkey", "ZA": "South Africa", "ZAF": "South Africa",
    "IE": "Ireland", "IRL": "Ireland", "QA": "Qatar", "QAT": "Qatar",
    "KW": "Kuwait", "KWT": "Kuwait", "BH": "Bahrain", "BHR": "Bahrain",
    "OM": "Oman", "OMN": "Oman", "JO": "Jordan", "JOR": "Jordan",
    "EG": "Egypt", "EGY": "Egypt", "BD": "Bangladesh", "BGD": "Bangladesh"
}

# Plotly Visual Palette
PLOTLY_COLORS = [
    "#06B6D4", # Cyan
    "#8B5CF6", # Purple
    "#10B981", # Emerald
    "#EC4899", # Pink
    "#F59E0B", # Amber
    "#3B82F6", # Blue
    "#14B8A6", # Teal
    "#F43F5E", # Rose
    "#84CC16", # Lime
    "#6366F1"  # Indigo
]

# Donor Tier Ordering
DONOR_TIER_ORDER = [
    "Low End",
    "Medium Low",
    "Medium",
    "High",
    "Super High"
]
