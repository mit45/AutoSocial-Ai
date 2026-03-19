from __future__ import annotations

import json
import time
from typing import Any

import requests

from app.services.instagram import INSTAGRAM_API, ACCESS_TOKEN
from app.services.storage_backend import generate_presigned_get_from_url


def _log(tag: str, msg: str) -> None:
    try:
        print(f"[{tag}] {msg}")
    except Exception:
        pass


def _json_preview(x: Any, max_len: int = 2000) -> str:
    try:
        s = json.dumps(x, ensure_ascii=False)
    except Exception:
        s = str(x)
    if len(s) > max_len:
        return s[:max_len] + "...(truncated)"
    return s


def _redact_access_token(token: Any) -> Any:
    if not isinstance(token, str):
        return token
    t = token.strip()
    if len(t) <= 10:
        return "***"
    return f"{t[:6]}...{t[-4:]}"


def create_reel_container(
    *,
    video_url: str,
    caption: str,
    ig_user_id: str,
    access_token: str | None = None,
    media_type: str = "REELS",
    retries: int = 3,
    backoff_s: float = 2.0,
) -> dict[str, Any]:
    """
    POST /{ig-user-id}/media (media_type=REELS) -> returns creation_id.
    """
    if access_token is None:
        access_token = ACCESS_TOKEN

    caption = str(caption or "").strip()
    video_url = str(video_url or "").strip()

    if not video_url:
        _log("reels_container", "create failed: video_url empty")
        return {"error": {"message": "video_url is required", "code": "invalid_video_url"}}
    if not ig_user_id:
        _log("reels_container", "create failed: ig_user_id empty")
        return {"error": {"message": "ig_user_id is required", "code": "invalid_ig_user_id"}}

    # Instagram servers need to fetch the file from a URL. If our R2 URL isn't public,
    # try a short-lived presigned URL.
    video_url_for_ig = generate_presigned_get_from_url(video_url, expires=3600) or video_url
    if video_url_for_ig != video_url:
        _log("reels", "using presigned video_url for IG fetch")

    create_url = f"{INSTAGRAM_API}/{ig_user_id}/media"
    payload: dict[str, Any] = {
        "media_type": media_type,
        "video_url": video_url_for_ig,
        "caption": caption,
        "access_token": access_token,
        "share_to_feed": "true",
    }

    for attempt in range(1, retries + 1):
        payload_for_log = dict(payload)
        payload_for_log["access_token"] = _redact_access_token(payload_for_log.get("access_token"))
        _log(
            "reels_container",
            f"create_attempt={attempt}/{retries} POST {create_url} payload={_json_preview(payload_for_log)}",
        )

        try:
            r_raw = requests.post(create_url, data=payload, timeout=60)
            status_code = getattr(r_raw, "status_code", None)
            try:
                body = r_raw.json()
            except Exception:
                body = {"raw_text": r_raw.text, "status_code": status_code}

            _log(
                "reels_container",
                f"create_response status={status_code} body={_json_preview(body)}",
            )

            creation_id = body.get("id") if isinstance(body, dict) else None
            if isinstance(body, dict) and r_raw.status_code and r_raw.status_code >= 400:
                # Token invalid / parameter errors won't magically fix with retries,
                # but we still retry for robustness when user sees transient errors.
                if attempt < retries:
                    time.sleep(backoff_s * attempt)
                    continue

            if not creation_id:
                return {
                    "error": {
                        "step": "create_reel_container",
                        "message": "Reels create failed",
                        "status_code": status_code,
                        "response": body,
                    }
                }

            return {
                "creation_id": str(creation_id),
                "creation_response": body,
            }
        except Exception as e:
            _log("reels_container", f"create_exception attempt={attempt} err={e}")
            if attempt < retries:
                time.sleep(backoff_s * attempt)
                continue
            return {"error": {"step": "create_reel_container", "message": str(e)}}

    return {"error": {"step": "create_reel_container", "message": "create failed (unknown)"}}


def check_container_status(
    *,
    creation_id: str,
    ig_user_id: str,
    access_token: str | None = None,
    target_status: str = "FINISHED",
    poll_s: float = 3.0,
    timeout_s: float = 90.0,
) -> dict[str, Any]:
    """
    GET /{creation_id}?fields=status_code until FINISHED (or timeout).
    """
    if access_token is None:
        access_token = ACCESS_TOKEN

    creation_id = str(creation_id or "").strip()
    if not creation_id:
        return {"error": {"step": "check_container_status", "message": "creation_id is required"}}

    url = f"{INSTAGRAM_API}/{creation_id}"
    params = {"fields": "status_code", "access_token": access_token}
    start = time.time()

    last_body: dict[str, Any] | None = None
    attempt = 0
    while time.time() - start <= timeout_s:
        attempt += 1
        _log("reels_status", f"status_poll={attempt} GET {url} params={_json_preview({'fields':'status_code'})}")
        try:
            r_raw = requests.get(url, params=params, timeout=30)
            status_code_http = getattr(r_raw, "status_code", None)
            try:
                body = r_raw.json()
            except Exception:
                body = {"raw_text": r_raw.text, "status_code": status_code_http}

            last_body = body if isinstance(body, dict) else {"response": body}
            _log(
                "reels_status",
                f"status_response http={status_code_http} body={_json_preview(last_body)}",
            )

            if isinstance(body, dict):
                sc = body.get("status_code")
                if isinstance(sc, str) and sc.upper() == target_status.upper():
                    return {"status_code": sc, "container_response": body}

                # If Graph returns an explicit error status, fail fast.
                if isinstance(sc, str) and sc.upper() not in (target_status.upper(), "IN_PROGRESS"):
                    return {
                        "error": {
                            "step": "check_container_status",
                            "message": "Reels container not finished",
                            "status_code": sc,
                            "response": body,
                        }
                    }
        except Exception as e:
            _log("reels_status", f"status_exception attempt={attempt} err={e}")

        time.sleep(poll_s)

    return {
        "error": {
            "step": "check_container_status",
            "message": "Timeout waiting for reels container FINISHED",
            "timeout_s": timeout_s,
            "last_response": last_body,
        }
    }


def publish_reel(
    *,
    ig_user_id: str,
    creation_id: str,
    access_token: str | None = None,
    retries: int = 3,
    backoff_s: float = 2.0,
) -> dict[str, Any]:
    """
    POST /{ig-user-id}/media_publish (creation_id).
    """
    if access_token is None:
        access_token = ACCESS_TOKEN
    ig_user_id = str(ig_user_id or "").strip()
    creation_id = str(creation_id or "").strip()

    if not ig_user_id or not creation_id:
        return {
            "error": {
                "step": "publish_reel",
                "message": "ig_user_id and creation_id are required",
                "ig_user_id": ig_user_id,
            }
        }

    publish_url = f"{INSTAGRAM_API}/{ig_user_id}/media_publish"

    last_body: dict[str, Any] | None = None
    for attempt in range(1, retries + 1):
        payload = {"creation_id": creation_id, "access_token": access_token}
        payload_for_log = dict(payload)
        payload_for_log["access_token"] = _redact_access_token(payload_for_log.get("access_token"))
        _log("reels_publish", f"publish_attempt={attempt}/{retries} POST {publish_url} payload={_json_preview(payload_for_log)}")
        try:
            rp_raw = requests.post(publish_url, data=payload, timeout=60)
            status_code_http = getattr(rp_raw, "status_code", None)
            try:
                body = rp_raw.json()
            except Exception:
                body = {"raw_text": rp_raw.text, "status_code": status_code_http}

            last_body = body if isinstance(body, dict) else {"response": body}
            _log(
                "reels_publish",
                f"publish_response http={status_code_http} body={_json_preview(last_body)}",
            )

            publish_id = None
            if isinstance(body, dict):
                publish_id = body.get("id") or (body.get("publish_response") or {}).get("id")
            if publish_id:
                return {
                    "publish_id": str(publish_id),
                    "publish_response": body,
                }

            err = body.get("error") if isinstance(body, dict) else None
            err_code = err.get("code") if isinstance(err, dict) else None
            err_subcode = err.get("error_subcode") if isinstance(err, dict) else None
            err_message = err.get("message") if isinstance(err, dict) else None

            retryable = False
            if err_code == 9007:
                retryable = True
            if err_subcode == 2207027:
                retryable = True
            if isinstance(err_message, str) and ("not ready" in err_message.lower() or "media not ready" in err_message.lower()):
                retryable = True

            if retryable and attempt < retries:
                time.sleep(backoff_s * attempt)
                continue

            return {
                "error": {
                    "step": "publish_reel",
                    "message": "Reels publish failed",
                    "status_code": status_code_http,
                    "response": body,
                }
            }
        except Exception as e:
            _log("reels_publish", f"publish_exception attempt={attempt} err={e}")
            if attempt < retries:
                time.sleep(backoff_s * attempt)
                continue
            return {"error": {"step": "publish_reel", "message": str(e)}}

    return {
        "error": {
            "step": "publish_reel",
            "message": "Reels publish failed (unknown)",
            "last_response": last_body,
        }
    }


def publish_reel_container_workflow(
    *,
    video_url: str,
    caption: str,
    ig_user_id: str,
    access_token: str | None = None,
    container_timeout_s: float = 90.0,
) -> dict[str, Any]:
    """
    Complete workflow: create container -> wait FINISHED -> publish.
    """
    _log("reels", "workflow_start")

    created = create_reel_container(
        video_url=video_url,
        caption=caption,
        ig_user_id=ig_user_id,
        access_token=access_token,
        retries=3,
    )
    if created.get("error"):
        return created

    creation_id = created.get("creation_id")
    assert isinstance(creation_id, str)

    status = check_container_status(
        creation_id=creation_id,
        ig_user_id=ig_user_id,
        access_token=access_token,
        timeout_s=container_timeout_s,
    )
    if status.get("error"):
        return {"error": status["error"], "creation_id": creation_id, "creation_response": created.get("creation_response")}

    published = publish_reel(
        ig_user_id=ig_user_id,
        creation_id=creation_id,
        access_token=access_token,
        retries=3,
    )
    if published.get("error"):
        return {
            "error": published["error"],
            "creation_id": creation_id,
            "creation_response": created.get("creation_response"),
        }

    return {
        "creation_id": creation_id,
        "creation_response": created.get("creation_response"),
        "status": status,
        "publish_response": published.get("publish_response"),
        "publish_id": published.get("publish_id"),
    }

