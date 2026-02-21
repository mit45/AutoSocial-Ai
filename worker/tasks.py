from celery import Celery
from app.services.instagram import publish_image, publish_story
from app.config import REDIS_URL, BASE_URL
from app.database import SessionLocal
from app.models import Account
import socket
from urllib.parse import urlparse

# Create Celery app; we'll switch to eager mode if Redis broker is not reachable (dev fallback).
celery_app = Celery("autosocial", broker=REDIS_URL)


def _redis_available(redis_url: str) -> bool:
    try:
        parsed = urlparse(redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        with socket.create_connection((host, port), timeout=1):
            return True
    except Exception:
        return False


# If Redis is not reachable, run tasks eagerly (synchronous) so automation still works in local dev.
if not _redis_available(REDIS_URL):
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    print("[CELERY] Redis broker not reachable at", REDIS_URL, "- enabling eager mode for local development.")


@celery_app.task
def publish_post(payload):
    # Ensure access_token present: prefer payload, else DB lookup by ig_user_id, else env fallback
    access_token = payload.get("access_token")
    ig_user_id = payload.get("ig_user_id")
    if not access_token:
        try:
            db = SessionLocal()
            acct = None
            if payload.get("account_id"):
                acct = db.query(Account).filter(Account.id == int(payload.get("account_id"))).first()
            elif ig_user_id:
                acct = db.query(Account).filter(Account.ig_user_id == str(ig_user_id)).first()
            if acct and acct.access_token:
                access_token = acct.access_token
        except Exception:
            access_token = None
        finally:
            try:
                db.close()
            except Exception:
                pass
    # fallback to env-configured token
    if not access_token:
        from app.config import INSTAGRAM_ACCESS_TOKEN as ENV_TOKEN

        access_token = ENV_TOKEN or None

    result = publish_image(
        payload.get("image"),
        payload.get("caption"),
        payload.get("ig_user_id"),
        access_token,
    )
    # Idempotency: if post_id provided and DB already shows published, skip duplicate handling.
    try:
        post_id = payload.get("post_id")
        if post_id:
            db_check = SessionLocal()
            from app.models import Post as PostModel, PostStatus as PostStatusModel
            existing = db_check.query(PostModel).filter(PostModel.id == int(post_id)).first()
            if existing:
                if existing.status == PostStatusModel.PUBLISHED and existing.ig_post_id_post:
                    # Already published by another path — return early with informative result
                    db_check.close()
                    return {"info": "already_published", "post_id": post_id, "ig_post_id_post": existing.ig_post_id_post}
            db_check.close()
    except Exception:
        pass
    # If post_id provided, update DB record accordingly
    try:
        post_id = payload.get("post_id")
        if post_id:
            db = SessionLocal()
            from app.models import Post, PostStatus
            from datetime import datetime

            p = db.query(Post).filter(Post.id == int(post_id)).first()
            if p:
                # success -> response may contain 'id' or error
                if isinstance(result, dict):
                    res_id = result.get("id")
                    if res_id:
                        p.status = PostStatus.PUBLISHED  # type: ignore[assignment]
                        p.published_at = datetime.utcnow()  # type: ignore[assignment]
                        p.ig_post_id_post = str(res_id)  # type: ignore[assignment]
                        db.add(p)
                        db.commit()
                    elif result.get("error"):
                        p.status = PostStatus.FAILED  # type: ignore[assignment]
                        p.error_message = str(result.get("error"))
                        db.add(p)
                        db.commit()
    except Exception:
        try:
            db.close()
        except Exception:
            pass
    return result
@celery_app.task
def publish_story_task(payload):
    """
    Payload: { image_url: str, ig_user_id: str, access_token: str }
    """
    # Ensure access_token present as above
    access_token = payload.get("access_token")
    ig_user_id = payload.get("ig_user_id")
    if not access_token:
        try:
            db = SessionLocal()
            acct = None
            if payload.get("account_id"):
                acct = db.query(Account).filter(Account.id == int(payload.get("account_id"))).first()
            elif ig_user_id:
                acct = db.query(Account).filter(Account.ig_user_id == str(ig_user_id)).first()
            if acct and acct.access_token:
                access_token = acct.access_token
        except Exception:
            access_token = None
        finally:
            try:
                db.close()
            except Exception:
                pass
    if not access_token:
        from app.config import INSTAGRAM_ACCESS_TOKEN as ENV_TOKEN

        access_token = ENV_TOKEN or None

    result = publish_story(payload.get("image_url"), payload.get("ig_user_id"), access_token=access_token)
    # Idempotency: if post_id provided and DB already shows story published, skip duplicate handling.
    try:
        post_id = payload.get("post_id")
        if post_id:
            db_check = SessionLocal()
            from app.models import Post as PostModel, PostStatus as PostStatusModel
            existing = db_check.query(PostModel).filter(PostModel.id == int(post_id)).first()
            if existing:
                if existing.status == PostStatusModel.PUBLISHED and existing.ig_post_id_story:
                    db_check.close()
                    return {"info": "already_published_story", "post_id": post_id, "ig_post_id_story": existing.ig_post_id_story}
            db_check.close()
    except Exception:
        pass
    # Update DB if post_id provided
    try:
        post_id = payload.get("post_id")
        if post_id:
            db = SessionLocal()
            from app.models import Post, PostStatus
            from datetime import datetime

            p = db.query(Post).filter(Post.id == int(post_id)).first()
            if p:
                # success -> publish might return publish_id or publish_response with 'id'
                publish_id = None
                if isinstance(result, dict):
                    publish_id = result.get("publish_id")
                    if not publish_id:
                        publish_resp = result.get("publish_response")
                        if isinstance(publish_resp, dict):
                            publish_id = publish_resp.get("id")
                if publish_id:
                    p.status = PostStatus.PUBLISHED  # type: ignore[assignment]
                    p.published_at = datetime.utcnow()  # type: ignore[assignment]
                    p.ig_post_id_story = str(publish_id)  # type: ignore[assignment]
                    db.add(p)
                    db.commit()
                elif isinstance(result, dict) and result.get("error"):
                    p.status = PostStatus.FAILED  # type: ignore[assignment]
                    p.error_message = str(result.get("error"))
                    db.add(p)
                    db.commit()
    except Exception:
        try:
            db.close()
        except Exception:
            pass
    return result
