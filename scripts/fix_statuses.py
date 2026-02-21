#!/usr/bin/env python3
import shutil
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "autosocial.db"
BACKUP = ROOT / "autosocial.db.bak"

print("DB:", DB)
shutil.copy2(DB, BACKUP)
print("Backup created at", BACKUP)

conn = sqlite3.connect(str(DB))
cur = conn.cursor()
cur.execute("SELECT status, COUNT(*) FROM posts GROUP BY status")
rows = cur.fetchall()
print("Before:", rows)

cur.execute("UPDATE posts SET status = UPPER(status) WHERE status IS NOT NULL")
conn.commit()

cur.execute("SELECT status, COUNT(*) FROM posts GROUP BY status")
rows = cur.fetchall()
print("After:", rows)
conn.close()

