#!/usr/bin/env python3
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models import Post
from app.api.routes import _public_image_url
import traceback

def main():
    db = SessionLocal()
    try:
        posts = db.query(Post).order_by(Post.created_at.desc()).all()
        print(f"Found {len(posts)} posts")
        for p in posts:
            try:
                img = _public_image_url(p.image_url)
                print(f"Post {p.id}: image_url -> {img!r}")
            except Exception as e:
                print(f"Error processing post {p.id}: {e}")
                traceback.print_exc()
    finally:
        db.close()

if __name__ == '__main__':
    main()

