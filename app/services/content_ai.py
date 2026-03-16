import random
from openai import OpenAI
from app.config import OPENAI_API_KEY

_client = None

# Tüm içeriklerde kullanılacak ortak komik üslup
KOMIK_USLUP = (
    "\n\nÜSLUP: Metni hafif komik, esprili ve eğlenceli bir dille yaz. "
    "Samimi, gülümseten bir ton kullan; okuyan gülsün ama mesaj da kalsın. "
    "Küfür veya aşağılayıcı ifade kullanma."
)

# Her üretimde farklı açı kullanarak tekrarları azalt
CAPTION_ANGLES = [
    "Pratik, günlük hayatta hemen uygulanabilir bir tüyo ver.",
    "Beklenmedik veya az bilinen bir psikoloji/ilişki bilgisiyle destekle.",
    "Astroloji veya burçlarla bağ kur (uygunsa).",
    "Kısa, cesur ve net bir öneri olarak yaz.",
    "Yumuşak, motive edici ve sıcak bir ton kullan.",
    "İlişki koçu / uzman tarzında profesyonel ama samimi bir tüyo ver.",
    "Modern, güncel bir ifade ve örnekler kullan.",
    "Duygusal zeka veya öz farkındalık açısından yaklaş.",
    "Sadece 1 cümlelik çarpıcı bir tüyo yaz.",
    "Dinamik ve enerjik bir üslupla yaz.",
]


def get_client():
    global _client
    if _client is None:
        if OPENAI_API_KEY:
            _client = OpenAI(api_key=OPENAI_API_KEY)
        else:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
    return _client


def generate_caption(topic, content_type: str = "ilginç_bilgi"):
    """
    content_type: ilginç_bilgi | bilim | teknoloji | yapay_zeka | tasarim | uzay
    Türüne göre farklı format ve üslupta kısa, komik ve öğretici metin üretir.
    """
    topic_choice = (topic or "").strip() or "bilim ve teknoloji"
    client = get_client()

    if content_type == "ilginç_bilgi":
        prompt = (
            "Türkçe olarak, okuyanın 'vay be, bunu bilmiyordum' diyeceği KISA bir ilginç bilgi yaz.\n\n"
            f"Konu: {topic_choice}\n\n"
            "- Günlük hayatta işe yarayabilecek veya zihni açacak bir gerçek olsun.\n"
            "- 1-3 cümle, sade ve anlaşılır.\n"
            "- Bilimsel olarak makul olsun; uydurma şehir efsanelerinden kaçın.\n"
            "- Sonunda hashtag veya uzun açıklama ekleme."
            + KOMIK_USLUP
            + "\n"
        )
    elif content_type == "bilim":
        prompt = (
            "Türkçe olarak, BİLİM temalı kısa bir bilgi veya gözlem yaz.\n\n"
            f"Alan/Konu: {topic_choice}\n\n"
            "- Fizik, biyoloji, psikoloji, nörobilim veya benzeri bir bilim dalından gerçek bir kavram seç.\n"
            "- 1-3 cümlede, karmaşık bir şeyi sade ve eğlenceli bir dille açıkla.\n"
            "- Bilimsel kavramı günlük hayattan örnekle bağla.\n"
            "- Sonunda hashtag ekleme."
            + KOMIK_USLUP
            + "\n"
        )
    elif content_type == "teknoloji":
        prompt = (
            "Türkçe olarak, TEKNOLOJİ dünyasından kısa bir içgörü veya mini ipucu yaz.\n\n"
            f"Alan: {topic_choice}\n\n"
            "- Telefon, bilgisayar, internet, oyun, donanım veya yazılım dünyasından bir örnek kullan.\n"
            "- 1-3 cümle, pratik ve anlaşılır olsun.\n"
            "- Okuyan, günlük hayatında uygulayabileceği küçük bir ipucu alabilsin.\n"
            "- Sonunda hashtag ekleme."
            + KOMIK_USLUP
            + "\n"
        )
    elif content_type == "yapay_zeka":
        prompt = (
            "Türkçe olarak, YAPAY ZEKA hakkında kısa ve anlaşılır bir açıklama veya ipucu yaz.\n\n"
            f"Konu: {topic_choice}\n\n"
            "- Yapay zekayı korkutucu değil, anlaşılır ve gündelik bir şey gibi anlat.\n"
            "- 1-3 cümlede kavramı özetle; teknik terimleri sadeleştir.\n"
            "- Okuyan, yapay zeka ile ne yapabileceğini hayal etsin.\n"
            "- Sonunda hashtag ekleme."
            + KOMIK_USLUP
            + "\n"
        )
    elif content_type == "tasarim":
        prompt = (
            "Türkçe olarak, TASARIM odaklı kısa bir ipucu veya gözlem yaz.\n\n"
            f"Konu: {topic_choice}\n\n"
            "- Grafik, UI/UX, tipografi veya renk kullanımıyla ilgili bir içgörü paylaş.\n"
            "- 1-3 cümle, uygulamaya dönük ve esprili bir dille olsun.\n"
            "- Çok teknik detaylara girmeden, herkesin anlayacağı şekilde yaz.\n"
            "- Sonunda hashtag ekleme."
            + KOMIK_USLUP
            + "\n"
        )
    elif content_type == "uzay":
        prompt = (
            "Türkçe olarak, UZAY ve EVREN hakkında kısa, merak uyandıran bir bilgi yaz.\n\n"
            f"Konu: {topic_choice}\n\n"
            "- Gezegenler, yıldızlar, kara delikler veya uzay yolculuğu gibi başlıklardan birini seç.\n"
            "- 1-3 cümlede, bilimsel bir gerçeği sade ve eğlenceli şekilde anlat.\n"
            "- Okuyan 'uzaya bilet alalım mı?' hissine kapılsın.\n"
            "- Sonunda hashtag ekleme."
            + KOMIK_USLUP
            + "\n"
        )
    else:
        # varsayılan: konuya göre ilginç ve öğretici bir bilgi/tüyo
        angle = random.choice(CAPTION_ANGLES)
        prompt = (
            "Türkçe olarak, Instagram için KISA (1-3 cümle) bir BİLGİ veya TÜYO yaz. Eyleme dönüştürülebilir, uygulanabilir bir öneri olmalı.\n\n"
            f"Konu: {topic_choice}\n\n"
            "ÇEŞİTLİLİK: Her seferinde FARKLI ifadeler kullan; klişe sözleri tekrarlama. Bu sefer: " + angle + "\n\n"
            "KURALLAR: Sadece bilgi/tüyo yaz; şiirsel veya felsefi genel cümle yazma. Samimi, motive edici ton. 1-2 emoji. Hashtag ekleme."
            + KOMIK_USLUP
            + "\n"
        )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.95,
        frequency_penalty=0.7,
        presence_penalty=0.5,
    )
    content = resp.choices[0].message.content
    return (content or "").strip()


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
            "bilim",
            "teknoloji",
            "yapay zeka",
            "tasarım",
            "uzay",
            "ilginç bilgiler",
        ]

        def _choose_topic(t):
            if not t:
                return "bilim"
            tl = t.lower()
            for a in ALLOWED_TOPICS:
                if a in tl or tl in a:
                    return a
            return "bilim"

        client = get_client()
        topic_choice = _choose_topic(topic)
        context = f"Konuyu Türkçe olarak ele al. Topic: {topic_choice}"
        if caption:
            context += f"\nCaption: {caption[:200]}"  # İlk 200 karakter
        prompt = f"""Türkçe bağlamda, bu içerik için {count} adet Instagram hashtag'i üret.
{context}

- Caption ve konuyla tam uyumlu, güncel ve ilgi çekici hashtag'ler seç. Türkçe ve evrensel karışımında olsun.
- Bilim, teknoloji, yapay zeka, tasarım, uzay ve ilginç bilgiler nişine uygun; paylaşılabilir ve keşfedilebilir etiketler kullan.
Sadece hashtag'leri döndürün, her satırda bir tane, '#' ile başlayacak şekilde. Açıklama yazmayın."""

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
        )

        raw = resp.choices[0].message.content
        hashtags_text = (raw or "").strip()
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
        # Fallback: Nişe uygun (bilim/teknoloji/AI) hashtag'ler
        print(f"Warning: Hashtag generation failed: {e}")
        fallback = [
            "#bilim",
            "#teknoloji",
            "#yapayzeka",
            "#tasarım",
            "#uzay",
            "#science",
            "#technology",
            "#ai",
            "#design",
            "#space",
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


def shorten_caption_for_image(text: str, max_chars: int = 220) -> str:
    """
    Görsele basılacak metni kısaltır; uzun caption'ların çok küçülmesini engeller.
    - max_chars sınırını aşarsa, uygun bir cümle sonuna kadar kısaltır, gerekirse '...' ekler.
    - Caption'ın tamamı DB'de ve Instagram'da kullanılmaya devam eder; bu sadece görsel üzerindeki kopya içindir.
    """
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t

    # Önce nokta, ünlem, soru işareti gibi cümle sonlarını arayıp, sınırın biraz altına denk geleni bul.
    cutoff = -1
    for ch in [".", "!", "?"]:
        idx = t.rfind(ch, 0, max_chars)
        if idx > cutoff:
            cutoff = idx
    if cutoff != -1 and cutoff >= int(max_chars * 0.5):
        return t[: cutoff + 1].strip()

    # Uygun cümle sonu yoksa, kelime ortasında kesmemek için son boşluğa kadar kısalt.
    last_space = t.rfind(" ", 0, max_chars)
    if last_space != -1 and last_space >= int(max_chars * 0.5):
        return (t[:last_space].rstrip() + "…").strip()

    # En kötü senaryoda direkt kes.
    return (t[:max_chars].rstrip() + "…").strip()


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

    # Her seferinde farklı görsel tarz öner
    style_hints = [
        "Use a warm, golden-hour palette with soft bokeh.",
        "Use cool blues and soft purples with minimal geometry.",
        "Use muted earth tones and organic, flowing shapes.",
        "Use soft pastels (pink, mint, lavender) and gentle gradients.",
        "Use deep, moody tones with a single accent color.",
        "Use airy, light tones with subtle floral or nature texture.",
        "Use abstract, dreamy gradients without recognisable objects.",
        "Use a cinematic, film-like colour grading.",
    ]
    style_hint = random.choice(style_hints)
    try:
        client = get_client()
        topic_choice = _choose_topic(topic)
        prompt = (
            f"Create a concise image generation prompt for a square Instagram background about: {topic_choice}\n\n"
            "- No readable text in the image (we'll overlay text later).\n"
            "- Leave a clear centered negative space for a white or light-colored quote overlay.\n"
            f"- This time: {style_hint}\n"
            "- Each image must feel UNIQUE; avoid the same composition or palette as typical quote backgrounds.\n"
            "- Match the mood to the topic: romantic, melancholic, joyful, calm, hopeful, dramatic, etc.\n"
            "- Style: soft, emotive, high-quality. Minimal distractions in center.\n"
            "Return ONLY the image prompt as a single paragraph, in English."
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            frequency_penalty=0.4,
        )
        content = resp.choices[0].message.content
        return (content or "").strip()
    except Exception as e:
        print(f"Warning: Image prompt generation failed: {e}")
        return f"Square 1:1 soft background with centered negative space for text, varied palette and mood, high quality, {topic}"


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
