from __future__ import annotations

from typing import Any

from app.services.content_ai import (
    _format_avoid_similar_block,
    extra_viral_caption_instructions,
    generate_hashtags,
    get_client,
)


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
    engagement_pack: dict[str, Any] | None = None,
    avoid_similar_to: list[str] | None = None,
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
    extra = ""
    if engagement_pack and isinstance(engagement_pack, dict):
        rs = str(engagement_pack.get("research_summary_tr") or "").strip()
        hk = str(engagement_pack.get("scroll_hook_tr") or "").strip()
        bd = str(engagement_pack.get("body_angle_tr") or "").strip()
        cta = str(engagement_pack.get("soft_cta_tr") or "").strip()
        av = engagement_pack.get("avoid_tr")
        avs = ", ".join(str(x) for x in (av or [])[:6]) if isinstance(av, list) else ""
        if rs or hk:
            extra = (
                "\nStrateji / araştırma notları (yazıya yansıt):\n"
                f"- Özet: {rs}\n"
                f"- Güçlü açılış fikri: {hk}\n"
                f"- Gövde odağı: {bd}\n"
                f"- Yumuşak CTA: {cta}\n"
            )
            if avs:
                extra += f"- Kaçın: {avs}\n"

    prompt = (
        "Türkçe olarak Instagram için bir caption yaz.\n\n"
        f"Konu: {topic_choice}\n"
        f"Format: {t}\n"
        f"Yapı: {structure}\n\n"
        "Okunabilirlik:\n"
        "- İlk satır dikkat çeksin ama clickbait veya alaycı ton kullanma.\n"
        "- Ses ve giriş stratejisi aşağıda verilenlere uy; her üretimde farklı his versin.\n"
        "- Son satırda net bir CTA (soru, kaydet, paylaş) — zorlamadan.\n"
        "- Satırlar kısa ve ritimli; madde işareti listesi kullanma.\n"
        "- Emoji en fazla 2.\n"
        "- Hashtag yazma.\n"
        f"- Maksimum {max_chars} karakteri hedefle.\n"
        + extra_viral_caption_instructions()
        + extra
        + "\n"
        "Sadece caption metnini döndür."
    )

    if avoid_similar_to:
        cleaned = [x for x in avoid_similar_to if (x or "").strip()]
        if cleaned:
            prompt = prompt + _format_avoid_similar_block(cleaned)

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.88,
        frequency_penalty=0.75,
        presence_penalty=0.5,
    )
    caption = (resp.choices[0].message.content or "").strip()

    image_prompt = generate_visual_prompt(topic_choice, t)
    if engagement_pack and str(engagement_pack.get("visual_direction_en") or "").strip():
        image_prompt = (
            image_prompt
            + " "
            + str(engagement_pack["visual_direction_en"]).strip()
        )
    hf = None
    if engagement_pack:
        hf = str(engagement_pack.get("hashtag_focus_tr") or "").strip() or None
    hashtags = generate_hashtags(
        topic_choice,
        caption=caption,
        count=int(hashtag_count),
        engagement_focus=hf,
    )

    _log("content_gen", f"type={t} topic='{topic_choice}' caption_len={len(caption)} hashtags={len(hashtags)}")
    return {"caption": caption, "image_prompt": image_prompt, "hashtags": hashtags}

