import os
import re
import requests

INSTAGRAM_API = "https://graph.facebook.com/v19.0"
# Uzun ömürlü access token'i .env üzerinden almayı tercih edin
ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_LONG_LIVED_TOKEN")


def get_instagram_account_id(access_token=None):
    """
    Access token kullanarak Instagram Business Account ID'yi alır

    Args:
        access_token: Instagram access token (optional)

    Returns:
        Instagram Business Account ID veya None
    """
    if access_token is None:
        access_token = ACCESS_TOKEN

    # Önce .env'den manuel olarak eklenmiş ID'yi kontrol et
    manual_id = os.getenv("INSTAGRAM_USER_ID")
    if manual_id:
        return manual_id

    # Otomatik olarak Facebook Page'den al
    url = f"{INSTAGRAM_API}/me/accounts"
    params = {"access_token": access_token}
    response = requests.get(url, params=params)

    if response.status_code == 200:
        data = response.json()
        pages = data.get("data", [])
        if pages:
            page_id = pages[0].get("id")
            # Page ID'den Instagram Business Account ID'yi al
            url = f"{INSTAGRAM_API}/{page_id}"
            params = {
                "access_token": access_token,
                "fields": "instagram_business_account",
            }
            response = requests.get(url, params=params)
            if response.status_code == 200:
                page_data = response.json()
                ig_account = page_data.get("instagram_business_account")
                if ig_account:
                    return ig_account.get("id")

    return None


def _caption_for_instagram(caption: str) -> str:
    """
    Caption'dan görsel prompt bölümünü kaldırır; sadece metin + hashtag'ler Instagram'a gider.
    """
    if not caption or not isinstance(caption, str):
        return caption or ""
    # "**Görsel Prompu:**", "Görsel Prompu:", "Görsel prompt:" ve sonrasını kaldır
    for pattern in [
        r"\*\*Görsel\s+Prompu\*\*:.*",
        r"Görsel\s+Prompu\s*:.*",
        r"Görsel\s+prompt\s*:.*",
        r"\*\*Görsel\s+prompt\*\*:.*",
    ]:
        caption = re.sub(pattern, "", caption, flags=re.IGNORECASE | re.DOTALL)
    return caption.strip()


def publish_image(image_url, caption, ig_user_id, access_token=None):
    """
    Publish an image to Instagram

    Args:
        image_url: URL of the image to publish
        caption: Caption for the post (görsel prompt metni otomatik çıkarılır)
        ig_user_id: Instagram user ID
        access_token: Instagram access token (optional, uses default if not provided)
    """
    if access_token is None:
        access_token = ACCESS_TOKEN

    caption = _caption_for_instagram(caption or "")

    # 1) Medya container oluştur (POST)
    # Validate image_url: prefer public uploads URL (umittopuz.com/uploads/ig)
    if not image_url or not isinstance(image_url, str):
        return {
            "error": {
                "message": "image_url is required and must be a string.",
                "code": "invalid_image_url",
            }
        }

    # Ensure image_url is a public HTTP(S) URL. Instagram requires a publicly accessible URL (prefer HTTPS).
    if not (
        isinstance(image_url, str)
        and (image_url.startswith("http://") or image_url.startswith("https://"))
    ):
        return {
            "error": {
                "message": "image_url must be a public HTTP(S) URL (e.g. https://.../file.png).",
                "code": "image_url_not_public",
            }
        }
    # Warn if not HTTPS
    if image_url.startswith("http://"):
        try:
            print(
                f"[WARNING][instagram.publish_image] image_url is not HTTPS: {image_url}"
            )
        except Exception:
            pass

    media_url = f"{INSTAGRAM_API}/{ig_user_id}/media"
    payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token,
    }
    # Debug log: request payload
    try:
        print(
            f"[DEBUG][instagram.publish_image] POST {media_url} payload: {{'image_url': '{image_url}', 'caption_present': {bool(caption)}}}"
        )
    except Exception:
        pass
    r_raw = requests.post(media_url, data=payload)
    try:
        r = r_raw.json()
    except Exception:
        r = {"raw_text": r_raw.text, "status_code": r_raw.status_code}
    # Debug log: response
    try:
        print(f"[DEBUG][instagram.publish_image] create response: {r}")
    except Exception:
        pass

    # Eğer container oluşturulamadıysa, ham hatayı geri döndür
    creation_id = r.get("id")
    if not creation_id:
        # Graph API'nin orijinal hata cevabını göster
        error_info = r.get("error", {})
        error_message = error_info.get("message", "Failed to create media container")
        error_code = error_info.get("code", "unknown")
        error_type = error_info.get("type", "unknown")

        # Token süresi dolmuşsa özel mesaj
        if error_code == 190:
            if (
                "expired" in error_message.lower()
                or "Session has expired" in error_message
            ):
                error_message = f"Instagram access token expired. Please refresh your token. Original: {error_message}"

        print(
            f"[ERROR] Instagram API error: {error_message} (code: {error_code}, type: {error_type})"
        )
        print(f"[ERROR] Full response: {r}")

        return {
            "error": {
                "message": error_message,
                "code": error_code,
                "type": error_type,
                "step": "create_media",
                "raw_response": r,
            }
        }

    # 2) Container'ı publish et
    publish_url = f"{INSTAGRAM_API}/{ig_user_id}/media_publish"
    publish_payload = {
        "creation_id": creation_id,
        "access_token": access_token,
    }
    try:
        print(
            f"[DEBUG][instagram.publish_image] POST {publish_url} payload: {{'creation_id': '{creation_id}'}}"
        )
    except Exception:
        pass
    rp_raw = requests.post(publish_url, data=publish_payload)
    try:
        rp = rp_raw.json()
    except Exception:
        rp = {"raw_text": rp_raw.text, "status_code": rp_raw.status_code}
    try:
        print(f"[DEBUG][instagram.publish_image] publish response: {rp}")
    except Exception:
        pass
    return rp


def publish_story(image_url, ig_user_id, access_token=None):
    """
    Publish a story to Instagram using the two-step container -> publish flow.
    Do NOT send a caption for stories.
    """
    if access_token is None:
        access_token = ACCESS_TOKEN

    # 1) Create media container (image) for STORY - include media_type=STORIES and do NOT send caption
    media_url = f"{INSTAGRAM_API}/{ig_user_id}/media"
    payload = {
        "image_url": image_url,
        "media_type": "STORIES",
        "access_token": access_token,
    }
    # Debug log: request payload
    try:
        print(
            f"[DEBUG][instagram.publish_story] POST {media_url} payload: {{'image_url': '{image_url}', 'media_type': 'STORIES'}}"
        )
    except Exception:
        pass
    r_raw = requests.post(media_url, data=payload)
    try:
        r = r_raw.json()
    except Exception:
        r = {"raw_text": r_raw.text, "status_code": r_raw.status_code}
    try:
        print(f"[DEBUG][instagram.publish_story] create response: {r}")
    except Exception:
        pass

    creation_id = r.get("id")
    if not creation_id:
        error_info = r.get("error", {})
        error_message = error_info.get(
            "message", "Failed to create media container for story"
        )
        error_code = error_info.get("code", "unknown")
        error_type = error_info.get("type", "unknown")
        # Token expiry friendly message
        if error_code == 190:
            if (
                "expired" in error_message.lower()
                or "Session has expired" in error_message
            ):
                error_message = f"Instagram access token expired. Please refresh your token. Original: {error_message}"

        print(
            f"[ERROR] Instagram API error (story create): {error_message} (code: {error_code}, type: {error_type})"
        )
        print(f"[ERROR] Full response: {r}")
        return {
            "error": {
                "message": error_message,
                "code": error_code,
                "type": error_type,
                "step": "create_media",
                "raw_response": r,
            }
        }

    # 2) Publish the created container (story)
    # 2) Publish the created container (story)
    # 2) Publish the created container (story)
    publish_url = f"{INSTAGRAM_API}/{ig_user_id}/media_publish"
    publish_payload = {"creation_id": creation_id, "access_token": access_token}
    try:
        print(
            f"[DEBUG][instagram.publish_story] POST {publish_url} payload: {{'creation_id': '{creation_id}'}}"
        )
    except Exception:
        pass
    rp_raw = requests.post(publish_url, data=publish_payload)
    try:
        rp = rp_raw.json()
    except Exception:
        rp = {"raw_text": rp_raw.text, "status_code": rp_raw.status_code}
    try:
        print(f"[DEBUG][instagram.publish_story] publish response: {rp}")
    except Exception:
        pass
    # Return both creation and publish responses for caller to handle/store
    return {"creation_id": creation_id, "creation_response": r, "publish_response": rp}
