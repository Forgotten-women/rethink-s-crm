import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import bcrypt
from jose import JWTError, jwt

from config.settings import LOCAL_DB_PATH, SUPABASE_KEY, SUPABASE_URL

# JWT Configuration
JWT_SECRET = os.environ.get("JWT_SECRET") or os.environ.get("APP_SECRET_KEY", "RethinkCharityCRM_SecretKey_2026!")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    """Hashes a password using native secure bcrypt."""
    pw_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")

get_password_hash = hash_password


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a password against bcrypt hash, with backward-compatible
    fallback to legacy unsalted SHA-256 for existing database users.
    """
    if not plain_password or not hashed_password:
        return False

    # Standard Bcrypt Hash ($2b$, $2a$, $2y$)
    if hashed_password.startswith("$2"):
        try:
            pw_bytes = plain_password.encode("utf-8")[:72]
            return bcrypt.checkpw(pw_bytes, hashed_password.encode("utf-8"))
        except Exception:
            return False

    # Legacy SHA-256 fallback
    legacy_hash = hashlib.sha256(plain_password.encode("utf-8")).hexdigest()
    return legacy_hash == hashed_password


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Creates a signed, time-limited JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decodes and cryptographically verifies a JWT access token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


def init_user_db():
    """Ensure users table exists in SQLite database with default accounts and granular permissions."""
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'admin',
                can_edit_donors INTEGER DEFAULT 0,
                can_edit_matrix INTEGER DEFAULT 0,
                can_manage_tags INTEGER DEFAULT 0,
                can_purge_data INTEGER DEFAULT 0,
                allowed_companies TEXT DEFAULT '["ALL"]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        # Check column migration
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        cols = [c[1] for c in cursor.fetchall()]
        for perm_col in ["can_edit_donors", "can_edit_matrix", "can_manage_tags", "can_purge_data"]:
            if perm_col not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {perm_col} INTEGER DEFAULT 0")
                conn.commit()
        if "allowed_companies" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN allowed_companies TEXT DEFAULT '[\"ALL\"]'")
            conn.commit()

        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        if count == 0:
            seed_users = [
                ('superadmin', 'superadmin@analytics.com', hash_password('SuperAdmin@123'), 'super_admin', 1, 1, 1, 1, '["ALL"]'),
                ('admin', 'admin@analytics.com', hash_password('Admin@123'), 'admin', 0, 0, 0, 0, '["ALL"]')
            ]
            cursor.executemany("""
                INSERT INTO users (username, email, password_hash, role, can_edit_donors, can_edit_matrix, can_manage_tags, can_purge_data, allowed_companies)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, seed_users)
            conn.commit()
        else:
            # Ensure superadmin has all permissions
            conn.execute("""
                UPDATE users SET 
                    can_edit_donors = 1,
                    can_edit_matrix = 1,
                    can_manage_tags = 1,
                    can_purge_data = 1
                WHERE role = 'super_admin'
            """)
            conn.commit()

        conn.close()
    except Exception as e:
        print(f"User DB init notice: {e}")


def get_all_users() -> List[Dict[str, Any]]:
    """Returns list of all registered users with their roles, granular permissions, and allowed companies."""
    init_user_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, role, can_edit_donors, can_edit_matrix, can_manage_tags, can_purge_data, allowed_companies, created_at FROM users")
    rows = cursor.fetchall()
    users = []
    for r in rows:
        u = dict(r)
        raw_comp = u.get("allowed_companies") or '["ALL"]'
        try:
            u["allowed_companies"] = json.loads(raw_comp) if isinstance(raw_comp, str) else raw_comp
        except Exception:
            u["allowed_companies"] = ["ALL"]
        users.append(u)
    conn.close()
    return users


def update_user_permissions(email, role, can_edit_donors, can_edit_matrix, can_manage_tags, can_purge_data, allowed_companies=None):
    """Updates user role, granular permissions, and allowed companies in SQLite."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    if allowed_companies is not None:
        comp_json = json.dumps(allowed_companies)
        conn.execute("""
            UPDATE users SET
                role = ?,
                can_edit_donors = ?,
                can_edit_matrix = ?,
                can_manage_tags = ?,
                can_purge_data = ?,
                allowed_companies = ?
            WHERE email = ? OR username = ?
        """, (role, int(can_edit_donors), int(can_edit_matrix), int(can_manage_tags), int(can_purge_data), comp_json, email, email))
    else:
        conn.execute("""
            UPDATE users SET
                role = ?,
                can_edit_donors = ?,
                can_edit_matrix = ?,
                can_manage_tags = ?,
                can_purge_data = ?
            WHERE email = ? OR username = ?
        """, (role, int(can_edit_donors), int(can_edit_matrix), int(can_manage_tags), int(can_purge_data), email, email))
    conn.commit()
    conn.close()
    return True


def authenticate_user(email_or_username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Authenticates user via Supabase Auth API if configured,
    or falls back to local SQLite users table.
    Upgrades legacy SHA-256 password hash to bcrypt automatically on successful login.
    Returns user dict with role ('super_admin' or 'admin') or None.
    """
    if not email_or_username or not password:
        return None

    user_identity = str(email_or_username).strip()

    # 1. Try Supabase Auth API if configured
    if SUPABASE_URL and SUPABASE_KEY:
        import requests
        endpoint = f"{SUPABASE_URL.rstrip('/')}/auth/v1/token?grant_type=password"
        headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
        payload = {"email": user_identity, "password": password}
        try:
            res = requests.post(endpoint, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                user_obj = data.get("user", {})
                user_meta = user_obj.get("user_metadata", {})
                app_meta = user_obj.get("app_metadata", {})
                role = user_meta.get("role") or app_meta.get("role") or "admin"
                
                email = user_obj.get("email", user_identity)
                if "superadmin" in email.lower() or "super" in str(role).lower():
                    role = "super_admin"

                return {
                    "id": user_obj.get("id"),
                    "email": email,
                    "username": email.split("@")[0],
                    "role": role,
                    "provider": "supabase",
                    "access_token": data.get("access_token")
                }
        except Exception as err:
            print(f"Supabase Auth attempt notice: {err}")

    # 2. Local SQLite DB Fallback
    init_user_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username, email, role, can_edit_donors, can_edit_matrix, can_manage_tags, can_purge_data, allowed_companies, password_hash
            FROM users
            WHERE LOWER(email) = LOWER(?) OR LOWER(username) = LOWER(?)
        """, (user_identity, user_identity))
        row = cur.fetchone()
        if row:
            stored_hash = row[9]
            if verify_password(password, stored_hash):
                # Transparent migration: upgrade legacy SHA-256 to modern bcrypt
                if not stored_hash.startswith("$2"):
                    try:
                        new_bcrypt = hash_password(password)
                        cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_bcrypt, row[0]))
                        conn.commit()
                        print(f"[Security] Upgraded user '{row[1]}' password hash to bcrypt.")
                    except Exception as up_err:
                        print(f"[Security Notice] Password hash upgrade notice: {up_err}")

                is_super = (row[3] == "super_admin")
                raw_comp = row[8] if row[8] else '["ALL"]'
                try:
                    allowed_comp = json.loads(raw_comp) if isinstance(raw_comp, str) else raw_comp
                except Exception:
                    allowed_comp = ["ALL"]

                return {
                    "id": row[0],
                    "username": row[1],
                    "email": row[2],
                    "role": row[3],
                    "can_edit_donors": 1 if (is_super or row[4]) else 0,
                    "can_edit_matrix": 1 if (is_super or row[5]) else 0,
                    "can_manage_tags": 1 if (is_super or row[6]) else 0,
                    "can_purge_data": 1 if (is_super or row[7]) else 0,
                    "allowed_companies": allowed_comp,
                    "provider": "local"
                }
    except Exception as e:
        print(f"Local auth error: {e}")
    finally:
        conn.close()

    return None


def get_user_by_identity(user_identity: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves user dict by username, email, or user id.
    """
    if not user_identity or not str(user_identity).strip():
        return None

    ident = str(user_identity).strip()
    init_user_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username, email, role, can_edit_donors, can_edit_matrix, can_manage_tags, can_purge_data, allowed_companies FROM users
            WHERE LOWER(email) = LOWER(?) OR LOWER(username) = LOWER(?)
        """, (ident, ident))
        row = cur.fetchone()
        if row:
            is_super = (row[3] == "super_admin")
            raw_comp = row[8] if row[8] else '["ALL"]'
            try:
                allowed_comp = json.loads(raw_comp) if isinstance(raw_comp, str) else raw_comp
            except Exception:
                allowed_comp = ["ALL"]

            return {
                "id": row[0],
                "username": row[1],
                "email": row[2],
                "role": row[3],
                "can_edit_donors": 1 if (is_super or row[4]) else 0,
                "can_edit_matrix": 1 if (is_super or row[5]) else 0,
                "can_manage_tags": 1 if (is_super or row[6]) else 0,
                "can_purge_data": 1 if (is_super or row[7]) else 0,
                "allowed_companies": allowed_comp,
                "provider": "local"
            }
    except Exception as e:
        print(f"Session restoration notice: {e}")
    finally:
        conn.close()

    return None


def send_password_reset_request(email: str):
    """
    Sends password reset email via Supabase Auth API if configured,
    or provides local recovery guidance.
    """
    if not email or not email.strip():
        return False, "Please enter a valid email address."

    user_email = email.strip()

    if SUPABASE_URL and SUPABASE_KEY:
        import requests
        endpoint = f"{SUPABASE_URL.rstrip('/')}/auth/v1/recover"
        headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
        payload = {"email": user_email}
        try:
            res = requests.post(endpoint, json=payload, headers=headers, timeout=10)
            if res.status_code in [200, 201, 204]:
                return True, f"✅ Password reset recovery link sent to **{user_email}** via Supabase Auth! Please check your inbox."
            else:
                err_msg = res.json().get("msg", "Failed to send reset email.")
                return False, f"Supabase Auth notice: {err_msg}"
        except Exception as err:
            return False, f"Auth service connection error: {err}"

    # Local fallback
    init_user_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        cur = conn.cursor()
        cur.execute("SELECT email, role FROM users WHERE LOWER(email) = LOWER(?) OR LOWER(username) = LOWER(?)", (user_email, user_email))
        row = cur.fetchone()
        if row:
            return True, f"✅ Local recovery verified for **{row[0]}** (`{row[1]}`). Contact your Super Admin to reset password or update database."
        else:
            return False, "No registered account found with that email/username."
    finally:
        conn.close()


def change_user_password(email_or_username: str, current_password: str, new_password: str):
    """
    Changes password for logged in user via Supabase Auth API if configured,
    or via local SQLite users table.
    """
    if not email_or_username or not str(email_or_username).strip():
        return False, "User email/username is missing."
    if not current_password or not new_password:
        return False, "Please fill in both current password and new password."
    if len(new_password.strip()) < 6:
        return False, "New password must be at least 6 characters long."

    user_identity = str(email_or_username).strip()

    # 1. Try Supabase Auth API if configured
    if SUPABASE_URL and SUPABASE_KEY:
        import requests
        token_endpoint = f"{SUPABASE_URL.rstrip('/')}/auth/v1/token?grant_type=password"
        headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
        payload = {"email": user_identity, "password": current_password}
        try:
            res = requests.post(token_endpoint, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                token = res.json().get("access_token")
                user_endpoint = f"{SUPABASE_URL.rstrip('/')}/auth/v1/user"
                update_headers = {
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
                update_payload = {"password": new_password.strip()}
                up_res = requests.put(user_endpoint, json=update_payload, headers=update_headers, timeout=10)
                if up_res.status_code in [200, 201]:
                    return True, "✅ Password updated successfully in Supabase Auth!"
                else:
                    err_msg = up_res.json().get("msg", "Failed to update password.")
                    return False, f"Supabase Auth error: {err_msg}"
            else:
                return False, "❌ Current password is incorrect."
        except Exception as err:
            return False, f"Auth connection error: {err}"

    # 2. Local SQLite DB Fallback
    init_user_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, password_hash FROM users
            WHERE LOWER(email) = LOWER(?) OR LOWER(username) = LOWER(?)
        """, (user_identity, user_identity))
        row = cur.fetchone()
        if not row:
            return False, "❌ User not found."

        user_id, stored_hash = row[0], row[1]
        if not verify_password(current_password, stored_hash):
            return False, "❌ Current password is incorrect."

        new_bcrypt = hash_password(new_password.strip())
        cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_bcrypt, user_id))
        conn.commit()
        return True, "✅ Password changed successfully!"
    except Exception as e:
        return False, f"Database error: {e}"
    finally:
        conn.close()


def edit_user_details(user_id: int, email: str, username: str, password: str = None):
    """
    Allows Super Admin to edit details of a member: email, username, and optionally reset their password.
    """
    init_user_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    try:
        if password and password.strip():
            hashed = hash_password(password.strip())
            cursor.execute("""
                UPDATE users SET email = ?, username = ?, password_hash = ?
                WHERE id = ?
            """, (email.strip(), username.strip(), hashed, user_id))
        else:
            cursor.execute("""
                UPDATE users SET email = ?, username = ?
                WHERE id = ?
            """, (email.strip(), username.strip(), user_id))
        conn.commit()
        return True, "User details updated successfully."
    except sqlite3.IntegrityError:
        return False, "Error: Username or Email already exists."
    except Exception as e:
        return False, f"Database error: {str(e)}"
    finally:
        conn.close()
