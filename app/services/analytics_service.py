import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.instagram_crawler import MediaItem, fetch_all_media, fetch_incremental_media
from app.services.instagram_insights import InsightsResult, fetch_media_insights


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log(tag: str, msg: str) -> None:
    try:
        print(f"[{tag}] {msg}")
    except Exception:
        pass


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def default_db_path() -> str:
    return os.getenv("INSTAGRAM_ANALYTICS_DB", os.path.join("data", "instagram_analytics.sqlite"))


def _connect(db_path: str) -> sqlite3.Connection:
    _ensure_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_analytics_db(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ig_media (
              media_id TEXT PRIMARY KEY,
              media_type TEXT NOT NULL,
              caption TEXT,
              timestamp TEXT,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ig_insights (
              media_id TEXT PRIMARY KEY,
              media_type TEXT NOT NULL,
              metrics_json TEXT NOT NULL,
              fetched_at TEXT NOT NULL,
              raw_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ig_media_ts ON ig_media(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ig_insights_fetched ON ig_insights(fetched_at)")
        conn.commit()
    finally:
        conn.close()


def clean_invalid_insights_cache(db_path: str) -> None:
    """
    Remove clearly invalid / empty metrics rows from cache.
    """
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM ig_insights WHERE metrics_json IS NULL OR trim(metrics_json) = '' OR trim(metrics_json) = '{}' "
        )
        deleted = cur.rowcount
        if deleted:
            _log("cache", f"clean_invalid_insights_cache removed_rows={deleted}")
        conn.commit()
    finally:
        conn.close()


def upsert_media(db_path: str, items: list[MediaItem]) -> None:
    conn = _connect(db_path)
    try:
        now = _utcnow().isoformat()
        conn.executemany(
            """
            INSERT INTO ig_media(media_id, media_type, caption, timestamp, updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(media_id) DO UPDATE SET
              media_type=excluded.media_type,
              caption=excluded.caption,
              timestamp=excluded.timestamp,
              updated_at=excluded.updated_at
            """,
            [(m.id, m.media_type, m.caption, m.timestamp, now) for m in items],
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_media_timestamp(db_path: str) -> datetime | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT timestamp FROM ig_media WHERE timestamp IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        ts = row["timestamp"]
        try:
            # Best-effort parse
            if isinstance(ts, str):
                if ts.endswith("Z"):
                    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if len(ts) >= 5 and (ts[-5] in ("+", "-")) and ts[-3] != ":":
                    ts = ts[:-5] + ts[-5:-2] + ":" + ts[-2:]
                return datetime.fromisoformat(ts)
        except Exception:
            return None
        return None
    finally:
        conn.close()


def get_cached_insights(db_path: str, media_id: str, *, max_age_hours: int = 12) -> dict[str, Any] | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT metrics_json, fetched_at FROM ig_insights WHERE media_id=?",
            (media_id,),
        ).fetchone()
        if not row:
            return None
        fetched_at = row["fetched_at"]
        try:
            fetched_dt = datetime.fromisoformat(fetched_at)
        except Exception:
            fetched_dt = _utcnow() - timedelta(days=365)
        if _utcnow() - fetched_dt > timedelta(hours=max_age_hours):
            _log("cache", f"stale cache media_id={media_id} age_hours>{max_age_hours}")
            return None
        try:
            return json.loads(row["metrics_json"])
        except Exception:
            return None
    finally:
        conn.close()


def set_cached_insights(db_path: str, result: InsightsResult) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO ig_insights(media_id, media_type, metrics_json, fetched_at, raw_json)
            VALUES(?,?,?,?,?)
            ON CONFLICT(media_id) DO UPDATE SET
              media_type=excluded.media_type,
              metrics_json=excluded.metrics_json,
              fetched_at=excluded.fetched_at,
              raw_json=excluded.raw_json
            """,
            (
                result.media_id,
                result.media_type,
                json.dumps(result.metrics or {}, ensure_ascii=False),
                result.fetched_at.isoformat(),
                json.dumps(result.raw_response or {}, ensure_ascii=False) if result.raw_response else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def refresh_pipeline(
    ig_user_id: str,
    access_token: str,
    *,
    db_path: str | None = None,
    full_sync: bool = False,
    cache_max_age_hours: int = 12,
    api_base: str | None = None,
) -> dict[str, Any]:
    """
    Orchestrates:
    Instagram API -> crawler -> pagination -> insights -> SQLite cache
    """
    db_path = db_path or default_db_path()
    init_analytics_db(db_path)
    clean_invalid_insights_cache(db_path)

    if full_sync:
        media = fetch_all_media(ig_user_id, access_token, api_base=api_base)
    else:
        since = get_latest_media_timestamp(db_path)
        # If we never synced, do a full sync once.
        if since is None:
            media = fetch_all_media(ig_user_id, access_token, api_base=api_base)
        else:
            # Pull a small window of newest items (incremental).
            media = fetch_incremental_media(ig_user_id, access_token, api_base=api_base, since_ts=since, max_pages=8)

    upsert_media(db_path, media)

    fetched = 0
    cached = 0
    errors = 0

    for m in media:
        existing = get_cached_insights(db_path, m.id, max_age_hours=cache_max_age_hours)
        if existing is not None:
            cached += 1
            continue

        res = fetch_media_insights(
            m.id,
            m.media_type,
            access_token,
            api_base=api_base,
            media_timestamp=m.timestamp,
            skip_if_younger_than_s=1800,
        )
        if res is None:
            errors += 1
            continue
        set_cached_insights(db_path, res)
        fetched += 1

    _log("pipeline", f"media={len(media)} insights_fetched={fetched} cached={cached} errors={errors}")
    return {"media": len(media), "insights_fetched": fetched, "cached": cached, "errors": errors, "db_path": db_path}


@dataclass(frozen=True)
class NormalizedMetrics:
    reach: int
    likes: int
    comments: int
    saved: int
    impressions: int
    plays: int
    replies: int
    views: int


def _normalize_metrics(metrics: dict[str, Any] | None) -> NormalizedMetrics:
    metrics = metrics or {}
    def _int(name: str) -> int:
        v = metrics.get(name, 0)
        try:
            return int(v or 0)
        except Exception:
            return 0

    return NormalizedMetrics(
        reach=_int("reach"),
        likes=_int("likes"),
        comments=_int("comments"),
        saved=_int("saved"),
        impressions=_int("impressions"),
        plays=_int("plays"),
        replies=_int("replies"),
        views=_int("views"),
    )


def _engagement(n: NormalizedMetrics) -> int:
    return int(n.likes + n.comments + n.saved + n.replies)


def _engagement_rate(n: NormalizedMetrics) -> float:
    denom = n.reach or n.impressions or n.views or n.plays
    if denom <= 0:
        return 0.0
    return _engagement(n) / float(denom)


def build_dashboard_output(
    *,
    db_path: str | None = None,
    limit_top_posts: int = 10,
    days: int = 90,
) -> dict[str, Any]:
    """
    Dashboard-ready JSON:
    {
      total_posts,
      avg_engagement,
      top_posts,
      reels_performance,
      growth_metrics
    }
    """
    db_path = db_path or default_db_path()
    init_analytics_db(db_path)

    conn = _connect(db_path)
    try:
        since_dt = _utcnow() - timedelta(days=days)
        rows = conn.execute(
            """
            SELECT m.media_id, m.media_type, m.caption, m.timestamp, i.metrics_json
            FROM ig_media m
            LEFT JOIN ig_insights i ON i.media_id = m.media_id
            WHERE m.timestamp IS NULL OR m.timestamp >= ?
            ORDER BY m.timestamp DESC
            """,
            (since_dt.isoformat(),),
        ).fetchall()
    finally:
        conn.close()

    items: list[dict[str, Any]] = []
    reels: list[dict[str, Any]] = []
    total_eng = 0
    total_reach = 0

    for r in rows:
        metrics = {}
        try:
            if r["metrics_json"]:
                metrics = json.loads(r["metrics_json"])
        except Exception:
            metrics = {}
        n = _normalize_metrics(metrics)
        er = _engagement_rate(n)

        total_eng += _engagement(n)
        total_reach += n.reach

        item = {
            "media_id": r["media_id"],
            "media_type": r["media_type"],
            "timestamp": r["timestamp"],
            "caption": r["caption"],
            "metrics": metrics,
            "engagement": _engagement(n),
            "engagement_rate": er,
        }
        items.append(item)
        if str(r["media_type"] or "").upper() in ("REEL", "REELS"):
            reels.append(item)

    items_sorted = sorted(items, key=lambda x: (x.get("engagement_rate") or 0.0, x.get("engagement") or 0), reverse=True)
    top_posts = items_sorted[: max(1, int(limit_top_posts))]

    avg_engagement = (total_eng / len(items)) if items else 0.0
    avg_engagement_rate = (
        sum((it.get("engagement_rate") or 0.0) for it in items) / len(items)
        if items
        else 0.0
    )

    reels_perf = {
        "count": len(reels),
        "avg_engagement_rate": (
            sum((it.get("engagement_rate") or 0.0) for it in reels) / len(reels) if reels else 0.0
        ),
        "top_reels": sorted(reels, key=lambda x: (x.get("engagement_rate") or 0.0), reverse=True)[:5],
    }

    growth_metrics = {
        # Placeholder without follower history: can be extended later with daily snapshots.
        "total_reach": total_reach,
        "avg_likes": (sum((_normalize_metrics(it.get("metrics")).likes for it in items)) / len(items)) if items else 0.0,
        "avg_comments": (sum((_normalize_metrics(it.get("metrics")).comments for it in items)) / len(items)) if items else 0.0,
    }

    return {
        "total_posts": len(items),
        "avg_engagement": avg_engagement,
        "avg_engagement_rate": avg_engagement_rate,
        "top_posts": top_posts,
        "reels_performance": reels_perf,
        "growth_metrics": growth_metrics,
        "days": days,
    }


def get_cached_media_with_insights(
    *,
    db_path: str | None = None,
    limit: int = 50,
    days: int = 365,
) -> list[dict[str, Any]]:
    """
    Returns cached media + insights from SQLite for use in the insights panel.
    Shape is compatible with /api/instagram/published (insights + comments keys).
    """
    db_path = db_path or default_db_path()
    init_analytics_db(db_path)

    conn = _connect(db_path)
    try:
        since_dt = _utcnow() - timedelta(days=days)
        rows = conn.execute(
            """
            SELECT m.media_id, m.media_type, m.caption, m.timestamp, i.metrics_json
            FROM ig_media m
            LEFT JOIN ig_insights i ON i.media_id = m.media_id
            WHERE m.timestamp IS NULL OR m.timestamp >= ?
            ORDER BY m.timestamp DESC
            LIMIT ?
            """,
            (since_dt.isoformat(), int(limit)),
        ).fetchall()
    finally:
        conn.close()

    media: list[dict[str, Any]] = []
    for r in rows:
        metrics: dict[str, Any] = {}
        try:
            if r["metrics_json"]:
                metrics = json.loads(r["metrics_json"])
        except Exception:
            metrics = {}
        if not metrics:
            _log("insights", f"EMPTY metrics in cache for media_id={r['media_id']}; panel will show 'İstatistik alınamadı'")
        media.append(
            {
                "id": r["media_id"],
                "caption": r["caption"],
                "media_type": r["media_type"],
                "media_url": None,
                "timestamp": r["timestamp"],
                "insights": metrics,
                "comments": [],
            }
        )
    return media


def build_posts_for_feedback(
    *,
    db_path: str | None = None,
    days: int = 90,
) -> list[dict[str, Any]]:
    """
    Prepare posts dicts (with metrics) from cache for feedback loop engine.
    """
    db_path = db_path or default_db_path()
    init_analytics_db(db_path)

    conn = _connect(db_path)
    try:
        since_dt = _utcnow() - timedelta(days=days)
        rows = conn.execute(
            """
            SELECT m.media_id, m.media_type, m.caption, m.timestamp, i.metrics_json
            FROM ig_media m
            LEFT JOIN ig_insights i ON i.media_id = m.media_id
            WHERE m.timestamp IS NULL OR m.timestamp >= ?
            ORDER BY m.timestamp DESC
            """,
            (since_dt.isoformat(),),
        ).fetchall()
    finally:
        conn.close()

    posts: list[dict[str, Any]] = []
    for r in rows:
        metrics: dict[str, Any] = {}
        try:
            if r["metrics_json"]:
                metrics = json.loads(r["metrics_json"])
        except Exception:
            metrics = {}
        if not metrics:
            _log("insights", f"EMPTY metrics in cache for feedback media_id={r['media_id']}")
        posts.append(
            {
                "media_id": r["media_id"],
                "media_type": r["media_type"],
                "caption": r["caption"],
                "topic": None,
                "timestamp": r["timestamp"],
                "reach": metrics.get("reach", 0),
                "impressions": metrics.get("impressions", 0),
                "likes": metrics.get("likes", 0),
                "comments": metrics.get("comments", 0),
                "saved": metrics.get("saved", 0),
            }
        )
    return posts

