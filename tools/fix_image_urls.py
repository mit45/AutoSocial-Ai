import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "autosocial.db"
conn = sqlite3.connect(str(DB))
cur = conn.cursor()
base = "https://umittopuz.com"
cur.execute("SELECT id, image_url FROM posts")
rows = cur.fetchall()
updated = 0
for id_, url in rows:
    if url and url.startswith(base):
        new = url.replace(base, "")
        cur.execute("UPDATE posts SET image_url = ? WHERE id = ?", (new, id_))
        updated += 1
conn.commit()
conn.close()
print(f"Updated {updated} rows")
