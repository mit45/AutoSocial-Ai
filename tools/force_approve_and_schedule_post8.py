import sqlite3
from pathlib import Path
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "autosocial.db"
BASE = "http://127.0.0.1:9001"
POST_ID = 8
SCHEDULE_ISO = "2026-02-09T08:00:00Z"


def force_approve(post_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE posts SET status = ?, scheduled_at = NULL, published_at = NULL, ig_post_id = NULL WHERE id = ?",
            ("APPROVED", post_id),
        )
        conn.commit()
        print("DB updated: set status=APPROVED for post", post_id)
    except Exception as e:
        print("DB error:", e)
    finally:
        conn.close()


def do_post(path, payload):
    url = BASE + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else b"{}"
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8")
            return r.status, body
    except urllib.error.HTTPError as he:
        try:
            body = he.read().decode("utf-8")
        except Exception:
            body = str(he)
        return he.code, body
    except Exception as e:
        return None, str(e)


def main():
    force_approve(POST_ID)
    print("Now calling publish endpoint with scheduled_at:", SCHEDULE_ISO)
    payload = {"post_type": "story", "scheduled_at": SCHEDULE_ISO}
    status, body = do_post(f"/api/publish/{POST_ID}", payload)
    print("Publish response:", status, body)


if __name__ == "__main__":
    main()
