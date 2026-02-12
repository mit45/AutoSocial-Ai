import json
import urllib.request
import sqlite3
from pathlib import Path

BASE = "http://127.0.0.1:9001"


def call_generate(topic=None):
    url = BASE + "/api/generate"
    payload = {
        "topic": topic or "Test içerik kontrolü",
        "post_type": "post",
        "render_style": "minimal_dark",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print("HTTP", r.status)
            print(r.read().decode("utf-8"))
    except Exception as e:
        print("error calling generate:", e)


def last_db_posts(limit=5):
    DB = Path(__file__).resolve().parents[1] / "autosocial.db"
    if not DB.exists():
        print("DB not found:", DB)
        return
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, topic, status, image_url, created_at FROM posts ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    for r in rows:
        print(r)
    conn.close()


if __name__ == "__main__":
    call_generate("Kontrol: otomatik içerik üretimi testi")
    print("--- Latest posts in DB ---")
    last_db_posts(5)
