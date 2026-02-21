#!/usr/bin/env python3
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "autosocial.db"

def main():
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()
    cur.execute('''SELECT id, topic, caption, image_url, image_path, image_prompt, status, created_at, scheduled_at_post, scheduled_at_story, ig_post_id_post, ig_post_id_story FROM posts ORDER BY created_at DESC LIMIT 20''')
    rows = cur.fetchall()
    keys = ['id','topic','caption','image_url','image_path','image_prompt','status','created_at','scheduled_at_post','scheduled_at_story','ig_post_id_post','ig_post_id_story']
    import sys
    out = sys.stdout
    for r in rows:
        out.buffer.write(b'--- POST ---\\n')
        for k, v in zip(keys, r):
            line = f"{k}: {v}\\n"
            out.buffer.write(line.encode('utf-8', errors='replace'))
    conn.close()

if __name__ == '__main__':
    main()

