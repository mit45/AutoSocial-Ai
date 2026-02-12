import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "autosocial.db"


def main():
    if not DB.exists():
        print("DB not found:", DB)
        return
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, topic, status, image_url, created_at, published_at, error_message FROM posts ORDER BY id DESC"
        )
        rows = cur.fetchall()
        print("posts_count:", len(rows))
        for r in rows:
            print(r)
    except Exception as e:
        print("error reading DB:", e)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
