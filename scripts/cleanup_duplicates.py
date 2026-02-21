#!/usr/bin/env python3
"""
Cleanup script for post duplicates and inconsistent publish IDs.

Behavior:
- Back up autosocial.db to autosocial.db.bak.TIMESTAMP
- 1) For posts where ig_post_id_post is NULL and ig_post_id_story is not NULL:
     - copy ig_post_id_story -> ig_post_id_post
     - clear ig_post_id_story
     - set published_at_post/published_at if missing and status=PUBLISHED
- 2) For posts with identical image_url created within DUPLICATE_WINDOW seconds:
     - keep the earliest (by created_at) and mark others as FAILED with error_message noting duplicate removal

This is non-reversible except via the DB backup created at start.
"""
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import time

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "autosocial.db"
BACKUP = ROOT / f"autosocial.db.bak.{int(time.time())}"

def backup_db():
    print("Backing up DB:", DB, "->", BACKUP)
    shutil.copy2(DB, BACKUP)

def fix_story_to_post(conn):
    cur = conn.cursor()
    # Find rows where ig_post_id_post is NULL but ig_post_id_story is not
    cur.execute("SELECT id, ig_post_id_story, status, published_at_story FROM posts WHERE (ig_post_id_post IS NULL OR ig_post_id_post = '') AND (ig_post_id_story IS NOT NULL AND ig_post_id_story != '')")
    rows = cur.fetchall()
    print("Story->Post fixes to apply:", len(rows))
    for r in rows:
        post_id, story_id, status, published_at_story = r
        print(f" - Post {post_id}: copying story id {story_id} -> ig_post_id_post")
        now = datetime.utcnow().isoformat()
        # update: set ig_post_id_post, clear ig_post_id_story, set published_at and status if appropriate
        cur.execute("""UPDATE posts SET ig_post_id_post = ?, ig_post_id_story = NULL, published_at_post = COALESCE(published_at_post, ?), published_at = COALESCE(published_at, ?), status = CASE WHEN status != 'published' THEN 'published' ELSE status END WHERE id = ?""",
                    (story_id, published_at_story or now, published_at_story or now, post_id))
    conn.commit()

def remove_close_duplicates(conn, window_seconds=120):
    cur = conn.cursor()
    # find image_urls with multiple posts
    cur.execute("SELECT image_url, COUNT(*) as c FROM posts WHERE image_url IS NOT NULL GROUP BY image_url HAVING c > 1")
    groups = cur.fetchall()
    print("Duplicate image_url groups:", len(groups))
    removed = 0
    for image_url, cnt in groups:
        cur.execute("SELECT id, created_at FROM posts WHERE image_url = ? ORDER BY created_at ASC", (image_url,))
        rows = cur.fetchall()
        # keep first, consider others duplicates if within window_seconds of first
        if not rows:
            continue
        keep_id, keep_created = rows[0]
        try:
            keep_dt = datetime.fromisoformat(str(keep_created))
        except Exception:
            keep_dt = None
        for r in rows[1:]:
            pid, created = r
            is_dup = False
            if keep_dt:
                try:
                    cur_dt = datetime.fromisoformat(str(created))
                    delta = (cur_dt - keep_dt).total_seconds()
                    if abs(delta) <= window_seconds:
                        is_dup = True
                except Exception:
                    is_dup = True
            else:
                is_dup = True
            if is_dup:
                note = f"duplicate_removed; kept_post_id={keep_id}"
                print(f" - Marking post {pid} as FAILED (duplicate of {keep_id})")
                cur.execute("UPDATE posts SET status = 'failed', error_message = COALESCE(error_message, '') || ? WHERE id = ?", (f"; {note}", pid))
                removed += 1
    conn.commit()
    print("Duplicates marked failed:", removed)

def main():
    if not DB.exists():
        print("DB not found:", DB)
        return
    backup_db()
    conn = sqlite3.connect(str(DB))
    try:
        fix_story_to_post(conn)
        remove_close_duplicates(conn, window_seconds=120)
        print("Cleanup complete.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()

