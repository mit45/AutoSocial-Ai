import json
import math
import os
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


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


def init_feedback_db(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ig_learning_state (
              key TEXT PRIMARY KEY,
              state_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _safe_int(v: Any) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _parse_timestamp(ts: Any) -> datetime | None:
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


def _caption_len_bucket(n: int) -> str:
    if n <= 60:
        return "short"
    if n <= 180:
        return "medium"
    return "long"


@dataclass(frozen=True)
class ScoredPost:
    media_id: str
    media_type: str
    caption: str
    topic: str | None
    timestamp: datetime | None
    reach: int
    impressions: int
    likes: int
    comments: int
    saved: int
    engagement: int
    engagement_rate: float
    score: float
    weight: float  # decay weight


def calculate_score_from_metrics(metrics: dict[str, Any]) -> tuple[float, dict[str, int | float]]:
    """
    Core scoring function, based on user's definition:
        engagement = likes + comments + saved
        base = reach or impressions or plays or 1
        score = engagement / base
    Plus:
        - minimal floor > 0 to avoid degenerate all-zero scores
    """
    likes = _safe_int(metrics.get("likes"))
    comments = _safe_int(metrics.get("comments"))
    saved = _safe_int(metrics.get("saved"))
    reach = _safe_int(metrics.get("reach"))
    impressions = _safe_int(metrics.get("impressions"))
    plays = _safe_int(metrics.get("plays"))

    engagement = int(likes + comments + saved)
    base = reach or impressions or plays or 1
    raw = float(engagement) / float(base or 1)
    score = raw if raw > 0.0 else 0.01
    return score, {
        "engagement": engagement,
        "base": base,
        "likes": likes,
        "comments": comments,
        "saved": saved,
        "reach": reach,
        "impressions": impressions,
        "plays": plays,
        "raw": raw,
    }


def compute_performance_score(
    post: dict[str, Any],
    *,
    decay_half_life_days: float | None = 30.0,
    now: datetime | None = None,
) -> ScoredPost:
    """
    Deterministic scoring using calculate_score_from_metrics() plus decay weight.
    """
    now = now or _utcnow()
    media_id = _safe_str(post.get("media_id") or post.get("id"))
    media_type = (_safe_str(post.get("media_type") or "image")).lower()
    caption = _safe_str(post.get("caption") or "")
    topic = _safe_str(post.get("topic") or "") or None
    ts = _parse_timestamp(post.get("timestamp"))

    reach = _safe_int(post.get("reach"))
    impressions = _safe_int(post.get("impressions"))
    likes = _safe_int(post.get("likes"))
    comments = _safe_int(post.get("comments"))
    saved = _safe_int(post.get("saved"))

    score, debug = calculate_score_from_metrics(
        {
            "likes": likes,
            "comments": comments,
            "saved": saved,
            "reach": reach,
            "impressions": impressions,
            "plays": _safe_int(post.get("plays")),
        }
    )
    _log(
        "score",
        f"media_id={media_id} media_type={media_type} engagement={debug['engagement']} base={debug['base']} raw={debug['raw']:.6f} score={score:.6f}",
    )

    if decay_half_life_days and ts:
        age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
        weight = 0.5 ** (age_days / float(decay_half_life_days))
    else:
        weight = 1.0

    return ScoredPost(
        media_id=media_id,
        media_type=media_type,
        caption=caption,
        topic=topic,
        timestamp=ts,
        reach=int(debug["reach"]),
        impressions=int(debug["impressions"]),
        likes=int(debug["likes"]),
        comments=int(debug["comments"]),
        saved=int(debug["saved"]),
        engagement=int(debug["engagement"]),
        engagement_rate=float(debug["raw"]),
        score=float(score),
        weight=float(weight),
    )


def _weighted_avg(values: list[float], weights: list[float]) -> float:
    s = 0.0
    w = 0.0
    for v, wt in zip(values, weights, strict=False):
        s += float(v) * float(wt)
        w += float(wt)
    return (s / w) if w > 0 else 0.0


def _softmax_from_lifts(lifts: dict[str, float], *, temperature: float = 1.0) -> dict[str, float]:
    if not lifts:
        return {}
    # Stabilize by subtracting max
    mx = max(lifts.values())
    exps: dict[str, float] = {}
    for k, v in lifts.items():
        exps[k] = math.exp((float(v) - float(mx)) / max(1e-6, float(temperature)))
    s = sum(exps.values())
    if s <= 0:
        return {k: 0.0 for k in lifts}
    return {k: float(v) / float(s) for k, v in exps.items()}


def _normalize_scores(posts: list[ScoredPost]) -> list[float]:
    """
    Normalize to 0..1 using weighted percentiles (approx via sorting).
    """
    if not posts:
        return []
    sorted_posts = sorted(posts, key=lambda p: p.score)
    scores = [p.score for p in sorted_posts]
    # Min-max with safety; deterministic and explainable.
    mn = min(scores)
    mx = max(scores)
    if mx <= mn:
        return [0.5 for _ in scores]
    return [(s - mn) / (mx - mn) for s in scores]


def classify_posts(posts: list[ScoredPost]) -> dict[str, list[ScoredPost]]:
    """
    Quantile-based classification on normalized score:
    - HIGH_PERFORMING: top 25%
    - LOW_PERFORMING: bottom 25%
    - AVERAGE: middle 50%
    """
    if len(posts) < 4:
        return {"HIGH_PERFORMING": [], "AVERAGE": posts[:], "LOW_PERFORMING": []}

    sorted_posts = sorted(posts, key=lambda p: p.score)
    n = len(sorted_posts)
    q = max(1, int(n * 0.25))
    low = sorted_posts[:q]
    high = sorted_posts[-q:]
    avg = sorted_posts[q:-q]
    return {"HIGH_PERFORMING": high, "AVERAGE": avg, "LOW_PERFORMING": low}


def _extract_topic_key(post: ScoredPost) -> str | None:
    if post.topic:
        return post.topic.strip().lower()
    # fallback: first hashtag-like token
    m = None
    for token in post.caption.split():
        if token.startswith("#") and len(token) > 2:
            m = token[1:].lower()
            break
    return m


def learn_patterns_and_weights(
    posts: list[dict[str, Any]],
    *,
    decay_half_life_days: float | None = 30.0,
    min_posts: int = 12,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Main deterministic learning step.
    Returns:
      {
        winning_patterns: [...],
        losing_patterns: [...],
        learning_state: {...}
      }
    """
    now = now or _utcnow()
    scored = [compute_performance_score(p, decay_half_life_days=decay_half_life_days, now=now) for p in (posts or [])]
    scored = [p for p in scored if p.media_id]

    if len(scored) < min_posts:
        _log("feedback", f"not_enough_data posts={len(scored)} min_posts={min_posts}")
        return {
            "winning_patterns": [],
            "losing_patterns": [],
            "learning_state": default_learning_state(),
            "meta": {"reason": "not_enough_data", "posts": len(scored), "min_posts": min_posts},
        }

    groups = classify_posts(scored)
    high = groups["HIGH_PERFORMING"]
    low = groups["LOW_PERFORMING"]

    def _group_avg(g: list[ScoredPost]) -> float:
        return _weighted_avg([p.score for p in g], [p.weight for p in g])

    high_avg = _group_avg(high)
    low_avg = _group_avg(low)
    overall_avg = _weighted_avg([p.score for p in scored], [p.weight for p in scored])
    _log("feedback", f"posts={len(scored)} high={len(high)} low={len(low)} avg_score={overall_avg:.6f}")

    if overall_avg <= 0.0:
        _log("feedback", "WARNING: No valid insights data, skipping learning (avg_score == 0)")
        return {
            "winning_patterns": [],
            "losing_patterns": [],
            "learning_state": default_learning_state(),
            "meta": {"reason": "no_valid_insights", "posts": len(scored)},
        }

    # Feature lifts: value -> (avg_score(value) - overall_avg)
    lifts: dict[str, dict[str, float]] = {"media_type": {}, "caption_style": {}, "posting_hour": {}, "topic": {}}
    buckets: dict[str, dict[str, list[ScoredPost]]] = {
        "media_type": defaultdict(list),
        "caption_style": defaultdict(list),
        "posting_hour": defaultdict(list),
        "topic": defaultdict(list),
    }

    for p in scored:
        buckets["media_type"][p.media_type].append(p)
        buckets["caption_style"][_caption_len_bucket(len(p.caption))].append(p)
        hr = str(p.timestamp.hour) if p.timestamp else "unknown"
        buckets["posting_hour"][hr].append(p)
        tk = _extract_topic_key(p)
        if tk:
            buckets["topic"][tk].append(p)

    for feat, by_val in buckets.items():
        for val, items in by_val.items():
            if len(items) < 2:
                continue
            avg = _weighted_avg([x.score for x in items], [x.weight for x in items])
            lifts[feat][val] = float(avg - overall_avg)

    weights = {
        "media_type": _softmax_from_lifts(lifts["media_type"], temperature=0.7),
        "caption_style": _softmax_from_lifts(lifts["caption_style"], temperature=0.7),
        "posting_hour": _softmax_from_lifts(lifts["posting_hour"], temperature=0.9),
        # topics can be many; keep top 30 by weight
        "topic": {},
    }

    topic_w = _softmax_from_lifts(lifts["topic"], temperature=0.9)
    if topic_w:
        top_topics = sorted(topic_w.items(), key=lambda kv: kv[1], reverse=True)[:30]
        weights["topic"] = {k: float(v) for k, v in top_topics}

    # Build explainable patterns
    winning_patterns: list[str] = []
    losing_patterns: list[str] = []

    if weights["caption_style"]:
        best_style = max(weights["caption_style"].items(), key=lambda kv: kv[1])[0]
        worst_style = min(weights["caption_style"].items(), key=lambda kv: kv[1])[0]
        winning_patterns.append(f"{best_style} captions perform better (learned from your data)")
        losing_patterns.append(f"{worst_style} captions underperform (learned from your data)")

    if weights["media_type"]:
        best_mt = max(weights["media_type"].items(), key=lambda kv: kv[1])[0]
        worst_mt = min(weights["media_type"].items(), key=lambda kv: kv[1])[0]
        winning_patterns.append(f"{best_mt} outperforms other media types")
        losing_patterns.append(f"{worst_mt} underperforms other media types")

    # Best posting hours: take top 3 non-unknown
    best_hours = []
    if weights["posting_hour"]:
        for hr, w in sorted(weights["posting_hour"].items(), key=lambda kv: kv[1], reverse=True):
            if hr == "unknown":
                continue
            try:
                best_hours.append(int(hr))
            except Exception:
                continue
            if len(best_hours) >= 3:
                break
        if best_hours:
            winning_patterns.append(f"posts around {', '.join(str(h) for h in best_hours)}:00 perform better")

    # Construct learning state shape exactly as required
    learning_state = {
        "content_weights": {
            # map to user's required keys
            "reel": float(weights["media_type"].get("reel", 0.0)),
            "image": float(weights["media_type"].get("image", 0.0) + weights["media_type"].get("video", 0.0)),
            "story": float(weights["media_type"].get("story", 0.0)),
            "post": float(weights["media_type"].get("post", 0.0)),
        },
        "caption_style": {
            "short": float(weights["caption_style"].get("short", 0.0)),
            "medium": float(weights["caption_style"].get("medium", 0.0)),
            "long": float(weights["caption_style"].get("long", 0.0)),
        },
        "best_posting_hours": best_hours,
        "topic_weights": weights["topic"],
        "avoid_patterns": [],
        "meta": {
            "posts": len(scored),
            "high_avg_score": float(high_avg),
            "low_avg_score": float(low_avg),
            "decay_half_life_days": decay_half_life_days,
            "updated_at": _utcnow().isoformat(),
        },
    }

    return {
        "winning_patterns": winning_patterns,
        "losing_patterns": losing_patterns,
        "learning_state": learning_state,
    }


def default_learning_state() -> dict[str, Any]:
    return {
        "content_weights": {"reel": 0.4, "image": 0.4, "story": 0.2, "post": 0.0},
        "caption_style": {"short": 0.5, "medium": 0.3, "long": 0.2},
        "best_posting_hours": [],
        "topic_weights": {},
        "avoid_patterns": [],
        "meta": {"updated_at": _utcnow().isoformat(), "posts": 0},
    }


def load_learning_state(db_path: str | None = None, *, key: str = "global") -> dict[str, Any]:
    db_path = db_path or default_db_path()
    init_feedback_db(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT state_json FROM ig_learning_state WHERE key=?", (key,)).fetchone()
        if not row:
            return default_learning_state()
        try:
            return json.loads(row["state_json"])
        except Exception:
            return default_learning_state()
    finally:
        conn.close()


def save_learning_state(state: dict[str, Any], db_path: str | None = None, *, key: str = "global") -> None:
    db_path = db_path or default_db_path()
    init_feedback_db(db_path)
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO ig_learning_state(key, state_json, updated_at)
            VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET
              state_json=excluded.state_json,
              updated_at=excluded.updated_at
            """,
            (key, json.dumps(state, ensure_ascii=False), _utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def update_learning_state_from_posts(
    posts: list[dict[str, Any]],
    *,
    db_path: str | None = None,
    key: str = "global",
    decay_half_life_days: float | None = 30.0,
    min_posts: int = 12,
) -> dict[str, Any]:
    """
    Updates stored learning state after every batch.
    Deterministic: fully derived from the given batch (no hidden randomness).
    """
    db_path = db_path or default_db_path()
    prev = load_learning_state(db_path, key=key)
    learned = learn_patterns_and_weights(
        posts,
        decay_half_life_days=decay_half_life_days,
        min_posts=min_posts,
    )
    state = learned.get("learning_state") or default_learning_state()

    # If not enough or invalid data, keep previous state but update timestamp.
    meta = (learned.get("meta") or {}) if isinstance(learned, dict) else {}
    if meta.get("reason") in ("not_enough_data", "no_valid_insights"):
        prev["meta"] = prev.get("meta") or {}
        prev["meta"]["updated_at"] = _utcnow().isoformat()
        save_learning_state(prev, db_path, key=key)
        return {
            "learning_state": prev,
            "winning_patterns": [],
            "losing_patterns": [],
            "meta": meta,
        }

    save_learning_state(state, db_path, key=key)
    _log("weights", f"saved key={key} content_weights={state.get('content_weights')} caption_style={state.get('caption_style')}")
    return learned

