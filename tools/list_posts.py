import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "autosocial.db"
conn = sqlite3.connect(str(DB))
cur = conn.cursor()
cur.execute(
    "SELECT id, image_path, image_url, type, status, created_at FROM posts ORDER BY id DESC LIMIT 20"
)
rows = cur.fetchall()
for r in rows:
    print(r)
conn.close()
