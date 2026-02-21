#!/usr/bin/env python3
import sqlite3
from urllib.parse import urlparse
from pathlib import Path
import os

DB = Path(__file__).resolve().parent.parent / "autosocial.db"

# Load R2 config from environment or .env
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
if not (R2_ACCOUNT_ID and R2_BUCKET_NAME):
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("R2_ACCOUNT_ID="):
                R2_ACCOUNT_ID = line.split("=", 1)[1].strip()
            if line.startswith("R2_BUCKET_NAME="):
                R2_BUCKET_NAME = line.split("=", 1)[1].strip()

if not (R2_ACCOUNT_ID and R2_BUCKET_NAME):
    print("Missing R2_ACCOUNT_ID or R2_BUCKET_NAME; aborting.")
    raise SystemExit(1)

conn = sqlite3.connect(str(DB))
cur = conn.cursor()
cur.execute("SELECT id, image_url FROM posts WHERE image_url IS NOT NULL;")
rows = cur.fetchall()
updated = 0
for id_, url in rows:
    if not url:
        continue
    parsed = urlparse(url)
    # if host already equals account endpoint, skip
    if parsed.netloc.startswith(f"{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"):
        continue
    # build new URL with account endpoint and original path
    path = parsed.path.lstrip("/")
    new = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/{R2_BUCKET_NAME}/{path}"
    if new != url:
        print(f"Updating {id_}: {url} -> {new}")
        cur.execute("UPDATE posts SET image_url = ? WHERE id = ?", (new, id_))
        updated += 1

conn.commit()
conn.close()
print(f"Done. Updated {updated} rows.")

