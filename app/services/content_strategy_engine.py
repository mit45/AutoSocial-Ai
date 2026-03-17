from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _log(tag: str, msg: str) -> None:
    try:
        print(f"[{tag}] {msg}")
    except Exception:
        pass


def _as_list(x: Any) -> list[Any]:
    if isinstance(x, list):
        return x
    return []


def _as_dict(x: Any) -> dict[str, Any]:
    if isinstance(x, dict):
        return x
    return {}


@dataclass(frozen=True)
class ContentIdea:
    type: str  # reel/post/story
    topic: str
    reason: str


def _pick_best_time_bucket(ai_insights: dict[str, Any]) -> str | None:
    meta = _as_dict(ai_insights.get("meta"))
    top_summary = _as_dict(meta.get("top_summary"))
    buckets = _as_dict(top_summary.get("posting_time_buckets"))
    if not buckets:
        return None
    best = max(buckets.items(), key=lambda kv: kv[1])[0]
    return str(best)


def _pick_winning_keywords(ai_insights: dict[str, Any], *, max_k: int = 8) -> list[str]:
    # Prefer explicit "top_only" winners if present; else fall back to top keywords from meta.
    winners: list[str] = []
    for p in _as_list(ai_insights.get("top_patterns")):
        pd = _as_dict(p)
        if pd.get("pattern") == "topics_keywords":
            ev = _as_dict(pd.get("evidence"))
            winners = [str(x) for x in _as_list(ev.get("top_only")) if str(x)]
            if winners:
                break
    if winners:
        return winners[:max_k]

    meta = _as_dict(ai_insights.get("meta"))
    top_summary = _as_dict(meta.get("top_summary"))
    kws = [str(x) for x in _as_list(top_summary.get("top_keywords")) if str(x)]
    return kws[:max_k]


def _has_pattern(ai_insights: dict[str, Any], pattern_name: str) -> bool:
    for p in _as_list(ai_insights.get("top_patterns")):
        if _as_dict(p).get("pattern") == pattern_name:
            return True
    for p in _as_list(ai_insights.get("bad_patterns")):
        if _as_dict(p).get("pattern") == pattern_name:
            return True
    return False


def _choose_types(ai_insights: dict[str, Any]) -> list[str]:
    """
    Simple policy:
    - If reels show as a theme (or you want growth): include reels
    - Always include at least one post and one story for distribution
    """
    types: list[str] = []
    # If reels patterns exist, bias to reels.
    if _has_pattern(ai_insights, "topics_keywords") or _has_pattern(ai_insights, "engagement_rate_gap"):
        types.extend(["reel", "reel"])
    else:
        types.append("reel")
    types.extend(["post", "story", "post"])
    return types[:5]


def build_content_strategy(
    ai_insights: dict[str, Any],
    *,
    ideas: int = 5,
    learning_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Input: AI insights (patterns + recommendations) from ai_insight_generator.py
    Output:
      {
        "content_plan": [
          {"type": "reel", "topic": "...", "reason": "..."},
          ...
        ]
      }

    Notes:
    - Generates *ideas*, not full captions/scripts/visuals.
    - Rule-based and deterministic enough to debug.
    """
    ai_insights = _as_dict(ai_insights)
    winners = _pick_winning_keywords(ai_insights)
    best_time = _pick_best_time_bucket(ai_insights)
    learning_state = _as_dict(learning_state or {})

    shorter_captions = any(
        _as_dict(p).get("pattern") == "shorter_captions" for p in _as_list(ai_insights.get("top_patterns"))
    )
    emotional = any(
        _as_dict(p).get("pattern") == "emotional_tone" for p in _as_list(ai_insights.get("top_patterns"))
    )

    style_bits: list[str] = []
    if shorter_captions:
        style_bits.append("keep the hook short")
    if emotional:
        style_bits.append("use an emotional hook/question")
    if best_time:
        style_bits.append(f"post in {best_time}")
    style = "; ".join(style_bits) if style_bits else "based on your top-performing patterns"

    # Apply feedback-loop weights if available.
    cw = _as_dict(learning_state.get("content_weights"))
    if cw:
        # Deterministic ordering: pick the highest-weight types first.
        ranked = sorted(cw.items(), key=lambda kv: float(kv[1] or 0.0), reverse=True)
        mapped: list[str] = []
        for k, _w in ranked:
            if k in ("reel", "post", "story"):
                mapped.append(k)
            elif k == "image":
                mapped.append("post")
        # Keep diversity and length=5
        types = (mapped + _choose_types(ai_insights))[:5]
    else:
        types = _choose_types(ai_insights)
    plan: list[ContentIdea] = []

    # Build topics: prefer learned topic_weights when present.
    topic_w = _as_dict(learning_state.get("topic_weights"))
    if topic_w:
        ranked_topics = [str(k) for k, _w in sorted(topic_w.items(), key=lambda kv: float(kv[1] or 0.0), reverse=True)]
        # Blend: learned topics first, then winners.
        winners = (ranked_topics + winners)[: max(8, len(winners))]

    # Build topics: use winning keywords if available; else generic placeholders.
    if not winners:
        winners = ["trend", "technology", "ai", "design", "science"]

    # Expand winners into idea topics with lightweight framing.
    topic_templates = [
        "3 quick takeaways about {kw}",
        "Common mistakes people make with {kw}",
        "Myth vs fact: {kw}",
        "A simple checklist for {kw}",
        "What changed recently in {kw} (and why it matters)",
    ]

    for i in range(max(1, int(ideas))):
        t = types[i % len(types)]
        kw = winners[i % len(winners)]
        topic = topic_templates[i % len(topic_templates)].format(kw=kw)
        reason = f"{style} (keyword='{kw}', format='{t}')"
        plan.append(ContentIdea(type=t, topic=topic, reason=reason))

    _log("content_strategy", f"ideas={len(plan)} winners={winners[:5]} best_time={best_time or 'n/a'}")

    return {"content_plan": [ci.__dict__ for ci in plan]}

