from datetime import datetime, timedelta
from app.services.trend_radar import get_trending_topics
from app.services.content_ai import generate_caption
from app.services.visual_ai import generate_image
from app.services.monetization import attach_affiliate
from worker.tasks import publish_post
from app.database import SessionLocal
from app.models import AutomationSetting, Account, Post, PostStatus
from app.services.content_ai import generate_hashtags, generate_image_prompt, generate_image_png_bytes
from app.services.storage_service import save_png_bytes_to_generated, upload_to_remote_server
from app.services.image_render import render_image
import json, os


def next_post_time():
    return datetime.utcnow() + timedelta(minutes=30)


def daily_post_cycle(accounts):
    for acc in accounts:
        topic = get_trending_topics()[0]
        caption = generate_caption(topic)
        caption = attach_affiliate(caption)
        image = generate_image(topic)

        payload = {"ig_user_id": acc.ig_user_id, "caption": caption, "image": image}

        publish_post.delay(payload)


def run_automation_check():
    """
    Check automation settings and generate drafts when needed.
    """
    db = SessionLocal()
    try:
        settings = db.query(AutomationSetting).filter(AutomationSetting.enabled == 1).all()
        if not settings:
            return
        now = datetime.utcnow()
        for s in settings:
            # hour window: use start_time/end_time (HH:MM) if present, else start_hour/end_hour
            def parse_time_str(t):
                if not t:
                    return None
                try:
                    parts = t.split(":")
                    h = int(parts[0])
                    m = int(parts[1]) if len(parts) > 1 else 0
                    return h * 60 + m
                except Exception:
                    return None

            start_minutes = parse_time_str(s.start_time) if s.start_time else (s.start_hour * 60 if s.start_hour is not None else 0)
            end_minutes = parse_time_str(s.end_time) if s.end_time else (s.end_hour * 60 if s.end_hour is not None else 23*60+59)
            now_minutes = now.hour*60 + now.minute
            if not (start_minutes <= now_minutes <= end_minutes):
                continue
            # determine counts already generated today (drafts created_at)
            acct = db.query(Account).filter(Account.id == s.account_id).first()
            if not acct:
                continue
            if s.frequency == "daily":
                target = s.daily_count or 1
                # count drafts today for this account
                day_start = datetime(now.year, now.month, now.day)
                cnt = db.query(Post).filter(Post.account_id == s.account_id, Post.created_at >= day_start).count()
                if cnt < target:
                    # generate one draft
                    topic = get_trending_topics()[0]
                    try:
                        caption = generate_caption(topic)
                    except Exception:
                        caption = f"Auto draft: {topic}"
                    try:
                        hashtags = generate_hashtags(topic, caption=caption, count=10)
                    except Exception:
                        hashtags = []
                    try:
                        image_prompt = generate_image_prompt(topic)
                        png_bytes = generate_image_png_bytes(image_prompt)
                        rel_bg, public_bg = save_png_bytes_to_generated(png_bytes)
                    except Exception:
                        public_bg = "https://images.pexels.com/photos/1032650/pexels-photo-1032650.jpeg"
                        rel_bg = None
                    # render final image (best effort)
                    public_url = public_bg
                    if rel_bg:
                        try:
                            BASE_DIR = os.getcwd()
                            background_full = os.path.join(BASE_DIR, "storage", rel_bg)
                            rel_final, abs_final = render_image(background_full, caption, "ince düşlerim", "minimal_dark")
                            with open(abs_final, "rb") as f:
                                final_bytes = f.read()
                            filename = os.path.basename(abs_final)
                            public_url = upload_to_remote_server(final_bytes, filename)
                        except Exception:
                            public_url = public_bg
                    post = Post(
                        account_id=s.account_id,
                        topic=topic,
                        caption=caption,
                        hashtags=json.dumps(hashtags),
                        image_prompt=image_prompt if 'image_prompt' in locals() else None,
                        image_url=public_url,
                        status=PostStatus.DRAFT,
                        created_at=datetime.utcnow(),
                    )
                    db.add(post)
                    s.last_run_at = datetime.utcnow()
                    db.add(s)
                    db.commit()
    finally:
        db.close()
