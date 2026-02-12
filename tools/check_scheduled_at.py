import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "autosocial.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("SELECT id, status, scheduled_at, published_at FROM posts ORDER BY id DESC")
rows = cur.fetchall()
for r in rows:
    print(r)
conn.close()
