"""
Araştırma / strateji katmanı: otomatik içerikleri Instagram etkileşimi için güçlendirir.

- OpenAI ile konuya özgü açı, hook, görsel yön ve hashtag odağı üretir (canlı web yok; genel ilkeler + mantık).
- feedback_loop_engine öğrenilen ağırlıkları (caption uzunluğu, en iyi saatler vb.) prompta ekler.

Kapatmak için: CONTENT_ENGAGEMENT_BOOST=0
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.services.content_ai import get_client
from app.services.feedback_loop_engine import (
    default_db_path,
    default_learning_state,
    init_feedback_db,
    load_learning_state,
)

ENGAGEMENT_UI_KEY = "engagement_ui"


def is_engagement_boost_enabled() -> bool:
    v = (os.getenv("CONTENT_ENGAGEMENT_BOOST") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def persist_engagement_pack_for_ui(topic: str, content_type: str, pack: dict[str, Any]) -> None:
    """Son başarılı strateji paketini analytics DB'de saklar; dashboard kırmızı metni buradan beslenir."""
    if not pack:
        return
    try:
        blob: dict[str, Any] = {
            "topic": (topic or "")[:200],
            "content_type": (content_type or "")[:80],
            "research_summary_tr": str(pack.get("research_summary_tr") or "").strip()[:500],
            "hook_tr": str(pack.get("scroll_hook_tr") or "").strip()[:220],
            "body_angle_tr": str(pack.get("body_angle_tr") or "").strip()[:220],
            "cta_tr": str(pack.get("soft_cta_tr") or "").strip()[:160],
            "visual_direction_en": str(pack.get("visual_direction_en") or "").strip()[:320],
            "hashtag_focus_tr": str(pack.get("hashtag_focus_tr") or "").strip()[:200],
            "avoid_tr": [str(x) for x in (pack.get("avoid_tr") or [])[:4] if str(x).strip()],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        line_bits: list[str] = []
        if blob["research_summary_tr"]:
            line_bits.append(blob["research_summary_tr"])
        if blob["hook_tr"]:
            line_bits.append("Önerilen açılış: " + blob["hook_tr"])
        if blob["body_angle_tr"]:
            line_bits.append("Metin odağı: " + blob["body_angle_tr"])
        if blob["cta_tr"]:
            line_bits.append("Etkileşim daveti: " + blob["cta_tr"])
        if blob["visual_direction_en"]:
            line_bits.append("Görsel yön (İng.): " + blob["visual_direction_en"][:180])
        if blob["hashtag_focus_tr"]:
            line_bits.append("Hashtag odağı: " + blob["hashtag_focus_tr"])
        if blob["avoid_tr"]:
            line_bits.append("Kaçınılan kalıplar: " + ", ".join(blob["avoid_tr"]))
        blob["summary_line_tr"] = " ".join(line_bits)[:900]

        db_path = default_db_path()
        init_feedback_db(db_path)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                INSERT INTO ig_learning_state(key, state_json, updated_at)
                VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                  state_json=excluded.state_json,
                  updated_at=excluded.updated_at
                """,
                (ENGAGEMENT_UI_KEY, json.dumps(blob, ensure_ascii=False), blob["updated_at"]),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        try:
            print(f"[ENGAGEMENT_UI] persist failed: {e}")
        except Exception:
            pass


def load_engagement_ui_for_api() -> dict[str, Any] | None:
    try:
        db_path = default_db_path()
        init_feedback_db(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT state_json FROM ig_learning_state WHERE key=?",
                (ENGAGEMENT_UI_KEY,),
            ).fetchone()
            if not row:
                return None
            data = json.loads(row["state_json"])
            return data if isinstance(data, dict) else None
        finally:
            conn.close()
    except Exception:
        return None


def _compact_learning_for_prompt(learning_state: dict[str, Any] | None) -> str:
    ls = learning_state if isinstance(learning_state, dict) else default_learning_state()
    cap = ls.get("caption_style") or {}
    summary = {
        "caption_style_weights": cap,
        "content_format_weights": ls.get("content_weights") or {},
        "best_posting_hours_utc_hint": (ls.get("best_posting_hours") or [])[:5],
        "top_topics_sample": list((ls.get("topic_weights") or {}).keys())[:8],
        "insights_posts": (ls.get("meta") or {}).get("posts"),
    }
    try:
        return json.dumps(summary, ensure_ascii=False)[:2800]
    except Exception:
        return "{}"


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner: list[str] = []
        for line in lines[1:]:
            if line.strip() == "```":
                break
            inner.append(line)
        text = "\n".join(inner).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        raise


def build_engagement_pack(
    topic: str,
    content_type: str,
    learning_state: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Tek LLM çağrısıyla strateji paketi üretir. Başarısız olursa None.
    """
    if not is_engagement_boost_enabled():
        return None
    topic = (topic or "").strip() or "bilim ve teknoloji"
    content_type = (content_type or "ilginç_bilgi").strip()
    ls = learning_state if learning_state is not None else load_learning_state()
    learning_blob = _compact_learning_for_prompt(ls)

    client = get_client()
    sys_user = f"""Sen içerik stratejisti ve öğretici Instagram editörüsün. Canlı web veya arama erişimin yok.
Genel olarak bilinen psikoloji, içerik tüketimi ve platform davranışlarından yararlan.
Uydurma istatistik, sahte kaynak adı, kesin tarih/sayı yazma; iddiaları mütevazı tut.

Konu (Türkçe): {topic}
İçerik türü (sistem anahtarı): {content_type}

Hesaptan öğrenilen sinyaller (JSON, karışık veri olabilir):
{learning_blob}

Yalnızca geçerli bir JSON nesnesi döndür. Anahtarlar:
- "research_summary_tr": string, 2-3 cümle — bu konuda insanların durup okumasını sağlayan "neden önemli / merak" düzlemi.
- "scroll_hook_tr": string, tek cümülük güçlü açılış fikri (clickbait yok, manipülasyon yok).
- "body_angle_tr": string, gövdede anlatılacak tek net bilgi/çerçeve.
- "soft_cta_tr": string, yorum veya kaydet için nazik davet (1 kısa cümle).
- "visual_direction_en": string, İngilizce 2 cümle — görsel üretici için: net özne, ışık, ruh hali, 1:1 kompozisyon, metin yok; scroll'da seçilebilir ama ucuz stok hissi vermesin.
- "hashtag_focus_tr": string, 4-10 niş anahtar kelime (boşlukla ayrılmış, # yok).
- "avoid_tr": string array — bu konuda kaçınılacak klişe ifade veya görsel kalıplar (en fazla 4 öğe).

Türkçe alanlarda yasak ton: alay, küçümseme, absürt şok başlığı, "kimse söylemiyor" kalıbı."""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": sys_user}],
            temperature=0.72,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
        data = _parse_json_object(raw)
        if not isinstance(data, dict):
            return None
        # normalise keys
        out = {
            "research_summary_tr": str(data.get("research_summary_tr") or "").strip(),
            "scroll_hook_tr": str(data.get("scroll_hook_tr") or "").strip(),
            "body_angle_tr": str(data.get("body_angle_tr") or "").strip(),
            "soft_cta_tr": str(data.get("soft_cta_tr") or "").strip(),
            "visual_direction_en": str(data.get("visual_direction_en") or "").strip(),
            "hashtag_focus_tr": str(data.get("hashtag_focus_tr") or "").strip(),
            "avoid_tr": data.get("avoid_tr") if isinstance(data.get("avoid_tr"), list) else [],
        }
        if not (out["scroll_hook_tr"] or out["body_angle_tr"]):
            return None
        try:
            print(f"[ENGAGEMENT_BOOST] topic='{topic[:50]}...' pack_ok=1")
        except Exception:
            pass
        try:
            persist_engagement_pack_for_ui(topic, content_type, out)
        except Exception:
            pass
        return out
    except Exception as e:
        try:
            print(f"[ENGAGEMENT_BOOST] failed: {e}")
        except Exception:
            pass
        return None


def caption_length_hint_from_learning(learning_state: dict[str, Any] | None) -> str:
    ls = learning_state if isinstance(learning_state, dict) else {}
    cap = ls.get("caption_style") or {}
    if not cap:
        return "2-4 kısa cümle; bazen tek satırlık net çıkarım + açılış."
    try:
        best = max(cap, key=lambda k: float(cap.get(k) or 0.0))
    except Exception:
        best = "medium"
    if best == "short":
        return "Öncelik: ÇOK KISA — 1-2 sıkı cümle veya 2-3 kısa satır; gereksiz dolgu yok."
    if best == "long":
        return "Öncelik: biraz daha uzun — kanca + 3-5 kısa satır veya 2 kısa paragraf; yine de Instagram'a uygun ritim."
    return "Orta uzunluk — 3-5 kısa cümle; satır aralarında nefes."


def format_engagement_pack_for_caption(pack: dict[str, Any] | None, *, length_hint: str) -> str:
    if not pack:
        return ""
    avoid = pack.get("avoid_tr") or []
    avoid_s = ", ".join(str(x) for x in avoid[:6]) if avoid else ""
    return (
        "\n\n--- ETKİLEŞİM / ARAŞTIRMA NOTLARI (BUNLARI YAZIYA YANSIT) ---\n"
        f"Hedef uzunluk tercihi (veriye dayalı): {length_hint}\n"
        f"Özet / merak düzlemi: {pack.get('research_summary_tr', '')}\n"
        f"Güçlü açılış fikri (ilk cümleye yansıt): {pack.get('scroll_hook_tr', '')}\n"
        f"Gövde odağı: {pack.get('body_angle_tr', '')}\n"
        f"Yumuşak CTA (metnin uygun yerine, sona zorlamadan): {pack.get('soft_cta_tr', '')}\n"
        + (f"Kaçınılacaklar: {avoid_s}\n" if avoid_s else "")
        + "---\n"
    )


def format_engagement_pack_for_image(pack: dict[str, Any] | None) -> str:
    if not pack:
        return ""
    v = (pack.get("visual_direction_en") or "").strip()
    if not v:
        return ""
    return (
        "\n\nEngagement / clarity boost (must follow): "
        + v
        + "\nKeep center calmer for text overlay; no readable text in image."
    )


def prepare_engagement_for_topic(topic: str, content_type: str) -> tuple[str | None, str | None, str | None]:
    """
    Manuel üretim endpoint'leri için: (caption_addon, visual_en, hashtag_focus).
    Kapalıysa veya hata varsa (None, None, None).
    """
    if not is_engagement_boost_enabled():
        return None, None, None
    try:
        ls = load_learning_state()
        pack = build_engagement_pack(topic, content_type, ls)
        if not pack:
            return None, None, None
        addon = format_engagement_pack_for_caption(
            pack,
            length_hint=caption_length_hint_from_learning(ls),
        )
        vis = (pack.get("visual_direction_en") or "").strip() or None
        hf = (pack.get("hashtag_focus_tr") or "").strip() or None
        return addon, vis, hf
    except Exception:
        return None, None, None
