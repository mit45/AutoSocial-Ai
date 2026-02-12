import sys
from pathlib import Path
import sqlite3
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.image_render import render_image
from app.services.storage_service import upload_to_remote_server
from app.services.instagram import publish_story
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

DB = ROOT / "autosocial.db"


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT id,image_path,image_url,caption,status FROM posts ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        print("No posts found")
        return
    post_id, image_path, image_url, caption, status = row
    print("Post:", post_id, image_path, image_url, status)

    # Render square image (existing render_image produces 1080x1080)
    bg_path = Path(image_path) if image_path else None
    if not bg_path or not bg_path.exists():
        # try storage/generated
        gen = next((p for p in (ROOT / "storage" / "generated").glob("*.png")), None)
        if not gen:
            print("No background image found to render")
            return
        bg_path = gen

    rel, abs_path = render_image(
        str(bg_path), caption or "", "ince düşlerim", "minimal_dark"
    )
    square_path = Path(abs_path)
    print("Square rendered:", square_path)

    # Create story canvas 1080x1920 and paste square centered
    from PIL import Image

    story_w, story_h = 1080, 1920
    story_img = Image.new("RGBA", (story_w, story_h), (0, 0, 0, 255))
    sq = Image.open(square_path).convert("RGBA")
    # center
    x = (story_w - sq.width) // 2
    y = (story_h - sq.height) // 2
    story_img.paste(sq, (x, y), sq)

    # save story image
    story_out = ROOT / "media" / f"{post_id}-story.png"
    story_img.convert("RGB").save(story_out, "PNG")
    print("Story image saved:", story_out)

    # upload to remote
    with open(story_out, "rb") as f:
        b = f.read()
    filename = story_out.name
    try:
        public_url = upload_to_remote_server(b, filename)
    except Exception as e:
        print("Upload failed:", e)
        public_url = f"/media/{filename}"
    print("Public URL:", public_url)

    # publish as story
    ig_user_id = os.getenv("INSTAGRAM_USER_ID")
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if not ig_user_id or not token:
        print("Missing IG credentials in .env")
        return

    resp = publish_story(
        image_url=public_url, ig_user_id=ig_user_id, access_token=token
    )
    print("Publish response:", resp)

    # update DB if published
    try:
        # Normalize different response shapes from publish_story
        published_id = None
        if isinstance(resp, dict):
            # published response may be nested
            if resp.get("publish_response") and isinstance(
                resp["publish_response"], dict
            ):
                published_id = resp["publish_response"].get("id")
            elif resp.get("id"):
                published_id = resp.get("id")
            elif resp.get("creation_response") and isinstance(
                resp["creation_response"], dict
            ):
                published_id = resp["creation_response"].get("id")

        if published_id:
            cur.execute(
                "UPDATE posts SET image_url=?, status=?, ig_post_id=? WHERE id=?",
                (public_url, "PUBLISHED", str(published_id), post_id),
            )
            conn.commit()
            print("DB updated: published (ig_post_id=%s)" % published_id)
        else:
            # if error or unexpected shape
            err = resp.get("error") if isinstance(resp, dict) else str(resp)
            cur.execute(
                "UPDATE posts SET status=?, error_message=? WHERE id=?",
                ("FAILED", str(err), post_id),
            )
            conn.commit()
            print("DB updated: failed")
    except Exception as e:
        print("DB update error:", e)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
