from __future__ import annotations

from typing import Any

from app.services.content_ai import KOMIK_USLUP, generate_hashtags, get_client


def _log(tag: str, msg: str) -> None:
    try:
        print(f"[{tag}] {msg}")
    except Exception:
        pass


def _normalize_type(t: str) -> str:
    tl = (t or "").strip().lower()
    if tl in ("reel", "reels"):
        return "reel"
    if tl in ("story", "stories"):
        return "story"
    return "post"


def _caption_style_for_type(content_type: str, *, prefer_short: bool | None = None) -> dict[str, Any]:
    """
    Returns generation constraints only (no content).
    """
    t = _normalize_type(content_type)
    if t == "story":
        return {
            "format": "VERY_SHORT",
            "max_chars": 140 if prefer_short is not False else 220,
            "structure": "Hook (1 line) + CTA (1 line).",
        }
    if t == "reel":
        return {
            "format": "SHORT",
            "max_chars": 220 if prefer_short is not False else 380,
            "structure": "Hook (1 line) + 2-4 bullets + CTA (1 line).",
        }
    # post
    return {
        "format": "MEDIUM" if prefer_short is False else "SHORT_OR_MEDIUM",
        "max_chars": 450 if prefer_short is False else 300,
        "structure": "Hook (1 line) + 2-5 short lines + CTA (1 line).",
    }


def generate_visual_prompt(topic: str, content_type: str) -> str:
    """
    Deterministic, production-friendly visual prompt template (no readable text).
    Works with image generators (DALL·E, SDXL etc).
    """
    t = _normalize_type(content_type)
    vibe = {
        "reel": "high-energy, modern, dynamic motion feel",
        "story": "minimal, clean, high readability, calm",
        "post": "high-quality, editorial, balanced composition",
    }[t]
    return (
        "Square 1:1 Instagram background image, no readable text, no logos. "
        f"Theme inspired by: {topic}. "
        f"Style: {vibe}. "
        "Include a clear centered negative space for an overlaid caption, strong contrast, "
        "simple shapes or subtle texture, professional lighting, high resolution."
    )


def generate_instagram_content(
    *,
    topic: str,
    content_type: str,
    prefer_short: bool | None = None,
    hashtag_count: int = 10,
) -> dict[str, Any]:
    """
    Input:
      - topic
      - content_type: reel | post | story

    Output:
      {
        "caption": "...",
        "image_prompt": "...",
        "hashtags": [...]
      }
    """
    t = _normalize_type(content_type)
    topic_choice = (topic or "").strip() or "bilim ve teknoloji"

    style = _caption_style_for_type(t, prefer_short=prefer_short)
    max_chars = int(style["max_chars"])
    structure = str(style["structure"])

    client = get_client()
    prompt = (
        "Türkçe olarak Instagram için bir caption yaz.\n\n"
        f"Konu: {topic_choice}\n"
        f"Format: {t}\n"
        f"Yapı: {structure}\n\n"
        "Engagement optimizasyonu:\n"
        "- İlk satır güçlü bir HOOK olsun (merak/sürpriz/soru).\n"
        "- Son satır net bir CTA olsun (yorum sorusu, kaydet, paylaş).\n"
        "- Satırlar kısa, okunabilir olsun.\n"
        "- Emoji: 1-3 adet, abartma.\n"
        "- Hashtag yazma.\n"
        f"- Maksimum {max_chars} karakteri hedefle.\n"
        + KOMIK_USLUP
        + "\n"
        "Sadece caption metnini döndür."
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        frequency_penalty=0.5,
        presence_penalty=0.4,
    )
    caption = (resp.choices[0].message.content or "").strip()

    image_prompt = generate_visual_prompt(topic_choice, t)
    hashtags = generate_hashtags(topic_choice, caption=caption, count=int(hashtag_count))

    _log("content_gen", f"type={t} topic='{topic_choice}' caption_len={len(caption)} hashtags={len(hashtags)}")
    return {"caption": caption, "image_prompt": image_prompt, "hashtags": hashtags}

