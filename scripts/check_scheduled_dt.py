#!/usr/bin/env python3
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime, timezone
from app.database import SessionLocal
from app.models import AutomationSetting
import json

def main():
    db = SessionLocal()
    s = db.query(AutomationSetting).first()
    now = datetime.utcnow()
    print("now UTC:", now)
    local_tz = datetime.now().astimezone().tzinfo
    print("local tz:", local_tz)
    daily = json.loads(s.daily_times) if s.daily_times else []
    for t in daily:
        var_time = t.get("time") if isinstance(t, dict) else str(t)
        parts = var_time.split(":")
        hh = int(parts[0]); mm = int(parts[1]) if len(parts)>1 else 0
        scheduled_local = datetime(now.year, now.month, now.day, hh, mm, tzinfo=local_tz)
        scheduled_dt = scheduled_local.astimezone(timezone.utc).replace(tzinfo=None)
        print("entry:", var_time, "scheduled_dt UTC:", scheduled_dt, "last_run_at:", s.last_run_at, "last_run < scheduled?", (s.last_run_at is None) or (s.last_run_at < scheduled_dt))

if __name__ == '__main__':
    main()

