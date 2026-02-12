"""
Simple scheduled runner that calls the application's scheduled-check endpoint.
Use Windows Task Scheduler (or cron/systemd on Linux) to run this script every minute.
"""

import os
import sys
import requests
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[1]
# Read BASE_URL from env/.env if present
from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env")
API_BASE = os.getenv("BASE_URL", "http://127.0.0.1:9001").rstrip("/")

URL = f"{API_BASE}/api/scheduled/check"


def main():
    try:
        r = requests.post(URL, timeout=30)
        try:
            data = r.json()
        except Exception:
            data = r.text
        print(f"[{datetime.utcnow().isoformat()}] {r.status_code} - {data}")
        return 0
    except Exception as e:
        print(f"[{datetime.utcnow().isoformat()}] ERROR calling {URL}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
