"""
Önceki üretilmiş caption metinleriyle çakışmayı azaltmak için yardımcılar.

Kaynaklar:
- posts.caption: taslak / yayın kayıtları
- caption_history: Post oluşturmayan önizleme veya harici üretimler
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import CaptionHistory, Post
from app.services.content_ai import generate_caption
from app.services.instagram_content_generator import generate_instagram_content


_CAPTION_FETCH_LIMIT = 140
_PROMPT_AVOID_CAP = 12
_MAX_SNIPPET_CHARS = 168
_DEFAULT_SIMILARITY = 0.83
_MAX_DEDUP_ATTEMPTS = 6


def _normalize_for_compare(text: str) -> str:
    s = (text or "").strip().casefold()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"#\w+", "", s)
    return s.strip()


def _word_jaccard(a_norm: str, b_norm: str) -> float:
    wa = set(re.findall(r"[\wöçşığüÖÇŞİĞÜ]+", a_norm, flags=re.UNICODE))
    wb = set(re.findall(r"[\wöçşığüÖÇŞİĞÜ]+", b_norm, flags=re.UNICODE))
    if not wa or not wb:
        return 0.0
    inter = wa & wb
    union = wa | wb
    return len(inter) / len(union)


def caption_similarity(a: str, b: str) -> float:
    na = _normalize_for_compare(a)
    nb = _normalize_for_compare(b)
    if not na or not nb:
        return 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    jac = _word_jaccard(na, nb)
    return max(seq, jac)


def is_too_similar(new: str, corpus: list[str], *, threshold: float = _DEFAULT_SIMILARITY) -> bool:
    for old in corpus:
        if caption_similarity(new, old) >= threshold:
            return True
    return False


def get_prior_captions(
    db: Session,
    *,
    account_id: int | None = None,
    limit: int = _CAPTION_FETCH_LIMIT,
) -> list[str]:
    lim = max(1, min(int(limit), 300))
    q_post = db.query(Post.caption, Post.created_at).filter(
        Post.caption.isnot(None),
        Post.caption != "",
    )
    if account_id is not None:
        q_post = q_post.filter(Post.account_id == account_id)
    rows_p = q_post.order_by(Post.created_at.desc()).limit(lim).all()

    q_hist = db.query(CaptionHistory.caption, CaptionHistory.created_at).filter(
        CaptionHistory.caption.isnot(None),
        CaptionHistory.caption != "",
    )
    if account_id is not None:
        q_hist = q_hist.filter(
            or_(CaptionHistory.account_id == account_id, CaptionHistory.account_id.is_(None))
        )
    rows_h = q_hist.order_by(CaptionHistory.created_at.desc()).limit(lim).all()

    merged: list[tuple[str, object]] = [(str(c), t) for c, t in rows_p if c] + [
        (str(c), t) for c, t in rows_h if c
    ]
    merged.sort(key=lambda x: x[1], reverse=True)  # type: ignore[arg-type, return-value]

    seen_keys: set[str] = set()
    out: list[str] = []
    for cap, _dt in merged:
        key = _normalize_for_compare(cap)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(cap.strip())
        if len(out) >= lim:
            break
    return out


def record_caption_history(
    db: Session,
    caption: str,
    *,
    topic: str | None = None,
    account_id: int | None = None,
    source: str | None = None,
) -> None:
    text = (caption or "").strip()
    if not text:
        return
    src = (source or "").strip()
    row = CaptionHistory(
        caption=text,
        topic=(topic or None),
        account_id=account_id,
        source=src[:64] if src else None,
    )
    db.add(row)
    db.commit()


def _build_avoid_list(prior: list[str], rejected: list[str]) -> list[str]:
    combined = list(prior) + list(rejected)
    return combined[-_PROMPT_AVOID_CAP:] if combined else []


def generate_caption_deduped(
    topic,
    content_type: str = "ilginç_bilgi",
    engagement_addon: str | None = None,
    *,
    db: Session,
    account_id: int | None = None,
    max_attempts: int = _MAX_DEDUP_ATTEMPTS,
    similarity_threshold: float = _DEFAULT_SIMILARITY,
) -> str:
    prior = get_prior_captions(db, account_id=account_id)
    rejected: list[str] = []
    attempts = max(1, min(int(max_attempts), 10))
    last: str = ""
    for _ in range(attempts):
        avoid = _build_avoid_list(prior, rejected)
        last = generate_caption(
            topic,
            content_type=content_type,
            engagement_addon=engagement_addon,
            avoid_similar_to=avoid if avoid else None,
        )
        if not is_too_similar(last, prior + rejected, threshold=similarity_threshold):
            return last
        rejected.append(last)
    return last


def generate_instagram_content_deduped(
    *,
    db: Session,
    account_id: int | None = None,
    topic: str,
    content_type: str,
    prefer_short: bool | None = None,
    hashtag_count: int = 10,
    engagement_pack: dict | None = None,
    max_attempts: int = _MAX_DEDUP_ATTEMPTS,
    similarity_threshold: float = _DEFAULT_SIMILARITY,
) -> dict:
    prior = get_prior_captions(db, account_id=account_id)
    rejected: list[str] = []
    attempts = max(1, min(int(max_attempts), 10))
    last: dict = {}
    for _ in range(attempts):
        avoid = _build_avoid_list(prior, rejected)
        last = generate_instagram_content(
            topic=topic,
            content_type=content_type,
            prefer_short=prefer_short,
            hashtag_count=hashtag_count,
            engagement_pack=engagement_pack,
            avoid_similar_to=avoid if avoid else None,
        )
        cap = (last.get("caption") or "").strip()
        if cap and not is_too_similar(cap, prior + rejected, threshold=similarity_threshold):
            return last
        if cap:
            rejected.append(cap)
    return last
