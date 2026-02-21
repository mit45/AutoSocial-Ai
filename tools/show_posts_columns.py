import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "autosocial.db"

def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(posts)")
    cols = cur.fetchall()
    for c in cols:
        print(c[1], c[2])
    conn.close()

if __name__ == '__main__':
    main()

