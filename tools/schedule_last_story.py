import sqlite3
from pathlib import Path
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "autosocial.db"


def get_last_post_id():
    if not DB.exists():
        raise FileNotFoundError(f"DB not found: {DB}")
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id FROM posts ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        raise RuntimeError("No posts in DB")
    return int(row[0])


def schedule_story(post_id, iso_utc):
    url = f"http://127.0.0.1:9001/api/publish/{post_id}"
    payload = {"post_type": "story", "scheduled_at": iso_utc}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print("HTTP", r.status)
            print(r.read().decode("utf-8"))
    except urllib.error.HTTPError as he:
        print("HTTPError", he.code)
        try:
            print(he.read().decode("utf-8"))
        except Exception:
            print(str(he))
    except Exception as e:
        print("error", e)


def main():
    # User requested: 09.2.2026 08:00 -> ISO UTC (Z)
    iso_utc = "2026-02-09T08:00:00Z"
    try:
        post_id = get_last_post_id()
        print("Last post id:", post_id)
    except Exception as e:
        print("Failed to read DB:", e)
        return
    print("Scheduling post", post_id, "as STORY at", iso_utc)
    schedule_story(post_id, iso_utc)


if __name__ == "__main__":
    main()
