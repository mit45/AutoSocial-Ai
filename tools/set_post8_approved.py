import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "autosocial.db"


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute(
        "UPDATE posts SET status = ?, error_message = NULL WHERE id = ?",
        ("APPROVED", 8),
    )
    conn.commit()
    conn.close()
    print("Post 8 set to APPROVED")


if __name__ == "__main__":
    main()
