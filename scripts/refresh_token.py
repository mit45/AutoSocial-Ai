#!/usr/bin/env python3
"""
Exchange a short-lived Facebook token for a long-lived token and update .env + sqlite DB.
Usage: python scripts/refresh_token.py
"""
import os
import json
import sqlite3
from urllib.parse import urlencode
from urllib.request import urlopen, Request

ROOT = os.path.dirname(os.path.dirname(__file__))
ENV_PATH = os.path.join(ROOT, ".env")
DB_PATH = os.path.join(ROOT, "autosocial.db")


def read_env(path):
    data = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def write_env(path, data):
    # Preserve original file structure as much as possible by replacing known keys
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k = line.split("=", 1)[0].strip()
                if k in data:
                    lines.append(f"{k}={data[k]}\n")
                    continue
            lines.append(line)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def exchange_long_lived(app_id, app_secret, short_token):
    base = "https://graph.facebook.com/v17.0/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    }
    url = base + "?" + urlencode(params)
    req = Request(url)
    with urlopen(req, timeout=30) as resp:
        data = resp.read().decode("utf-8")
        return json.loads(data)


def update_db_token(db_path, ig_user_id, new_token):
    if not os.path.exists(db_path):
        print("DB not found, skipping DB update:", db_path)
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    if ig_user_id:
        cur.execute("UPDATE accounts SET access_token=? WHERE ig_user_id=?", (new_token, ig_user_id))
        updated = cur.rowcount
    else:
        cur.execute("UPDATE accounts SET access_token=?", (new_token,))
        updated = cur.rowcount
    conn.commit()
    conn.close()
    print(f"DB updated, rows affected: {updated}")


def mask_token(t):
    if not t:
        return ""
    if len(t) <= 12:
        return t
    return t[:6] + "..." + t[-6:]


def main():
    if not os.path.exists(ENV_PATH):
        print(".env not found at", ENV_PATH)
        return
    env = read_env(ENV_PATH)
    app_id = env.get("INSTAGRAM_APP_ID") or env.get("FACEBOOK_APP_ID") or env.get("APP_ID")
    app_secret = env.get("INSTAGRAM_APP_SECRET") or env.get("FACEBOOK_APP_SECRET") or env.get("APP_SECRET")
    short = env.get("YOUR_SHORT_LIVED_TOKEN") or env.get("SHORT_LIVED_TOKEN") or env.get("INSTAGRAM_SHORT_TOKEN")
    if not app_id or not app_secret or not short:
        print("Missing values in .env. Need INSTAGRAM_APP_ID, INSTAGRAM_APP_SECRET and YOUR_SHORT_LIVED_TOKEN")
        return
    print("Exchanging short token for long-lived token...")
    try:
        resp = exchange_long_lived(app_id, app_secret, short)
    except Exception as e:
        print("Exchange request failed:", e)
        return
    if "error" in resp:
        print("Exchange returned error:", resp["error"])
        return
    new_token = resp.get("access_token")
    expires = resp.get("expires_in")
    if not new_token:
        print("No access_token in response:", resp)
        return
    # Update .env: set INSTAGRAM_ACCESS_TOKEN to new_token
    env["INSTAGRAM_ACCESS_TOKEN"] = new_token
    write_env(ENV_PATH, env)
    print("Wrote INSTAGRAM_ACCESS_TOKEN to .env (masked):", mask_token(new_token))
    print("expires_in (seconds):", expires)
    # Update DB accounts table where ig_user_id matches INSTAGRAM_USER_ID if present
    ig_uid = env.get("INSTAGRAM_USER_ID")
    update_db_token(DB_PATH, ig_uid, new_token)
    print("Done.")


if __name__ == "__main__":
    main()

