import sqlite3
from pathlib import Path
import os
from dotenv import load_dotenv

# Load .env from project root
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
BASE_URL = os.getenv("BASE_URL", "https://umittopuz.com")

DB = Path(__file__).resolve().parents[1] / "autosocial.db"
conn = sqlite3.connect(str(DB))
cur = conn.cursor()
cur.execute("SELECT id, image_url FROM posts")
rows = cur.fetchall()
updated = 0
for id_, url in rows:
    if not url:
        continue
    u = url.strip()
    # if it's already absolute, skip
    if u.startswith("http://") or u.startswith("https://"):
        continue
    # if it points to uploads/ig, normalize to BASE_URL + path
    if "uploads/ig" in u:
        if not u.startswith("/"):
            u = "/" + u
        new = BASE_URL.rstrip("/") + u
        cur.execute("UPDATE posts SET image_url = ? WHERE id = ?", (new, id_))
        updated += 1
conn.commit()
conn.close()
print(f"Updated {updated} rows to remote uploads URL using BASE_URL={BASE_URL}")
