#!/usr/bin/env python3
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models import AutomationSetting, Account
import json

def main():
    db = SessionLocal()
    try:
        settings = db.query(AutomationSetting).all()
        print(f"Found {len(settings)} automation settings")
        for s in settings:
            acct = db.query(Account).filter(Account.id == s.account_id).first()
            print("-----")
            print("id:", s.id)
            print("account_id:", s.account_id, "ig_user_id:", getattr(acct, 'ig_user_id', None))
            print("enabled:", s.enabled, "frequency:", s.frequency)
            print("daily_count:", s.daily_count, "weekly_count:", s.weekly_count)
            print("start_time:", s.start_time, "end_time:", s.end_time)
            print("start_hour:", s.start_hour, "end_hour:", s.end_hour)
            print("only_draft:", s.only_draft)
            try:
                print("daily_times:", json.loads(s.daily_times) if s.daily_times else [])
            except Exception:
                print("daily_times: <parse error>", s.daily_times)
            try:
                print("weekly_times:", json.loads(s.weekly_times) if s.weekly_times else [])
            except Exception:
                print("weekly_times: <parse error>", s.weekly_times)
            print("last_run_at:", s.last_run_at)
    finally:
        db.close()

if __name__ == '__main__':
    main()

