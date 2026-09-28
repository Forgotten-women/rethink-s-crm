import os
import shutil

PROJECT_ROOT = "/home/ubuntu/Python_Visualization"

def organize_root():
    print("🧹 Organizing root directory structure...")

    # 1. Ensure target directories exist
    backups_dir = os.path.join(PROJECT_ROOT, "data_cache", "backups")
    sheets_dir = os.path.join(PROJECT_ROOT, "Sheets")
    docs_dir = os.path.join(PROJECT_ROOT, "docs")
    scripts_dir = os.path.join(PROJECT_ROOT, "scripts")
    
    os.makedirs(backups_dir, exist_ok=True)
    os.makedirs(sheets_dir, exist_ok=True)
    os.makedirs(docs_dir, exist_ok=True)
    os.makedirs(scripts_dir, exist_ok=True)

    # 2. Move spreadsheets to Sheets/
    sheet_files = ["Rethink_Humama_Final.xlsx"]
    for f in sheet_files:
        src = os.path.join(PROJECT_ROOT, f)
        dst = os.path.join(sheets_dir, f)
        if os.path.exists(src):
            shutil.move(src, dst)
            print(f"  📁 Moved '{f}' -> Sheets/")

    # 3. Move documentation files to docs/
    doc_files = ["questions.md"]
    for f in doc_files:
        src = os.path.join(PROJECT_ROOT, f)
        dst = os.path.join(docs_dir, f)
        if os.path.exists(src):
            shutil.move(src, dst)
            print(f"  📁 Moved '{f}' -> docs/")

    # 4. Move windows batch runner scripts to scripts/
    batch_files = ["run_app.bat", "run_dashboard.bat", "run_dev.bat"]
    for f in batch_files:
        src = os.path.join(PROJECT_ROOT, f)
        dst = os.path.join(scripts_dir, f)
        if os.path.exists(src):
            shutil.move(src, dst)
            print(f"  📁 Moved '{f}' -> scripts/")

    # 5. Move database backup files to data_cache/backups/
    for fname in os.listdir(PROJECT_ROOT):
        if fname.startswith("launchgood_donations.db.bak"):
            src = os.path.join(PROJECT_ROOT, fname)
            dst = os.path.join(backups_dir, fname)
            shutil.move(src, dst)
            print(f"  📁 Moved '{fname}' -> data_cache/backups/")

    # 6. Clean up 0-byte orphan DB files, build artifacts, logs, and obsolete stubs
    orphan_files = ["analytics.db", "beneficiaries.db", "crm.db", "donors.db", "uvicorn.log", "utils.py"]
    for f in orphan_files:
        p = os.path.join(PROJECT_ROOT, f)
        if os.path.exists(p):
            os.remove(p)
            print(f"  🗑️ Removed orphan/log file '{f}'")

    # 7. Clean up empty/build directories
    orphan_dirs = ["Dashboard_RT_CRM", "crowdfunding_crm_backend.egg-info"]
    for d in orphan_dirs:
        p = os.path.join(PROJECT_ROOT, d)
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)
            print(f"  🗑️ Removed build/empty directory '{d}/'")

    print("\n✨ Root directory cleaning complete!")

if __name__ == "__main__":
    organize_root()
