#!/usr/bin/env python3
'''Fix duplicated /ig/post/ig/post/ segments in SQLite DB image_url fields using app.utils.normalize_image_url.'''
import sqlite3
from pathlib import Path
import sys

# make sure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.utils import normalize_image_url

DB_PATH = PROJECT_ROOT / 'autosocial.db'

def main(dry_run: bool = False):
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    cur.execute('SELECT id, image_url FROM posts;')
    rows = cur.fetchall()
    updates = []
    for id_, url in rows:
        if not url:
            continue
        new = normalize_image_url(url)
        if new and new != url:
            updates.append((id_, url, new))
    print(f'Found {len(updates)} rows to update.')
    for id_, old, new in updates:
        print(f'{id_}: {old} -> {new}')
    if not dry_run and updates:
        for id_, old, new in updates:
            cur.execute('UPDATE posts SET image_url = ? WHERE id = ?', (new, id_))
        con.commit()
        print('Applied updates.')
    elif dry_run:
        print('Dry run complete. No changes applied.')
    con.close()

if __name__ == '__main__':
    dry = '--dry' in sys.argv or '-n' in sys.argv
    main(dry_run=dry)

