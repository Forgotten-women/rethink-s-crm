import io
import os
import sqlite3
from typing import Optional, List
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config.settings import PARQUET_PATH, LOCAL_DB_PATH, LOGOS_DIR
from core.data_processor import (
    delete_single_dataset,
    load_data,
    process_and_upload_excel,
    purge_all_data,
    purge_payout_data,
    update_source_tag,
)
from core.database import get_cloud_sync_status
from core.auth import get_all_users, update_user_permissions, edit_user_details

router = APIRouter(prefix="/api/admin", tags=["Admin & Database Management"])


class CompanyUpsertRequest(BaseModel):
    user_role: str
    id: str
    name: str
    short_code: str
    accent_color: Optional[str] = "cyan"
    is_active: Optional[bool] = True


class UpdateUserPermissionRequest(BaseModel):
    user_role: str
    target_email: str
    new_role: str
    can_edit_donors: bool
    can_edit_matrix: bool
    can_manage_tags: bool
    can_purge_data: bool
    allowed_companies: Optional[List[str]] = None


class EditUserRequest(BaseModel):
    user_role: str
    user_id: int
    email: str
    username: str
    password: str = None  # Optional reset password


class AssignPresetRequest(BaseModel):
    user_role: str
    target_email: str
    preset_name: str  # "super_admin", "admin", "data_editor"


class RenameTagRequest(BaseModel):
    user_role: str
    old_tag: str
    new_tag: str


class DeleteTagRequest(BaseModel):
    user_role: str
    tag_name: str


class PurgeDataRequest(BaseModel):
    user_role: str
    confirm: bool = False


@router.get("/users")
def get_users_list():
    return get_all_users()


@router.post("/users/permissions")
def update_user_permission_endpoint(payload: UpdateUserPermissionRequest):
    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Managing user roles and permissions is restricted to Super Admin accounts."
        )

    update_user_permissions(
        payload.target_email,
        payload.new_role,
        payload.can_edit_donors,
        payload.can_edit_matrix,
        payload.can_manage_tags,
        payload.can_purge_data,
        payload.allowed_companies
    )
    return {"status": "success", "message": f"Successfully updated permissions for '{payload.target_email}'."}


@router.post("/users/preset")
def assign_preset_endpoint(payload: AssignPresetRequest):
    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Assigning role presets is restricted to Super Admin accounts."
        )

    preset = payload.preset_name.lower()
    if preset == "super_admin":
        role, d, m, t, p = "super_admin", 1, 1, 1, 1
    elif preset == "data_editor":
        role, d, m, t, p = "data_editor", 1, 1, 0, 0
    else:  # admin (read-only)
        role, d, m, t, p = "admin", 0, 0, 0, 0

    update_user_permissions(payload.target_email, role, d, m, t, p)
    return {"status": "success", "message": f"Successfully assigned preset '{payload.preset_name}' to '{payload.target_email}'."}


@router.post("/users/edit")
def edit_user_endpoint(payload: EditUserRequest):
    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Editing user details is restricted to Super Admin accounts."
        )

    if not payload.email.strip() or not payload.username.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and username are required."
        )

    ok, msg = edit_user_details(
        payload.user_id,
        payload.email,
        payload.username,
        payload.password
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg
        )
    return {"status": "success", "message": msg}


@router.get("/status")
def get_system_status(company_id: Optional[str] = Query(None)):
    comp = str(company_id).lower().strip() if company_id else None
    df_raw = load_data(company_id=comp) if comp and comp != "all" else load_data()
    df_all = load_data()
    total_global = len(df_all)

    pq_exists = os.path.exists(PARQUET_PATH)
    if not pq_exists:
        pq_size = "N/A"
    elif len(df_raw) == 0:
        pq_size = "0.0 MB"
    elif comp and comp != "all" and total_global > 0:
        global_bytes = os.path.getsize(PARQUET_PATH)
        proportional_mb = (len(df_raw) / total_global) * (global_bytes / (1024 * 1024))
        pq_size = f"{proportional_mb:.1f} MB"
    else:
        pq_size = f"{os.path.getsize(PARQUET_PATH) / (1024*1024):.1f} MB"

    sync_info = get_cloud_sync_status()

    return {
        "company_id": comp or "all",
        "total_records": len(df_raw),
        "parquet_exists": pq_exists,
        "parquet_size": pq_size,
        "cloud_sync_status": sync_info["status"] if sync_info else "ACTIVE"
    }


@router.get("/tags")
def get_dataset_tags(company_id: Optional[str] = Query(None)):
    comp = str(company_id).lower().strip() if company_id else None
    df_raw = load_data(company_id=comp) if comp and comp != "all" else load_data()
    if df_raw.empty or "Source" not in df_raw.columns:
        return []

    source_counts = df_raw["Source"].value_counts().reset_index()
    source_counts.columns = ["source_tag", "record_count"]
    return source_counts.to_dict(orient="records")


@router.post("/tags/rename")
def rename_dataset_tag(payload: RenameTagRequest):
    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Renaming dataset tags is restricted to Super Admin accounts."
        )

    if not payload.old_tag or not payload.new_tag.strip():
        raise HTTPException(status_code=400, detail="Old tag and new tag name are required.")

    n_updated = update_source_tag(payload.old_tag, payload.new_tag.strip())
    return {
        "status": "success",
        "message": f"Successfully renamed {n_updated:,} records from '{payload.old_tag}' to '{payload.new_tag.strip()}'."
    }


@router.post("/tags/delete")
def delete_dataset_tag(payload: DeleteTagRequest):
    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Deleting dataset batches is restricted to Super Admin accounts."
        )

    if not payload.tag_name:
        raise HTTPException(status_code=400, detail="Tag name is required.")

    n_deleted = delete_single_dataset(payload.tag_name)
    return {
        "status": "success",
        "message": f"Successfully deleted dataset batch '{payload.tag_name}' ({n_deleted:,} records removed)."
    }


@router.post("/purge")
def purge_database(payload: PurgeDataRequest):
    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Purging all database records is restricted to Super Admin accounts."
        )

    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation is required to purge data.")

    purge_all_data()
    return {
        "status": "success",
        "message": "Database purged cleanly!"
    }


@router.post("/purge-payouts")
def purge_payouts_endpoint(payload: PurgeDataRequest):
    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Purging payout data is restricted to Super Admin accounts."
        )

    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation is required to purge payout data.")

    n_purged = purge_payout_data()
    return {
        "status": "success",
        "message": f"Successfully purged LaunchGood payout settlement data! ({n_purged:,} records removed)"
    }


@router.post("/upload-data")
def upload_raw_data_file(
    user_role: str = Form(...),
    upload_mode: str = Form("merge"),  # "merge" or "replace"
    platform: str = Form("auto"),       # "auto", "launchgood", "givebright", "paysuite", "website"
    company_id: str = Form("rethink"),  # Target company
    file: UploadFile = File(...)
):
    """Bulk uploads a raw donation dataset (.csv, .xlsx, .xls) for LaunchGood, GiveBright, Paysuite, or Rethink Website."""
    if user_role not in ["super_admin", "admin", "data_editor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Uploading donation datasets requires Data Editor or Admin privileges."
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    target_cid = str(company_id or "rethink").strip().lower()
    if not target_cid or target_cid == "all":
        raise HTTPException(status_code=400, detail="Please select a specific company to upload data into (cannot upload into 'All Companies').")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".csv", ".xlsx", ".xls"]:
        raise HTTPException(status_code=400, detail="Unsupported file format. Please upload a .csv, .xlsx, or .xls file.")

    try:
        file_bytes = file.file.read()
        file_buffer = io.BytesIO(file_bytes)

        res = process_and_upload_excel(
            file_buffer=file_buffer,
            source_name=file.filename,
            upload_mode=upload_mode,
            platform=platform,
            company_id=target_cid
        )

        if isinstance(res, dict) and res.get("status") == "error":
            raise HTTPException(status_code=400, detail=res.get("message", "Upload failed."))

        return {
            "status": "success",
            "message": f"Successfully processed '{file.filename}' for company '{target_cid}'! {res.get('added', 0):,} records imported and auto-classified.",
            "details": res
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process uploaded file: {str(e)}")


# ── Dynamic Multi-Company & Brand Logo Management ──────────────────────────────

@router.get("/companies")
def list_companies_endpoint():
    """Returns all registered companies with active status, accent color, and brand logo URL."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, name, short_code, accent_color, logo_url, is_active FROM companies ORDER BY created_at ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"status": "success", "companies": rows}


@router.post("/companies")
def upsert_company_endpoint(payload: CompanyUpsertRequest):
    """Allows Super Admins to dynamically create or update companies."""
    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Managing companies is restricted to Super Admin accounts."
        )
    cid = payload.id.strip().lower()
    if not cid or cid == "all":
        raise HTTPException(status_code=400, detail="Valid Company ID is required (cannot be 'all').")

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO companies (id, name, short_code, accent_color, is_active, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            short_code = excluded.short_code,
            accent_color = excluded.accent_color,
            is_active = excluded.is_active,
            updated_at = CURRENT_TIMESTAMP
    """, (cid, payload.name.strip(), payload.short_code.strip(), payload.accent_color or "cyan", 1 if payload.is_active else 0))
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Successfully saved company '{payload.name}'!"}


@router.post("/companies/{company_id}/logo")
def upload_company_logo_endpoint(company_id: str, user_role: str = Form(...), file: UploadFile = File(...)):
    """Allows Super Admins to upload a custom brand logo image for a company."""
    if user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Uploading company brand logos is restricted to Super Admin accounts."
        )
    cid = company_id.strip().lower()
    if not cid or cid == "all":
        raise HTTPException(status_code=400, detail="Valid Company ID is required.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".svg", ".webp"]:
        raise HTTPException(status_code=400, detail="Unsupported logo image format. Please upload PNG, SVG, JPG, or WEBP.")

    os.makedirs(LOGOS_DIR, exist_ok=True)
    logo_filename = f"{cid}_logo{ext}"
    logo_path = os.path.join(LOGOS_DIR, logo_filename)

    with open(logo_path, "wb") as f:
        f.write(file.file.read())

    logo_url = f"/api/admin/companies/{cid}/logo?t={int(os.path.getmtime(logo_path))}"

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    cur = conn.cursor()
    cur.execute("UPDATE companies SET logo_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (logo_url, cid))
    conn.commit()
    conn.close()

    return {"status": "success", "logo_url": logo_url, "message": f"Brand logo updated for company '{cid}'!"}


@router.get("/companies/{company_id}/logo")
def get_company_logo_endpoint(company_id: str):
    """Serves the uploaded brand logo file for the requested company."""
    cid = company_id.strip().lower()
    for ext in [".png", ".svg", ".webp", ".jpg", ".jpeg"]:
        logo_path = os.path.join(LOGOS_DIR, f"{cid}_logo{ext}")
        if os.path.exists(logo_path):
            media_type = "image/svg+xml" if ext == ".svg" else ("image/png" if ext == ".png" else "image/jpeg")
            return FileResponse(logo_path, media_type=media_type)
    raise HTTPException(status_code=404, detail=f"No custom brand logo found for company '{cid}'.")
