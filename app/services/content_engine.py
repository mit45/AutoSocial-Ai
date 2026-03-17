from __future__ import annotations

from typing import Any

from app.services.feedback_loop_engine import load_learning_state
from app.services.instagram_content_generator import generate_instagram_content


def generate_content_from_strategy_item(
    *,
    topic: str,
    content_type: str,
    learning_key: str = "global",
    db_path: str | None = None,
    hashtag_count: int = 10,
) -> dict[str, Any]:
    """
    Integration point:
    - loads learning_state
    - applies deterministic preferences (caption length) into content generation
    """
    learning_state = load_learning_state(db_path, key=learning_key)

    cap_w = (learning_state.get("caption_style") or {}) if isinstance(learning_state, dict) else {}
    short_w = float(cap_w.get("short", 0.0) or 0.0)
    long_w = float(cap_w.get("long", 0.0) or 0.0)
    # Prefer short if it clearly wins; prefer long if it clearly wins; otherwise neutral.
    prefer_short: bool | None
    if short_w >= long_w + 0.15:
        prefer_short = True
    elif long_w >= short_w + 0.15:
        prefer_short = False
    else:
        prefer_short = None

    return generate_instagram_content(
        topic=topic,
        content_type=content_type,
        prefer_short=prefer_short,
        hashtag_count=hashtag_count,
    )

