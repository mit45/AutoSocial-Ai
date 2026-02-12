from celery import Celery
from app.services.instagram import publish_image
from app.config import REDIS_URL

celery_app = Celery("autosocial", broker=REDIS_URL)


@celery_app.task
def publish_post(payload):
    return publish_image(
        payload["image"],
        payload["caption"],
        payload["ig_user_id"],
        payload["access_token"],
    )
