import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "autosocial.db"

def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cols = [
        ("scheduled_at_post", "DATETIME"),
        ("scheduled_at_story", "DATETIME"),
        ("published_at_post", "DATETIME"),
        ("published_at_story", "DATETIME"),
        ("ig_post_id_post", "TEXT"),
        ("ig_post_id_story", "TEXT"),
    ]
    for name, typ in cols:
        try:
            cur.execute(f"ALTER TABLE posts ADD COLUMN {name} {typ}")
            print("Added", name)
        except Exception as e:
            print("Skipped", name, "->", e)
    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()

