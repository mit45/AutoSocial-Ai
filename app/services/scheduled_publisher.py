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
        scheduled_posts = (
            db.query(Post)
            .filter(
                Post.status == PostStatus.APPROVED,
                Post.scheduled_at.isnot(None),
            )
            .all()
        )

        def scheduled_time_passed(p):
            s = p.scheduled_at
            if s is None:
                return False
            if isinstance(s, str):
                try:
                    s = datetime.fromisoformat(s.replace("Z", "+00:00"))
                except Exception:
                    return False
            if getattr(s, "tzinfo", None):
                s = s.astimezone(timezone.utc).replace(tzinfo=None)
            return s <= now

        due = [p for p in scheduled_posts if scheduled_time_passed(p)]
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

                # Eğer story ise caption zorunlu değildir; story için farklı akış:
                if post.type == PostType.STORY:
                    # Story için image_url zorunlu
                    if not image_url:
                        errors.append(
                            f"Post {post.id}: Story paylaşımı için image_url zorunludur"
                        )
                        continue
                    ig_response = publish_story(
                        image_url=image_url,
                        ig_user_id=ig_user_id,
                        access_token=access_token,
                    )
                else:
                    # Hazırla: caption + hashtag'ler (hashtag'ler DB'de JSON veya comma-separated olabilir)
                    hashtags_list = []
                    if post.hashtags:
                        try:
                            hashtags_list = json.loads(post.hashtags)
                        except Exception:
                            hashtags_list = [
                                h.strip()
                                for h in str(post.hashtags).split(",")
                                if h.strip()
                            ]

                    # format_post_text varsa kullan (caption + hashtag'ler), yoksa sadece caption
                    try:
                        from app.services.content_ai import format_post_text

                        final_caption = (
                            format_post_text(post.caption, hashtags_list)
                            if hashtags_list
                            else post.caption
                        )
                    except Exception:
                        final_caption = post.caption

                    ig_response = publish_image(
                        image_url=image_url,
                        caption=final_caption,
                        ig_user_id=ig_user_id,
                        access_token=access_token,
                    )

                # Normalize different instagram response shapes (image vs story)
                published_id = None
                # If error at top level
                if isinstance(ig_response, dict) and "error" in ig_response:
                    post.status = PostStatus.FAILED
                    post.error_message = str(
                        ig_response.get("error", {}).get("message", "Unknown error")
                    )
                    errors.append(f"Post {post.id}: {post.error_message}")
                    print(
                        f"[SCHEDULED] Post {post.id}: Publish failed: {post.error_message}"
                    )
                else:
                    # Try top-level id
                    if isinstance(ig_response, dict) and ig_response.get("id"):
                        published_id = str(ig_response.get("id"))
                    # Some flows return nested publish_response dict
                    elif isinstance(ig_response, dict) and isinstance(
                        ig_response.get("publish_response"), dict
                    ):
                        published_id = str(ig_response["publish_response"].get("id"))
                    # Some flows return nested creation_response with id (use as fallback)
                    elif isinstance(ig_response, dict) and isinstance(
                        ig_response.get("creation_response"), dict
                    ):
                        published_id = str(ig_response["creation_response"].get("id"))

                    if published_id:
                        post.status = PostStatus.PUBLISHED
                        post.published_at = datetime.utcnow()
                        post.ig_post_id = published_id
                        post.account_id = account.id
                        post.scheduled_at = None
                        post.error_message = None
                        published += 1
                        print(
                            f"[SCHEDULED] Post {post.id}: Published successfully (IG ID: {post.ig_post_id})"
                        )
                    else:
                        # Unexpected response shape -> treat as failure with raw dump
                        post.status = PostStatus.FAILED
                        post.error_message = (
                            f"Unexpected publish response: {ig_response}"
                        )
                        errors.append(f"Post {post.id}: {post.error_message}")
                        print(
                            f"[SCHEDULED] Post {post.id}: Unexpected publish response: {ig_response}"
                        )

                db.add(post)
                db.commit()
            except Exception as e:
                db.rollback()
                errors.append(f"Post {post.id}: {e}")
                print(f"[SCHEDULED] Post {post.id}: Error during publish: {e}")

        return len(scheduled_posts), published, errors
    finally:
        db.close()
