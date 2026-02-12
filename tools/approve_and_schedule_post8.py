import json
import urllib.request

BASE = "http://127.0.0.1:9001"
POST_ID = 8
SCHEDULE_ISO = "2026-02-09T08:00:00Z"


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
    print("Approving post", POST_ID)
    status, body = do_post(f"/api/approve/{POST_ID}", {})
    print("Approve response:", status, body)
    if status != 200:
        print("Approve failed, aborting.")
        return

    print("Scheduling publish as STORY at", SCHEDULE_ISO)
    payload = {"post_type": "story", "scheduled_at": SCHEDULE_ISO}
    status2, body2 = do_post(f"/api/publish/{POST_ID}", payload)
    print("Publish response:", status2, body2)


if __name__ == "__main__":
    main()
