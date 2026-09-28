import sqlite3
import re

DB_PATH = "/home/ubuntu/Python_Visualization/launchgood_donations.db"
BASE_URL = "https://rethink.dpdns.org"

RETHINK_LOGO = f"{BASE_URL}/logos/rethink_email_logo.png"
IQRA_LOGO = f"{BASE_URL}/logos/iqra_email_logo.png"
SP_LOGO = f"{BASE_URL}/logos/sp_logo.png"

def migrate_templates():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, company_id, template_type, body_html FROM sponsorship_email_templates")
    rows = cur.fetchall()
    
    updated_count = 0
    for row_id, company_id, template_type, body_html in rows:
        cid = str(company_id).lower()
        new_html = body_html
        
        if cid == "sp_rethink":
            # First replace the Sisters' Project logo src
            new_html = re.sub(
                r'(<img[^>]*src=")[^"]*data:image/[^;]+;base64,[^"]*("[^>]*alt="Sisters\' Project")',
                r'\1' + SP_LOGO + r'\2',
                new_html
            )
            new_html = re.sub(
                r'(<img[^>]*alt="Sisters\' Project"[^>]*src=")[^"]*data:image/[^;]+;base64,[^"]*(")',
                r'\1' + SP_LOGO + r'\2',
                new_html
            )
            # Then replace the Rethink logo src
            new_html = re.sub(
                r'(<img[^>]*src=")[^"]*data:image/[^;]+;base64,[^"]*("[^>]*alt="Rethink Charity")',
                r'\1' + RETHINK_LOGO + r'\2',
                new_html
            )
            new_html = re.sub(
                r'(<img[^>]*alt="Rethink Charity"[^>]*src=")[^"]*data:image/[^;]+;base64,[^"]*(")',
                r'\1' + RETHINK_LOGO + r'\2',
                new_html
            )
            # Generic cleanup for any remaining data URIs
            new_html = re.sub(r'data:image/[^;]+;base64,[^"\'\s>]+', RETHINK_LOGO, new_html)
        elif cid == "sp":
            new_html = re.sub(r'data:image/[^;]+;base64,[^"\'\s>]+', SP_LOGO, new_html)
        elif cid == "iqra":
            new_html = re.sub(r'data:image/[^;]+;base64,[^"\'\s>]+', IQRA_LOGO, new_html)
        else: # rethink
            new_html = re.sub(r'data:image/[^;]+;base64,[^"\'\s>]+', RETHINK_LOGO, new_html)
            
        if len(new_html) != len(body_html):
            cur.execute("UPDATE sponsorship_email_templates SET body_html = ? WHERE id = ?", (new_html, row_id))
            print(f"Row {row_id} ({cid} - {template_type}): {len(body_html):,} bytes -> {len(new_html):,} bytes")
            updated_count += 1
            
    conn.commit()
    conn.close()
    print(f"\nMigration complete: {updated_count} templates cleaned.")

if __name__ == "__main__":
    migrate_templates()
