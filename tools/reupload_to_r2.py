#!/usr/bin/env python3
"""
Scan local generated/media files, upload to R2, update DB posts.image_url and remove local file.

Usage:
  python tools/reupload_to_r2.py

Requires .env to contain R2 credentials (already in project .env).
"""
import sys
from pathlib import Path
import sqlite3
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from app.services import r2_storage
from app.services import storage_backend
from app.config import R2_ACCOUNT_ID, R2_BUCKET_NAME, R2_PUBLIC_BASE_URL

DB = ROOT / "autosocial.db"

def find_matching_post(cur, filename):
    # try to find post by image_path or image_url containing filename
    cur.execute("SELECT id, type FROM posts WHERE image_path LIKE ? OR image_url LIKE ? LIMIT 1", (f"%{filename}%", f"%{filename}%"))
    row = cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "type": row[1]}

def upload_file(path: Path, prefix: str):
    b = path.read_bytes()
    # Use centralized storage backend (r2_storage kept for compatibility)
    try:
        url = storage_backend.upload_bytes(b, path.name, prefix=prefix)
    except Exception:
        url = r2_storage.upload_bytes(b, path.name, prefix=prefix)
    return url

def main():
    if not (R2_ACCOUNT_ID and R2_BUCKET_NAME):
        print("R2 not configured in .env. Aborting.")
        return 1

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Collect candidate files: media/ and storage/generated/
    candidates = []
    for d in (ROOT / "media", ROOT / "storage" / "generated"):
        if d.exists():
            for p in sorted(d.iterdir()):
                if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    candidates.append(p)

    print(f"Found {len(candidates)} candidate files to upload.")
    for p in candidates:
        fname = p.name
        post = find_matching_post(cur, fname)
        if post:
            ptype = post["type"] or "post"
        else:
            # heuristic: filename contains 'story' or '{id}-story'
            if "story" in fname.lower():
                ptype = "story"
            else:
                ptype = "post"

        prefix = "ig/story" if ptype == "story" else "ig/post"
        print(f"Uploading {p} as {ptype} -> prefix={prefix} ...")
        try:
            url = upload_file(p, prefix)
            print("Uploaded ->", url)
            # update DB if matching post found
            if post:
                cur.execute("UPDATE posts SET image_url = ?, image_path = NULL WHERE id = ?", (url, post["id"]))
                conn.commit()
                print(f"Updated DB post id={post['id']}")
            # remove local file
            try:
                p.unlink()
                print("Removed local file:", p)
            except Exception as e:
                print("Failed to remove local file:", e)
        except Exception as e:
            print("Upload failed for", p, ":", e)

    conn.close()
    print("Done.")
    return 0

if __name__ == "__main__":
    sys.exit(main())

