import os
import re
import requests
from app.services import r2_storage

# Keep a configurable API version; v19 may be unavailable on some accounts. Fallback to v16.0 if not set.
INSTAGRAM_API = os.getenv("INSTAGRAM_GRAPH_API", "https://graph.facebook.com/v19.0")
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

    # Resolve ig_user_id if not provided
    if not ig_user_id:
        resolved = get_instagram_account_id(access_token)
        if not resolved:
            return {"error": {"message": "Instagram user id not found. Set INSTAGRAM_USER_ID or provide ig_user_id.", "code": "missing_ig_user_id"}}
        ig_user_id = resolved
    else:
        # If provided ig_user_id might be a Facebook Page id, try to resolve its instagram_business_account
        try:
            url_chk = f"{INSTAGRAM_API}/{ig_user_id}"
            resp_chk = requests.get(url_chk, params={"access_token": access_token, "fields": "instagram_business_account"})
            if resp_chk.status_code == 200:
                data_chk = resp_chk.json()
                if isinstance(data_chk, dict) and data_chk.get("instagram_business_account"):
                    ig_user_id = data_chk["instagram_business_account"].get("id") or ig_user_id
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
    # If image is on R2 and not publicly accessible, try to generate a presigned URL for Instagram to fetch
    try:
        from app.services import r2_storage
        presigned = r2_storage.generate_presigned_get_from_url(image_url, expires=300)
        if presigned:
            payload["image_url"] = presigned
            image_url = presigned
    except Exception:
        # ignore presigned generation errors and proceed with original URL
        pass

    r_raw = requests.post(media_url, data=payload)
    # Log raw response for easier debugging on API errors
    try:
        r = r_raw.json()
    except Exception:
        r = {"raw_text": r_raw.text, "status_code": r_raw.status_code}
    # If status is not 200, include raw text
    if getattr(r_raw, "status_code", None) and r_raw.status_code >= 400 and "error" not in r:
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
    # Attempt to publish with retries for transient "Media not ready" errors (code 9007)
    import time

    max_attempts = 5
    delay = 2.0
    last_resp = None
    for attempt in range(1, max_attempts + 1):
        rp_raw = requests.post(publish_url, data=publish_payload)
        try:
            rp = rp_raw.json()
        except Exception:
            rp = {"raw_text": rp_raw.text, "status_code": rp_raw.status_code}
        try:
            print(f"[DEBUG][instagram.publish_image] publish response (attempt {attempt}): {rp}")
        except Exception:
            pass
        last_resp = rp
        # If successful (id present) or non-transient error, break
        if isinstance(rp, dict) and rp.get("id"):
            break
        # Check for transient "Media not ready" error code 9007 / subcode 2207027
        err = rp.get("error") if isinstance(rp, dict) else None
        if err and err.get("code") == 9007:
            # wait and retry
            time.sleep(delay)
            delay = min(delay * 2, 10.0)
            continue
        # Other errors - no retry
        break
    return last_resp


def publish_story(image_url, ig_user_id, access_token=None):
    """
    Publish a story to Instagram using the two-step container -> publish flow.
    Do NOT send a caption for stories.
    """
    if access_token is None:
        access_token = ACCESS_TOKEN

    # 1) Create media container (image) for STORY - include media_type=STORIES and do NOT send caption
    # Resolve ig_user_id if missing
    if not ig_user_id:
        resolved = get_instagram_account_id(access_token)
        if not resolved:
            return {"error": {"message": "Instagram user id not found. Set INSTAGRAM_USER_ID or provide ig_user_id.", "code": "missing_ig_user_id"}}
        ig_user_id = resolved
    else:
        # If provided ig_user_id might be a Facebook Page id, try to resolve its instagram_business_account
        try:
            url_chk = f"{INSTAGRAM_API}/{ig_user_id}"
            resp_chk = requests.get(url_chk, params={"access_token": access_token, "fields": "instagram_business_account"})
            if resp_chk.status_code == 200:
                data_chk = resp_chk.json()
                if isinstance(data_chk, dict) and data_chk.get("instagram_business_account"):
                    ig_user_id = data_chk["instagram_business_account"].get("id") or ig_user_id
        except Exception:
            pass

    media_url = f"{INSTAGRAM_API}/{ig_user_id}/media"
    # Determine whether we must convert the provided image to a story canvas.
    try:
        from app.services.image_render import generate_story_image_from_post, make_story_from_post
        need_convert = False
        # If URL looks like a post or a local media, try to fetch and inspect size
        try:
            if isinstance(image_url, str) and image_url.startswith("http"):
                r = requests.get(image_url, timeout=10)
                r.raise_for_status()
                from io import BytesIO
                from PIL import Image as PILImage

                try:
                    im = PILImage.open(BytesIO(r.content))
                    w, h = im.size
                    # If square (approx 1:1) or width>=height, treat as post
                    if w == 1080 and h == 1080:
                        need_convert = True
                    elif abs((w / h) - 1.0) < 0.15:
                        need_convert = True
                except Exception:
                    # Could not parse image; fallback to URL heuristic
                    need_convert = ("ig/post" in image_url or "/media/" in image_url) and ("ig/story" not in image_url)
            else:
                # local path
                try:
                    p = Path(image_url)
                    if p.exists():
                        from PIL import Image as PILImage

                        im = PILImage.open(p)
                        w, h = im.size
                        if w == 1080 and h == 1080:
                            need_convert = True
                        elif abs((w / h) - 1.0) < 0.15:
                            need_convert = True
                    else:
                        need_convert = ("ig/post" in str(image_url) or "/media/" in str(image_url)) and (
                            "ig/story" not in str(image_url)
                        )
                except Exception:
                    need_convert = False
        except Exception:
            # fallback to heuristic if network/image read fails
            need_convert = False

        # If fetch/parsing didn't decide, fallback to URL pattern heuristics
        if not need_convert:
            try:
                s = str(image_url)
                if ("ig/post" in s or "/media/" in s or "/uploads/ig" in s or s.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))) and ("ig/story" not in s):
                    need_convert = True
            except Exception:
                need_convert = False
        # Log decision
        try:
            print(f"[LOG][STORY_CONVERT_DECISION] need_convert={need_convert} for image_url={image_url}")
        except Exception:
            pass

        if need_convert:
            try:
                print(f"[LOG][STORY_CONVERT] starting conversion for {image_url}")
                local_story = generate_story_image_from_post(image_url)
                print(f"[LOG][STORY_CONVERT] created local story at {local_story}")
                from app.services import storage_backend

                with open(local_story, "rb") as _f:
                    story_bytes = _f.read()
                filename = Path(local_story).name
                public = storage_backend.upload_to_remote_server(story_bytes, filename, prefix="ig/story")
                image_url = public
                print(f"[LOG][STORY_CONVERT] uploaded story to {image_url}")
            except Exception as ex_conv:
                print(f"[WARN][STORY_CONVERT] conversion failed: {ex_conv}")
                try:
                    story_url = make_story_from_post(image_url)
                    image_url = story_url
                    print(f"[LOG][STORY_CONVERT] fallback make_story_from_post returned {image_url}")
                except Exception as ex_f:
                    print(f"[WARN][STORY_CONVERT] fallback failed: {ex_f}")
                    pass
    except Exception:
        # image_render may not be available; continue
        pass

    # Use media_type=STORIES for story container; some API versions may require is_stories or no param.
    payload = {
        "image_url": image_url,
        "media_type": "STORIES",
        "access_token": access_token,
    }
    # Debug log: request payload (A)
    try:
        # Shorten access token for logs
        def _short_token(t):
            try:
                if not t:
                    return "None"
                s = str(t)
                if len(s) <= 12:
                    return s
                return f"{s[:6]}...{s[-4:]}"
            except Exception:
                return "err"

        print(
            f"[LOG][STORY_CREATE_REQUEST] image_url={image_url} media_type=STORIES access_token={_short_token(access_token)}"
        )
    except Exception:
        pass
    # If image is on R2 and not publicly accessible, try to generate a presigned URL for Instagram to fetch
    try:
        presigned = r2_storage.generate_presigned_get_from_url(image_url, expires=300)
        if presigned:
            payload["image_url"] = presigned
            image_url = presigned
    except Exception:
        # ignore presigned generation errors and proceed with original URL
        pass

    # Create media container with retry/backoff for transient errors (code==2 && is_transient==True)
    import time
    creation_id = None
    creation_response = None
    max_create_attempts = 6
    for create_attempt in range(1, max_create_attempts + 1):
        try:
            r_raw = requests.post(media_url, data=payload)
        except Exception as e:
            creation_response = {"error": {"message": f"request_failed: {e}"}}
            print(f"[LOG][STORY_CREATE_ATTEMPT {create_attempt}] request exception: {e}")
            # transient network error - apply backoff and retry
            if create_attempt < max_create_attempts:
                backoff = min(2 ** create_attempt, 16)
                print(f"[LOG][STORY_CREATE_ATTEMPT {create_attempt}] waiting {backoff}s before retry")
                time.sleep(backoff)
                continue
            else:
                print(f"[LOG][STORY_CREATE_ATTEMPT {create_attempt}] max attempts reached for create")
                break

        try:
            r = r_raw.json()
        except Exception:
            r = {"raw_text": r_raw.text, "status_code": getattr(r_raw, "status_code", None)}

        creation_response = r
        try:
            print(f"[LOG][STORY_CREATE_ATTEMPT {create_attempt}] response: {r}")
        except Exception:
            pass

        creation_id = r.get("id")
        if creation_id:
            # success
            print(f"[LOG][STORY_CREATE_ATTEMPT {create_attempt}] creation_id={creation_id}")
            break

        # check for transient error code==2 and is_transient==True
        err = r.get("error") if isinstance(r, dict) else None
        err_code = err.get("code") if isinstance(err, dict) else None
        is_transient = err.get("is_transient") if isinstance(err, dict) else False
        if err and err_code == 2 and is_transient:
            # exponential backoff: 1s,2s,4s,8s,16s...
            if create_attempt < max_create_attempts:
                backoff = min(2 ** (create_attempt - 1), 16)
                print(f"[LOG][STORY_CREATE_ATTEMPT {create_attempt}] transient error (code=2). waiting {backoff}s before retry")
                time.sleep(backoff)
                continue
            else:
                print(f"[LOG][STORY_CREATE_ATTEMPT {create_attempt}] max attempts reached for create (transient).")
                break
        else:
            # non-transient error -> return immediately
            error_info = err or {}
            error_message = error_info.get("message", "Failed to create media container for story")
            error_code = error_info.get("code", "unknown")
            error_type = error_info.get("type", "unknown")
            print(f"[ERROR] Instagram API error (story create): {error_message} (code: {error_code}, type: {error_type})")
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

    # After attempts, if still no creation_id, return error to caller
    if not creation_id:
        print(f"[ERROR] Story create failed after {max_create_attempts} attempts. Last response: {creation_response}")
        return {"error": {"message": "Story create failed after retries", "step": "create_media", "raw_response": creation_response}}

    # 2) Publish the created container (story)
    publish_url = f"{INSTAGRAM_API}/{ig_user_id}/media_publish"
    publish_payload = {"creation_id": creation_id, "access_token": access_token}

    # Publish request info (C) - whether creation_id present
    try:
        has_creation = bool(creation_id)
        print(f"[LOG][STORY_PUBLISH_REQUEST] creation_id_present={has_creation} creation_id={creation_id if has_creation else None}")
        print(f"[DEBUG][instagram.publish_story] POST {publish_url} payload: {{'creation_id': '{creation_id}'}}")
    except Exception:
        pass

    # Wait a minimum before first publish attempt (ensure media ready)
    import time
    try:
        time.sleep(3)
    except Exception:
        pass

    max_attempts = 6
    attempt = 0
    last_resp = None
    published_id = None
    while attempt < max_attempts:
        attempt += 1
        try:
            rp_raw = requests.post(publish_url, data=publish_payload)
        except Exception as e:
            rp = {"error": {"message": f"request_failed: {e}"}}
            print(f"[LOG][STORY_PUBLISH_ATTEMPT {attempt}] request exception: {e}")
            last_resp = rp
            # wait and retry
            time.sleep(3)
            continue

        try:
            rp = rp_raw.json()
        except Exception:
            rp = {"raw_text": rp_raw.text, "status_code": getattr(r_raw, "status_code", None)}

        # Log each attempt
        try:
            print(f"[LOG][STORY_PUBLISH_ATTEMPT {attempt}] response: {rp}")
        except Exception:
            pass

        last_resp = rp

        # Success case: publish returns id
        if isinstance(rp, dict) and rp.get("id"):
            published_id = str(rp.get("id"))
            print(f"[LOG][STORY_PUBLISH_ATTEMPT {attempt}] success publish_id={published_id}")
            break

        # Check for transient "Media not ready" error: require BOTH conditions
        err = rp.get("error") if isinstance(rp, dict) else None
        err_code = err.get("code") if isinstance(err, dict) else None
        err_subcode = err.get("error_subcode") if isinstance(err, dict) else None
        if err and err_code == 9007 and err_subcode == 2207027:
            # wait 3s and retry
            print(f"[LOG][STORY_PUBLISH_ATTEMPT {attempt}] transient media not ready (code={err_code} subcode={err_subcode}), waiting 3s before retry")
            time.sleep(3)
            continue

        # Non-transient error - stop retrying
        print(f"[LOG][STORY_PUBLISH_ATTEMPT {attempt}] non-retryable error, stopping: {err}")
        break

    # Return creation + publish info. If published_id present, include it.
    result = {"creation_id": creation_id, "creation_response": r, "publish_response": last_resp}
    if published_id:
        result["publish_id"] = published_id
    return result
