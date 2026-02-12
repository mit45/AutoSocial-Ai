"""Zamanlanmış post'ları kontrol edip yayınlayan servis."""

import os
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import Post, Account, PostStatus
from app.services.instagram import publish_image, publish_story
from app.models import PostType
import json


def run_scheduled_publish():
    """
    Zamanı gelen (scheduled_at <= now) approved post'ları Instagram'a yayınlar.
    Returns: (checked_count, published_count, errors)
    """
    db = SessionLocal()
    try:
        now = datetime.utcnow()

        # Find posts that are approved and have either post/story scheduled
        scheduled_posts = (
            db.query(Post)
            .filter(Post.status == PostStatus.APPROVED)
            .filter(
                (Post.scheduled_at.isnot(None))
                | (Post.scheduled_at_post.isnot(None))
                | (Post.scheduled_at_story.isnot(None))
            )
            .all()
        )

        def to_dt(s):
            if not s:
                return None
            if isinstance(s, str):
                try:
                    return datetime.fromisoformat(s.replace("Z", "+00:00"))
                except Exception:
                    return None
            return s

        def due_post(p):
            s = p.scheduled_at_post or p.scheduled_at
            dt = to_dt(s)
            if not dt:
                return False
            if getattr(dt, "tzinfo", None):
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt <= now

        def due_story(p):
            s = p.scheduled_at_story
            dt = to_dt(s)
            if not dt:
                return False
            if getattr(dt, "tzinfo", None):
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt <= now

        due = [p for p in scheduled_posts if due_post(p) or due_story(p)]
        if due:
            print(f"[SCHEDULED] At {now}: found {len(due)} post(s) due for publish")

        published = 0
        errors = []

        for post in due:
            try:
                account = db.query(Account).first()
                if not account:
                    errors.append(f"Post {post.id}: No account found")
                    continue

                ig_user_id = account.ig_user_id
                access_token = account.access_token
                env_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
                if env_token:
                    access_token = env_token

                image_url = post.image_url
                if not image_url:
                    errors.append(f"Post {post.id}: No image_url")
                    continue
                if image_url.startswith("/static/") or image_url.startswith("/media/"):
                    # Convert to full URL using BASE_URL if available, otherwise treat as local and error
                    from app.config import BASE_URL

                    if BASE_URL:
                        image_url = BASE_URL.rstrip("/") + image_url
                    else:
                        errors.append(
                            f"Post {post.id}: image_url is local. Instagram needs public URL (https://...)."
                        )
                        continue

                # Determine which parts are due
                do_post_publish = due_post(post)
                do_story_publish = due_story(post)

                # publish POST if due
                if do_post_publish:
                    # Prepare caption/hashtags
                    hashtags_list = []
                    if post.hashtags:
                        try:
                            hashtags_list = json.loads(post.hashtags)
                        except Exception:
                            hashtags_list = [h.strip() for h in str(post.hashtags).split(",") if h.strip()]
                    try:
                        from app.services.content_ai import format_post_text

                        final_caption = format_post_text(post.caption, hashtags_list) if hashtags_list else post.caption
                    except Exception:
                        final_caption = post.caption

                    ig_response = publish_image(
                        image_url=image_url,
                        caption=final_caption,
                        ig_user_id=ig_user_id,
                        access_token=access_token,
                    )

                    # handle response
                    published_id = None
                    if isinstance(ig_response, dict) and "error" in ig_response:
                        post.error_message = str(ig_response.get("error", {}).get("message", "Unknown error"))
                        errors.append(f"Post {post.id} (post): {post.error_message}")
                        print(f"[SCHEDULED] Post {post.id} (post): Publish failed: {post.error_message}")
                    else:
                        if isinstance(ig_response, dict) and ig_response.get("id"):
                            published_id = str(ig_response.get("id"))
                        elif isinstance(ig_response, dict) and isinstance(ig_response.get("publish_response"), dict):
                            published_id = str(ig_response["publish_response"].get("id"))
                        elif isinstance(ig_response, dict) and isinstance(ig_response.get("creation_response"), dict):
                            published_id = str(ig_response["creation_response"].get("id"))

                        if published_id:
                            post.published_at_post = datetime.utcnow()
                            post.ig_post_id_post = published_id
                            post.account_id = account.id
                            post.scheduled_at_post = None
                            post.error_message = None
                            published += 1
                            print(f"[SCHEDULED] Post {post.id}: Published POST successfully (IG ID: {published_id})")
                        else:
                            post.error_message = f"Unexpected publish response (post): {ig_response}"
                            errors.append(f"Post {post.id}: {post.error_message}")
                            print(f"[SCHEDULED] Post {post.id}: Unexpected publish response (post): {ig_response}")

                # publish STORY if due
                if do_story_publish:
                    ig_response = publish_story(image_url=image_url, ig_user_id=ig_user_id, access_token=access_token)
                    published_id = None
                    if isinstance(ig_response, dict) and "error" in ig_response:
                        post.error_message = str(ig_response.get("error", {}).get("message", "Unknown error"))
                        errors.append(f"Post {post.id} (story): {post.error_message}")
                        print(f"[SCHEDULED] Post {post.id} (story): Publish failed: {post.error_message}")
                    else:
                        if isinstance(ig_response, dict) and ig_response.get("id"):
                            published_id = str(ig_response.get("id"))
                        elif isinstance(ig_response, dict) and isinstance(ig_response.get("publish_response"), dict):
                            published_id = str(ig_response["publish_response"].get("id"))
                        elif isinstance(ig_response, dict) and isinstance(ig_response.get("creation_response"), dict):
                            published_id = str(ig_response["creation_response"].get("id"))

                        if published_id:
                            post.published_at_story = datetime.utcnow()
                            post.ig_post_id_story = published_id
                            post.account_id = account.id
                            post.scheduled_at_story = None
                            post.error_message = None
                            published += 1
                            print(f"[SCHEDULED] Post {post.id}: Published STORY successfully (IG ID: {published_id})")
                        else:
                            post.error_message = f"Unexpected publish response (story): {ig_response}"
                            errors.append(f"Post {post.id}: {post.error_message}")
                            print(f"[SCHEDULED] Post {post.id}: Unexpected publish response (story): {ig_response}")

                # If any side published, mark overall status as PUBLISHED
                if post.published_at_post or post.published_at_story:
                    post.status = PostStatus.PUBLISHED

                db.add(post)
                db.commit()
            except Exception as e:
                db.rollback()
                errors.append(f"Post {post.id}: {e}")
                print(f"[SCHEDULED] Post {post.id}: Error during publish: {e}")

        return len(scheduled_posts), published, errors
    finally:
        db.close()
