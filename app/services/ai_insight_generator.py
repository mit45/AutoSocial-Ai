import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _log(tag: str, msg: str) -> None:
    try:
        print(f"[{tag}] {msg}")
    except Exception:
        pass


def _safe_int(v: Any) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0


def _safe_float(v: Any) -> float:
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


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


def _caption_text(caption: Any) -> str:
    if not caption or not isinstance(caption, str):
        return ""
    return caption.strip()


def _caption_length_bucket(n: int) -> str:
    if n <= 0:
        return "empty"
    if n <= 60:
        return "very_short(0-60)"
    if n <= 140:
        return "short(61-140)"
    if n <= 300:
        return "medium(141-300)"
    return "long(301+)"


def _posting_time_bucket(dt: datetime | None) -> str:
    if not dt:
        return "unknown"
    h = dt.hour
    if 5 <= h <= 10:
        return "morning(05-10)"
    if 11 <= h <= 15:
        return "midday(11-15)"
    if 16 <= h <= 20:
        return "evening(16-20)"
    return "night(21-04)"


_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+", re.UNICODE)


def _extract_keywords(caption: str, *, max_keywords: int = 8) -> list[str]:
    """
    Lightweight, dependency-free keyword extraction:
    - hashtags are kept as topics (without '#')
    - otherwise: top frequent tokens length>=4
    """
    if not caption:
        return []
    hashtags = [h[1:].lower() for h in re.findall(r"#\w+", caption)]
    if hashtags:
        return hashtags[:max_keywords]

    tokens = [t.lower() for t in _TOKEN_RE.findall(caption) if len(t) >= 4]
    if not tokens:
        return []
    common = [w for (w, _) in Counter(tokens).most_common(max_keywords)]
    return common


def _detect_emotional_tone(caption: str) -> bool:
    """
    Very simple heuristic (no content generation).
    """
    if not caption:
        return False
    cues = (
        "!", "?", "şaş", "inan", "wow", "mükemmel", "harika", "şok", "sev", "nefret",
        "aşk", "mutlu", "üzgün", "kork", "heyecan"
    )
    s = caption.lower()
    return any(c in s for c in cues)


@dataclass(frozen=True)
class PostRow:
    caption: str
    media_type: str
    timestamp: datetime | None
    reach: int
    likes: int
    comments: int
    saved: int

    @property
    def engagement(self) -> int:
        return int(self.likes + self.comments + self.saved)

    @property
    def engagement_rate(self) -> float:
        denom = self.reach
        if denom <= 0:
            return 0.0
        return self.engagement / float(denom)


def _coerce_posts(posts: list[dict[str, Any]]) -> list[PostRow]:
    out: list[PostRow] = []
    for p in posts or []:
        caption = _caption_text(p.get("caption"))
        media_type = str(p.get("media_type") or "IMAGE")
        ts = _parse_timestamp(p.get("timestamp"))
        out.append(
            PostRow(
                caption=caption,
                media_type=media_type,
                timestamp=ts,
                reach=_safe_int(p.get("reach")),
                likes=_safe_int(p.get("likes")),
                comments=_safe_int(p.get("comments")),
                saved=_safe_int(p.get("saved")),
            )
        )
    return out


def _split_top_bottom(rows: list[PostRow], *, top_ratio: float = 0.25) -> tuple[list[PostRow], list[PostRow]]:
    rows2 = sorted(rows, key=lambda r: (r.engagement_rate, r.engagement), reverse=True)
    if not rows2:
        return [], []
    k = max(1, int(len(rows2) * float(top_ratio)))
    top = rows2[:k]
    bottom = rows2[-k:] if len(rows2) > 1 else []
    return top, bottom


def _avg(nums: list[float]) -> float:
    return (sum(nums) / len(nums)) if nums else 0.0


def generate_ai_insights_for_posts(posts: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Input:
      - list of posts with: caption, media_type, timestamp, reach, likes, comments, saved
    Output:
      {
        "top_patterns": [],
        "bad_patterns": [],
        "recommendations": []
      }

    NOTE: No content generation. Only analysis & pattern extraction.
    """
    rows = _coerce_posts(posts)
    if len(rows) < 4:
        return {
            "top_patterns": [],
            "bad_patterns": [],
            "recommendations": [],
            "meta": {"reason": "not_enough_data", "posts": len(rows)},
        }

    top, bottom = _split_top_bottom(rows)
    if not top or not bottom:
        return {
            "top_patterns": [],
            "bad_patterns": [],
            "recommendations": [],
            "meta": {"reason": "cannot_split_groups", "posts": len(rows)},
        }

    def summarize(group: list[PostRow]) -> dict[str, Any]:
        caps = [r.caption for r in group]
        cap_lens = [len(c) for c in caps]
        lens_bucket = Counter(_caption_length_bucket(n) for n in cap_lens)
        time_bucket = Counter(_posting_time_bucket(r.timestamp) for r in group)
        media_bucket = Counter((r.media_type or "IMAGE").upper() for r in group)
        emotional = sum(1 for r in group if _detect_emotional_tone(r.caption))
        kw = Counter()
        for r in group:
            kw.update(_extract_keywords(r.caption))
        return {
            "n": len(group),
            "avg_reach": _avg([float(r.reach) for r in group]),
            "avg_engagement": _avg([float(r.engagement) for r in group]),
            "avg_engagement_rate": _avg([float(r.engagement_rate) for r in group]),
            "caption_len_avg": _avg([float(x) for x in cap_lens]),
            "caption_len_buckets": dict(lens_bucket),
            "posting_time_buckets": dict(time_bucket),
            "media_type_buckets": dict(media_bucket),
            "emotional_ratio": emotional / float(len(group)) if group else 0.0,
            "top_keywords": [w for (w, _) in kw.most_common(10)],
        }

    top_s = summarize(top)
    bot_s = summarize(bottom)

    _log("ai_insights", f"top_n={top_s['n']} bottom_n={bot_s['n']} total={len(rows)}")

    top_patterns: list[dict[str, Any]] = []
    bad_patterns: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    # Pattern: caption length
    if top_s["caption_len_avg"] and bot_s["caption_len_avg"]:
        diff = float(top_s["caption_len_avg"]) - float(bot_s["caption_len_avg"])
        if abs(diff) >= 40:
            if diff < 0:
                top_patterns.append(
                    {
                        "pattern": "shorter_captions",
                        "statement": "Shorter captions correlate with higher engagement rate in your data.",
                        "evidence": {
                            "top_caption_len_avg": top_s["caption_len_avg"],
                            "bottom_caption_len_avg": bot_s["caption_len_avg"],
                        },
                    }
                )
                recommendations.append(
                    {
                        "recommendation": "Try shorter captions more often (test <= 140 chars).",
                        "why": "Your top-performing group has shorter captions on average.",
                    }
                )
            else:
                top_patterns.append(
                    {
                        "pattern": "longer_captions",
                        "statement": "Longer captions correlate with higher engagement rate in your data.",
                        "evidence": {
                            "top_caption_len_avg": top_s["caption_len_avg"],
                            "bottom_caption_len_avg": bot_s["caption_len_avg"],
                        },
                    }
                )

    # Pattern: emotional tone
    emo_diff = float(top_s["emotional_ratio"]) - float(bot_s["emotional_ratio"])
    if abs(emo_diff) >= 0.25:
        if emo_diff > 0:
            top_patterns.append(
                {
                    "pattern": "emotional_tone",
                    "statement": "Captions with emotional cues correlate with better performance.",
                    "evidence": {"top_ratio": top_s["emotional_ratio"], "bottom_ratio": bot_s["emotional_ratio"]},
                }
            )
            recommendations.append(
                {
                    "recommendation": "Test more emotional hooks (questions, surprise, strong opening).",
                    "why": "Emotional-cue captions are more common in your top-performing group.",
                }
            )
        else:
            bad_patterns.append(
                {
                    "pattern": "emotional_tone_overuse",
                    "statement": "Emotional cues appear more in low-performing captions.",
                    "evidence": {"top_ratio": top_s["emotional_ratio"], "bottom_ratio": bot_s["emotional_ratio"]},
                }
            )

    # Pattern: posting time
    def _dominant_bucket(buckets: dict[str, Any]) -> str | None:
        if not buckets:
            return None
        return max(buckets.items(), key=lambda kv: kv[1])[0]

    top_time = _dominant_bucket(top_s["posting_time_buckets"])
    bot_time = _dominant_bucket(bot_s["posting_time_buckets"])
    if top_time and bot_time and top_time != bot_time:
        top_patterns.append(
            {
                "pattern": "posting_time",
                "statement": f"Top posts are more concentrated in {top_time} compared to low performers ({bot_time}).",
                "evidence": {"top_buckets": top_s["posting_time_buckets"], "bottom_buckets": bot_s["posting_time_buckets"]},
            }
        )
        recommendations.append(
            {
                "recommendation": f"Run an A/B test posting more in {top_time}.",
                "why": "Your top group clusters more in that time bucket.",
            }
        )

    # Pattern: topics/keywords
    top_kw = set(top_s["top_keywords"][:8])
    bot_kw = set(bot_s["top_keywords"][:8])
    if top_kw:
        winners = sorted(list(top_kw - bot_kw))[:8]
        if winners:
            top_patterns.append(
                {
                    "pattern": "topics_keywords",
                    "statement": "Certain topics/keywords show up more in top posts.",
                    "evidence": {"top_keywords": top_s["top_keywords"][:10], "bottom_keywords": bot_s["top_keywords"][:10], "top_only": winners},
                }
            )
            recommendations.append(
                {
                    "recommendation": "Create more posts around the top-only keywords and monitor engagement rate.",
                    "why": "These keywords are more present in top-performing posts than low performers.",
                }
            )

    # Pattern: engagement rate gap
    if float(top_s["avg_engagement_rate"]) >= float(bot_s["avg_engagement_rate"]) * 1.5 and bot_s["avg_engagement_rate"] > 0:
        top_patterns.append(
            {
                "pattern": "engagement_rate_gap",
                "statement": "There is a large performance gap between top and low posts.",
                "evidence": {"top_avg_er": top_s["avg_engagement_rate"], "bottom_avg_er": bot_s["avg_engagement_rate"]},
            }
        )

    # Bad patterns: empty/very long captions in bottom group
    bottom_len_buckets = bot_s["caption_len_buckets"] or {}
    if bottom_len_buckets.get("empty", 0) >= max(1, int(bot_s["n"] * 0.25)):
        bad_patterns.append(
            {
                "pattern": "missing_captions",
                "statement": "Low-performing posts often have missing/empty captions.",
                "evidence": {"bottom_caption_len_buckets": bottom_len_buckets},
            }
        )
        recommendations.append(
            {"recommendation": "Avoid posting without a caption (even a short hook helps).", "why": "Empty captions cluster in low performers."}
        )

    return {
        "top_patterns": top_patterns,
        "bad_patterns": bad_patterns,
        "recommendations": recommendations,
        "meta": {
            "posts": len(rows),
            "top_n": top_s["n"],
            "bottom_n": bot_s["n"],
            "top_summary": top_s,
            "bottom_summary": bot_s,
        },
    }

