import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "autosocial.db"

def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE automation_settings ADD COLUMN start_time TEXT")
        print("Added start_time")
    except Exception as e:
        print("Skipped start_time:", e)
    try:
        cur.execute("ALTER TABLE automation_settings ADD COLUMN end_time TEXT")
        print("Added end_time")
    except Exception as e:
        print("Skipped end_time:", e)
    conn.commit()
    conn.close()

if __name__ == '__main__':
    main()

