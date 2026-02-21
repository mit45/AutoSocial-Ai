#!/usr/bin/env python3
"""
Add missing automation_settings columns (daily_times, weekly_times) to SQLite DB.
Usage: python tools/add_automation_time_columns.py
"""
import os
import sqlite3
from urllib.parse import urlparse

DB_ENV = os.environ.get("DATABASE_URL", "sqlite:///./autosocial.db")

def sqlite_path_from_dburl(dburl: str) -> str:
    # expects sqlite:///./path or sqlite:///absolute/path
    if dburl.startswith("sqlite:///"):
        path = dburl[len("sqlite:///"):]
        # relative paths are relative to project root
        return os.path.abspath(path)
    # fallback: if it's a bare path
    return os.path.abspath(dburl)

def column_exists(conn, table, column):
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]
    return column in cols

def add_column_if_missing(conn, table, column_def):
    # column_def example: "daily_times TEXT"
    col = column_def.split()[0]
    if column_exists(conn, table, col):
        print(f"Column '{col}' already exists on '{table}'. Skipping.")
        return
    sql = f"ALTER TABLE {table} ADD COLUMN {column_def};"
    print("Executing:", sql)
    conn.execute(sql)
    conn.commit()
    print(f"Added column '{col}' to '{table}'.")

def main():
    db_path = sqlite_path_from_dburl(DB_ENV)
    if not os.path.exists(db_path):
        print("Database file not found:", db_path)
        print("Check DATABASE_URL in your .env or pass a correct path in the environment.")
        return
    print("Using SQLite DB:", db_path)
    conn = sqlite3.connect(db_path)
    try:
        # ensure table exists
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='automation_settings'")
        if not cur.fetchone():
            print("Table 'automation_settings' does not exist. Nothing to do.")
            return
        add_column_if_missing(conn, "automation_settings", "daily_times TEXT")
        add_column_if_missing(conn, "automation_settings", "weekly_times TEXT")
        print("Done.")
    except Exception as e:
        print("Error:", e)
    finally:
        conn.close()

if __name__ == "__main__":
    main()

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

