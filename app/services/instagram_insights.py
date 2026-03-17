import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import requests


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log(tag: str, msg: str) -> None:
    try:
        print(f"[{tag}] {msg}")
    except Exception:
        pass


def _parse_ig_timestamp(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if len(ts) >= 5 and (ts[-5] in ("+", "-")) and ts[-3] != ":":
            ts = ts[:-5] + ts[-5:-2] + ":" + ts[-2:]
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def metrics_for_media_type(media_type: str) -> tuple[str, str | None] | None:
    """
    Metrics selection based on Instagram Graph API docs.

    Updated for Graph API v22+ deprecations:
    - Prefer `views` over `impressions`
    - Keep `impressions` as fallback for older media where available
    - For reels: prefer `views`, fallback to `plays` (may be deprecated depending on version)
    """
    kind = (media_type or "IMAGE").upper()
    if kind in ("CAROUSEL_ALBUM", "CAROUSEL"):
        return None
    if kind in ("STORY", "STORIES"):
        return ("reach,replies,views", "reach,replies,impressions")
    if kind in ("REEL", "REELS"):
        return ("reach,likes,comments,saved,views", "reach,likes,comments,saved,plays")
    # IMAGE / VIDEO feed posts
    return ("reach,likes,comments,saved,views", "reach,likes,comments,saved,impressions")


@dataclass(frozen=True)
class InsightsResult:
    media_id: str
    media_type: str
    metrics: dict[str, Any]
    fetched_at: datetime
    raw_response: dict[str, Any] | None = None


def validate_media_access(media_id: str, access_token: str, *, api_base: str | None = None) -> bool:
    """
    Critical validation:
    - Confirms media_id is accessible and is a real IG Media object.
    - Detects common mistake: using creation_id/container_id instead of published media_id.
    """
    api_base = api_base or os.getenv("INSTAGRAM_GRAPH_API", "https://graph.facebook.com/v19.0")
    url = f"{api_base}/{media_id}"
    params = {"fields": "id,media_type,timestamp", "access_token": access_token}
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code != 200:
            try:
                _log("validate_media", f"FAIL media_id={media_id} status={r.status_code} response={r.text}")
            except Exception:
                pass
            return False
        return True
    except Exception as e:
        _log("validate_media", f"Exception media_id={media_id} error={e}")
        return False


def _request_with_retries(
    *,
    url: str,
    params: dict[str, Any],
    timeout_s: int = 20,
    max_retries: int = 5,
    backoff_base_s: float = 1.7,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[int, dict[str, Any]]:
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=timeout_s)
            body: dict[str, Any] = r.json() if r.text else {}
            if r.status_code == 200:
                return r.status_code, body

            _log("insights", f"HTTP {r.status_code} url={url} response={body}")
            error = (body or {}).get("error") or {}
            code = error.get("code")
            subcode = error.get("error_subcode")
            retryable = code in (1, 2, 4, 17, 613) or subcode in (2446079, 2446078)
            if not retryable:
                return r.status_code, body
        except Exception as e:
            last_exc = e
            _log("insights", f"Exception url={url} error={e}")

        sleep_s = backoff_base_s**attempt
        sleeper(min(30.0, sleep_s))

    if last_exc:
        raise last_exc
    return 0, {}


def fetch_media_insights(
    media_id: str,
    media_type: str,
    access_token: str,
    *,
    media_timestamp: str | None = None,
    skip_if_younger_than_s: int = 1800,
    api_base: str | None = None,
    timeout_s: int = 20,
) -> InsightsResult | None:
    """
    Fetch insights for a single media_id. Logs full API errors.
    Returns None when:
    - carousel album (no insights),
    - story likely expired (API may return empty data),
    - or API error (caller can decide what to do).
    """
    api_base = api_base or os.getenv("INSTAGRAM_GRAPH_API", "https://graph.facebook.com/v19.0")

    # Delay handling: new posts can take time before insights become available.
    ts_dt = _parse_ig_timestamp(media_timestamp)
    if ts_dt:
        age_s = (_utcnow() - ts_dt).total_seconds()
        if age_s < float(skip_if_younger_than_s):
            _log(
                "insights",
                f"skip media_id={media_id} media_type={media_type} reason=too_new age_s={int(age_s)}",
            )
            return None

    # Validate that media_id is accessible (helps catch container_id vs media_id bugs).
    if not validate_media_access(media_id, access_token, api_base=api_base):
        return None

    metric_pair = metrics_for_media_type(media_type)
    if metric_pair is None:
        _log("insights", f"skip media_id={media_id} media_type={media_type} reason=no_insights_for_carousel")
        return None

    url = f"{api_base}/{media_id}/insights"
    primary_metrics, fallback_metrics = metric_pair
    status, body = _request_with_retries(
        url=url,
        params={"access_token": access_token, "metric": primary_metrics},
        timeout_s=timeout_s,
    )

    # If primary failed, try fallback once (useful across API versions / media creation dates).
    if status != 200 and fallback_metrics:
        _log(
            "insights",
            f"primary failed media_id={media_id} media_type={media_type} status={status} metric={primary_metrics} body={body}",
        )
        status, body = _request_with_retries(
            url=url,
            params={"access_token": access_token, "metric": fallback_metrics},
            timeout_s=timeout_s,
        )

    if status != 200:
        # do not silently hide API errors
        _log(
            "insights",
            f"API error media_id={media_id} media_type={media_type} status={status} metrics={primary_metrics} fallback={fallback_metrics} body={body}",
        )
        return None

    out: dict[str, Any] = {}
    for item in (body.get("data") or []):
        name = item.get("name")
        values = item.get("values") or []
        if name and values:
            out[name] = values[0].get("value", 0)

    # If API returns empty dataset, treat as invalid for learning but log raw response.
    if not out:
        _log("insights", f"EMPTY metrics for media_id={media_id} media_type={media_type} body={body}")
        return None

    _log("metrics", f"media_id={media_id} media_type={media_type} metrics={out}")

    return InsightsResult(
        media_id=str(media_id),
        media_type=str(media_type or "IMAGE"),
        metrics=out,
        fetched_at=_utcnow(),
        raw_response=body,
    )

