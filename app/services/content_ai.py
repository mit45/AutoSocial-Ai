from openai import OpenAI
from app.config import OPENAI_API_KEY

_client = None


def get_client():
    global _client
    if _client is None:
        if OPENAI_API_KEY:
            _client = OpenAI(api_key=OPENAI_API_KEY)
        else:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
    return _client


def generate_caption(topic):
    # Enforce allowed topics only
    ALLOWED_TOPICS = [
        "duygusal",
        "ikili ilişkiler",
        "aşk",
        "arkadaşlık",
        "platonik aşk",
        "komedi",
        "dram",
    ]

    def _choose_topic(t):
        if not t:
            return "duygusal"
        tl = t.lower()
        for a in ALLOWED_TOPICS:
            if a in tl or tl in a:
                return a
        # fallback
        return "duygusal"

    topic_choice = _choose_topic(topic)

    # Generate short, Instagram-appropriate caption constrained to allowed themes.
    prompt = (
        f"Türkçe olarak, Instagram için KISA, mobilde okunaklı ve paylaşılabilir bir içerik (1-3 kısa cümle) yaz.\n"
        f"Konu: {topic_choice}\n"
        f"- Bu içerik yalnızca şu temalardan biri üzerine olsun: {', '.join(ALLOWED_TOPICS)}.\n"
        f"- Duygusal, samimi ve hafif dramatik ama umutlu bir ton kullanın.\n"
        f"- Emoji kullanmak isterseniz 1-2 ile sınırlayın. CTA ya da 'yorumlarda paylaşın' gibi yönlendirmeler eklemeyin.\n"
        f"- Sonunda hashtag eklemeyin (hashtag ayrı fonksiyonda üretilir).\n"
    )
    client = get_client()
    resp = client.chat.completions.create(
        # gpt-4 yerine daha yaygın erişilebilen bir model kullan
        # Hesabında açık olan modele göre burayı değiştirebilirsin.
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


def generate_hashtags(topic, caption=None, count=10):
    """
    Verilen konu ve caption'a göre Instagram hashtag'leri üretir.

    Args:
        topic: Post konusu
        caption: Post caption'ı (opsiyonel, daha iyi hashtag için)
        count: Kaç hashtag üretilecek (default: 10)

    Returns:
        List[str]: Hashtag listesi (örn: ["#AI", "#Technology", ...])
    """
    try:
        ALLOWED_TOPICS = [
            "duygusal",
            "ikili ilişkiler",
            "aşk",
            "arkadaşlık",
            "platonik aşk",
            "komedi",
            "dram",
        ]

        def _choose_topic(t):
            if not t:
                return "duygusal"
            tl = t.lower()
            for a in ALLOWED_TOPICS:
                if a in tl or tl in a:
                    return a
            return "duygusal"

        client = get_client()
        topic_choice = _choose_topic(topic)
        context = f"Konuyu Türkçe olarak ele al. Topic: {topic_choice}"
        if caption:
            context += f"\nCaption: {caption[:200]}"  # İlk 200 karakter
        prompt = f"""Türkçe bağlamda, bu içerik için {count} adet uygun Instagram hashtag'i üret.
{context}

Sadece hashtag'leri döndürün, her satırda bir tane, '#' ile başlayacak şekilde. Açıklama yazmayın."""

        resp = client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
        )

        hashtags_text = resp.choices[0].message.content.strip()
        # Satırlara böl ve # ile başlamayanları filtrele
        hashtags = [
            line.strip()
            for line in hashtags_text.split("\n")
            if line.strip().startswith("#")
        ]

        # Eğer yeterli hashtag yoksa, topic'ten bazı genel ekle
        if len(hashtags) < count:
            topic_words = topic.lower().split()
            for word in topic_words[: count - len(hashtags)]:
                if len(word) > 3:  # Çok kısa kelimeleri atla
                    hashtags.append(f"#{word.capitalize()}")

        return hashtags[:count]  # İstenen sayıya kadar sınırla

    except Exception as e:
        # Fallback: Basit hashtag'ler
        print(f"Warning: Hashtag generation failed: {e}")
        fallback = [
            "#AI",
            "#Technology",
            "#Innovation",
            "#Motivation",
            "#Inspiration",
            "#Success",
            "#Growth",
            "#Tips",
            "#Life",
            "#Daily",
        ]
        return fallback[:count]


def format_post_text(caption, hashtags):
    """
    Caption ve hashtag'leri Instagram formatına göre birleştirir.

    Format:
    - Caption (emoji'lerle)
    - Boş satır
    - Hashtag'ler (satır başına 3-4 tane)

    Args:
        caption: Ana caption metni
        hashtags: Hashtag listesi

    Returns:
        str: Formatlanmış post metni
    """
    # Caption'ı temizle
    formatted_caption = caption.strip()

    # Hashtag'leri grupla (satır başına 3-4 tane)
    hashtag_lines = []
    for i in range(0, len(hashtags), 4):
        line = " ".join(hashtags[i : i + 4])
        hashtag_lines.append(line)

    # Birleştir
    hashtag_section = "\n".join(hashtag_lines)

    # Final format
    formatted_post = f"{formatted_caption}\n\n{hashtag_section}"

    return formatted_post


def generate_image_prompt(topic: str) -> str:
    """
    Create a compact image generation prompt optimized for quote overlay on Instagram.
    The returned prompt should describe a square (1:1) background with negative space/area
    for readable text, a clear mood/style and color palette. Do NOT include any readable text
    in the image itself.
    """
    ALLOWED_TOPICS = [
        "duygusal",
        "ikili ilişkiler",
        "aşk",
        "arkadaşlık",
        "platonik aşk",
        "komedi",
        "dram",
    ]

    def _choose_topic(t):
        if not t:
            return "duygusal"
        tl = t.lower()
        for a in ALLOWED_TOPICS:
            if a in tl or tl in a:
                return a
        return "duygusal"

    try:
        client = get_client()
        topic_choice = _choose_topic(topic)
        prompt = (
            f"Create a concise image generation prompt for a square Instagram background about: {topic_choice}\n\n"
            "- No readable text in the image (we'll overlay text later).\n"
            "- Leave a clear centered negative space for a white or light-colored quote overlay.\n"
            "- Style: soft, emotive, high-quality. Suggest palette (e.g., warm pastels or cool blues) and mood.\n"
            "- Composition: minimal distractions in center, subtle texture, natural lighting or soft vignette.\n"
            "Return ONLY the image prompt as a single paragraph."
        )
        resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Warning: Image prompt generation failed: {e}")
        return f"Square 1:1 soft background with centered negative space for text, warm pastel palette, high quality, {topic}"


def generate_image_png_bytes(image_prompt: str) -> bytes:
    """
    OpenAI gpt-image-1 modeli ile görsel üretir ve PNG bytes döndürür.

    Args:
        image_prompt: Görsel üretimi için prompt

    Returns:
        bytes: PNG formatında görsel bytes'ı

    Raises:
        Exception: OpenAI API hatası veya görsel üretilemezse
    """
    client = get_client()

    try:
        # DALL-E 3 sadece URL formatını destekler, b64_json desteklemez
        # URL'den görseli indirip bytes'a çeviriyoruz
        resp = client.images.generate(
            model="dall-e-3",
            prompt=image_prompt,
            size="1024x1024",
            n=1,
            response_format="url",  # DALL-E 3 için tek desteklenen format
        )

        url = resp.data[0].url  # type: ignore[attr-defined]
        if not url:
            raise ValueError("Empty image URL from OpenAI")

        # URL'den görseli indir
        import requests

        img_resp = requests.get(url, timeout=30)
        img_resp.raise_for_status()
        return img_resp.content

    except Exception as e:
        # Hata durumunda detaylı log
        import traceback

        print(f"[ERROR] OpenAI image generation failed: {e}")
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        raise Exception(f"Failed to generate image: {e}") from e
