from datetime import datetime, timedelta
from app.services.trend_radar import get_trending_topics
from app.services.content_ai import generate_caption
from app.services.visual_ai import generate_image
from app.services.monetization import attach_affiliate
from worker.tasks import publish_post


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
