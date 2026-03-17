from __future__ import annotations

from typing import Any

from app.services.content_strategy_engine import build_content_strategy
from app.services.feedback_loop_engine import load_learning_state


def generate_content_plan(
    *,
    ai_insights: dict[str, Any],
    ideas: int = 5,
    learning_key: str = "global",
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Integration point:
    - loads learning_state from feedback loop storage
    - uses it inside content strategy generation
    """
    learning_state = load_learning_state(db_path, key=learning_key)
    return build_content_strategy(ai_insights, ideas=ideas, learning_state=learning_state)

