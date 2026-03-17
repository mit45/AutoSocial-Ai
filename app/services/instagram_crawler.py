import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import requests


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log(tag: str, msg: str) -> None:
    # Keep it simple: project uses print-based logging in services.
    try:
        print(f"[{tag}] {msg}")
    except Exception:
        pass


def _parse_ig_timestamp(ts: str | None) -> datetime | None:
    """
    Instagram timestamps are usually ISO8601, e.g. 2024-01-01T12:34:56+0000
    """
    if not ts or not isinstance(ts, str):
        return None
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        # Handle +0000 format
        if len(ts) >= 5 and (ts[-5] in ("+", "-")) and ts[-2:] != ":00" and ts[-3] != ":":
            # Convert ...+0000 -> ...+00:00
            ts = ts[:-5] + ts[-5:-2] + ":" + ts[-2:]
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _request_with_retries(
    *,
    url: str,
    params: dict[str, Any],
    timeout_s: int = 20,
    max_retries: int = 5,
    backoff_base_s: float = 1.5,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=timeout_s)
            body: dict[str, Any] = r.json() if r.text else {}
            if r.status_code == 200:
                return body

            # Log full API error response (do not silently fail)
            _log(
                "pagination",
                f"HTTP {r.status_code} url={url} params_keys={list(params.keys())} response={body}",
            )

            # Rate limit / transient error handling
            error = (body or {}).get("error") or {}
            code = error.get("code")
            subcode = error.get("error_subcode")
            # Common transient / throttling codes: 4 (Application request limit), 17 (User request limit),
            # 613 (Calls to this API have exceeded the rate limit), 1/2 (temporary)
            retryable = code in (1, 2, 4, 17, 613) or subcode in (2446079, 2446078)
            if not retryable:
                return body
        except Exception as e:
            last_exc = e
            _log("pagination", f"Exception url={url} error={e}")

        sleep_s = backoff_base_s**attempt
        sleeper(min(30.0, sleep_s))

    if last_exc:
        raise last_exc
    return {}


@dataclass(frozen=True)
class MediaItem:
    id: str
    media_type: str
    caption: str | None
    timestamp: str | None


def fetch_all_media(
    ig_user_id: str,
    access_token: str,
    *,
    api_base: str | None = None,
    fields: str = "id,media_type,caption,timestamp",
    page_limit: int = 100,
    max_pages: int | None = None,
) -> list[MediaItem]:
    """
    Full crawl: fetch ALL media using paging.next.
    """
    api_base = api_base or os.getenv("INSTAGRAM_GRAPH_API", "https://graph.facebook.com/v19.0")
    url = f"{api_base}/{ig_user_id}/media"
    params: dict[str, Any] = {"access_token": access_token, "fields": fields, "limit": page_limit}

    out: list[MediaItem] = []
    pages = 0
    while True:
        pages += 1
        body = _request_with_retries(url=url, params=params)
        data = body.get("data") or []
        for m in data:
            mid = m.get("id")
            if not mid:
                continue
            out.append(
                MediaItem(
                    id=str(mid),
                    media_type=str(m.get("media_type") or "IMAGE"),
                    caption=m.get("caption"),
                    timestamp=m.get("timestamp"),
                )
            )

        paging = body.get("paging") or {}
        next_url = paging.get("next")
        _log("media_crawler", f"page={pages} fetched={len(data)} total={len(out)} next={'yes' if next_url else 'no'}")

        if not next_url:
            break
        if max_pages is not None and pages >= max_pages:
            _log("media_crawler", f"max_pages reached={max_pages}; stopping pagination early")
            break

        # When using paging.next, the URL already includes all query params.
        url = next_url
        params = {}

    return out


def fetch_incremental_media(
    ig_user_id: str,
    access_token: str,
    *,
    api_base: str | None = None,
    fields: str = "id,media_type,caption,timestamp",
    page_limit: int = 100,
    since_ts: datetime | None = None,
    max_pages: int = 5,
) -> list[MediaItem]:
    """
    Incremental crawl: crawl from newest backwards until timestamps are older than since_ts.
    Stops early to reduce API usage.
    """
    api_base = api_base or os.getenv("INSTAGRAM_GRAPH_API", "https://graph.facebook.com/v19.0")
    url = f"{api_base}/{ig_user_id}/media"
    params: dict[str, Any] = {"access_token": access_token, "fields": fields, "limit": page_limit}

    out: list[MediaItem] = []
    pages = 0
    cutoff = since_ts
    while True:
        pages += 1
        body = _request_with_retries(url=url, params=params)
        data = body.get("data") or []

        stop = False
        for m in data:
            mid = m.get("id")
            if not mid:
                continue
            mts = _parse_ig_timestamp(m.get("timestamp"))
            if cutoff and mts and mts < cutoff:
                stop = True
                continue
            out.append(
                MediaItem(
                    id=str(mid),
                    media_type=str(m.get("media_type") or "IMAGE"),
                    caption=m.get("caption"),
                    timestamp=m.get("timestamp"),
                )
            )

        paging = body.get("paging") or {}
        next_url = paging.get("next")
        _log("media_crawler", f"inc_page={pages} kept={len(out)} next={'yes' if next_url else 'no'} stop={'yes' if stop else 'no'}")

        if stop or not next_url or pages >= max_pages:
            break
        url = next_url
        params = {}

    return out

