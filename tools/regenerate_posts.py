import sys
from pathlib import Path
import sqlite3
import json
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.services.content_ai import (
    generate_caption,
    generate_hashtags,
    generate_image_prompt,
    generate_image_png_bytes,
)
from app.services.storage_service import (
    save_png_bytes_to_generated,
    upload_to_remote_server,
)
from app.services.image_render import render_image

DB = ROOT / "autosocial.db"


def regen_post(post_id: int):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id, topic FROM posts WHERE id = ?", (post_id,))
    row = cur.fetchone()
    if not row:
        print(f"Post {post_id} not found")
        conn.close()
        return
    _, topic = row
    print(f"Regenerating post {post_id} topic='{topic}'")

    try:
        caption = generate_caption(topic)
    except Exception as e:
        print("Caption generation failed:", e)
        caption = f"Test post about {topic}. #AI #Automation"

    try:
        hashtags = generate_hashtags(topic, caption=caption, count=10)
    except Exception as e:
        print("Hashtag generation failed:", e)
        hashtags = ["#AI", "#Automation"]

    try:
        image_prompt = generate_image_prompt(topic)
    except Exception as e:
        print("Image prompt generation failed:", e)
        image_prompt = (
            f"Square 1:1 Instagram post image, high quality, modern style, {topic}"
        )

    # Generate image bytes
    try:
        png_bytes = generate_image_png_bytes(image_prompt)
    except Exception as e:
        print("Image generation failed:", e)
        conn.close()
        return

    # Save generated background (storage/generated) and get public url
    rel_bg, public_bg = save_png_bytes_to_generated(png_bytes)
    print("Background saved:", rel_bg, public_bg)

    # Render final image (text on background)
    try:
        BASE_DIR = ROOT
        background_full = BASE_DIR / "storage" / rel_bg
        signature = "ince düşlerim"
        rel_final, abs_final = render_image(
            background_path=str(background_full),
            text=caption,
            signature=signature,
            style="minimal_dark",
            target="square",
        )
        with open(abs_final, "rb") as f:
            final_bytes = f.read()
    except Exception as e:
        print("Render failed:", e)
        conn.close()
        return

    # Upload final image remote
    filename_final = os.path.basename(abs_final)
    try:
        public_final = upload_to_remote_server(final_bytes, filename_final)
    except Exception as e:
        print("Upload final failed:", e)
        public_final = f"/media/{filename_final}"

    # Update DB: set caption, hashtags, image_prompt, image_path, image_url, status DRAFT
    try:
        cur.execute(
            "UPDATE posts SET caption = ?, hashtags = ?, image_prompt = ?, image_path = ?, image_url = ?, status = ?, error_message = NULL WHERE id = ?",
            (
                caption,
                json.dumps(hashtags),
                image_prompt,
                rel_final,
                public_final,
                "DRAFT",
                post_id,
            ),
        )
        conn.commit()
        print(f"Post {post_id} updated: image_url={public_final}")
    except Exception as e:
        print("DB update failed:", e)
    finally:
        conn.close()


def main():
    ids = [9, 10]
    for pid in ids:
        regen_post(pid)


if __name__ == "__main__":
    main()
