import random
from openai import OpenAI
from app.config import OPENAI_API_KEY

_client = None

# ——— Caption: ton çeşitliliği (tek tip "komik / alaycı" kilitlenmesin) ———
VOICE_PRESETS = [
    "SES: Net popüler-bilim anlatıcısı. Sıcak ama ciddi; alaycı veya havalı değil. Cümleler öz.",
    "SES: Meraklı gözlemci. Yeni not almış gibi düzenli paylaşım; abartı ve şakaya kaçma.",
    "SES: Sakin uzman. Güven veren, yargılamayan; gereksiz espri yok.",
    "SES: Kısa hikâye açılışı. 1 küçük somut sahne → sonra bilgiyi bağla; dramatize etme.",
    "SES: Pratik rehber. Okuyanın 'bunu not edeyim' diyeceği net bilgi; boş motivasyon cümlesi yok.",
    "SES: Minimal ve özgün. Süslü söz, klişe giriş, metafor şovu yok; doğrudan anlat.",
    "SES: Karşılaştırmalı düşünür. İki fikri yan yana koyarak açıkla (tek taraf alay etmeden).",
]

OPENING_STRATEGIES = [
    "Giriş: Tek somut gözlem veya örnek (bir satır), ardından açıklama.",
    "Giriş: Kısa tanım veya ölçek; hemen ardından günlük hayattaki karşılığı.",
    "Giriş: Tek 'neden' sorusu; cevap 2-3 cümlede, net.",
    "Giriş: Sayı, süre veya ölçek ver (abartısız); sonra anlamını bağla.",
    "Giriş: Yanlış anlaşılan noktayı düzelt — saygılı, öğretici üslupla (alay etmeden).",
    "Giriş: Doğrudan ana cümleyle başla; ikinci cümle detay veya örneği taşısın.",
    "Giriş: 'Şunu fark ettin mi?' tarzı yumuşak merak (üst perdeden değil).",
]

ANTI_REPETITION_AND_TONE = (
    "\n\nTON VE TEKRAR (ZORUNLU):\n"
    "- Alaycı ironi, küçümseyen ton, 'herkesten akıllıyım' hissi YASAK.\n"
    "- Aşağıdaki KALIPları ve yakın varyantlarını bu metinde KULLANMA: "
    "'asıl mesele', 'kimse söylemiyor', 'şok', 'dur bi dakika', 'yanlış biliyorsun', "
    "'evdeki akıllı dost', 'teknolojik arkadaş', 'teknolojik arkadaşlarımız', 'Sana biraz … lazım' şakalaşma kalıbı.\n"
    "- Bulut bilişim / veri merkezi konusunda 'gökyüzüne yükle', 'bulut = gökyüzü' gibi çocuksu benzetme veya sığ şaka YASAK.\n"
    "- Fazla ünlem, soru yağmuru, üç nokta ile dramatikleştirme YASAK.\n"
    "- Üslubu seçilen SES ile tutarlı tut; önceki üretimlerde kullandığın girişi TAHMİN ETME — her seferinde farklı bir giriş stratejisi izle.\n"
    "- Bilgi doğru ve makul olsun; uydurma iddia ve tık tuzağı yok. Küfür yok.\n"
    "- Kuru akademik özet, madde madde liste, sözlük tanımı gibi yazma; yine de ciddiyet korunabilir.\n"
)

NICHE_CONTENT_ANGLES = [
    "Mekanizmayı kısaca anlat: 'neyin üst üste bindiği' veya 'nasıl işliyor'.",
    "İki kavramı yan yana koy; farkı tek paragrafta netleştir.",
    "Günlük hayatta görünür bir örnek seç; bilgiyi ona bağla.",
    "Kısa 'neden önemli?' cümlesiyle bağlam ver; abartma.",
    "Tek sayı veya ölçü ile düşündür; kaynak uydurma.",
    "Okuyana küçük bir kontrol ve mini pratik öneri (etik ve güvenli).",
]


def _caption_variety_addon() -> str:
    return (
        ANTI_REPETITION_AND_TONE
        + random.choice(VOICE_PRESETS)
        + "\n"
        + random.choice(OPENING_STRATEGIES)
        + "\n"
    )


def extra_viral_caption_instructions() -> str:
    """Instagram / strateji caption üretiminde çeşitlilik ve ton kısıtları (eski ad, uyumluluk)."""
    return _caption_variety_addon()


def get_client():
    global _client
    if _client is None:
        if OPENAI_API_KEY:
            _client = OpenAI(api_key=OPENAI_API_KEY)
        else:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
    return _client


def _format_avoid_similar_block(avoid_similar_to: list[str]) -> str:
    lines: list[str] = []
    for i, t in enumerate(avoid_similar_to[-12:], 1):
        snippet = (t or "").strip().replace("\n", " ")
        if len(snippet) > 168:
            snippet = snippet[:165] + "..."
        lines.append(f"{i}. {snippet}")
    return (
        "\n\nÖNCEKİ İÇERİKLERDEN AYRIL (ZORUNLU):\n"
        "Aşağıdakiler bu kanal için daha önce üretilmiş metinlerdir (veya az önce reddedilen çok yakın taslaklar). "
        "Yeni metin bunların aynısı, çevirisi veya neredeyse aynı cümle yapısı olmasın; "
        "farklı örnek, farklı giriş ve farklı sözcük seç.\n"
        + "\n".join(lines)
    )


def generate_caption(
    topic,
    content_type: str = "ilginç_bilgi",
    engagement_addon: str | None = None,
    avoid_similar_to: list[str] | None = None,
):
    """
    content_type: ilginç_bilgi | bilim | teknoloji | yapay_zeka | tasarim | uzay
    Türüne göre farklı format ve üslupta kısa, çeşitli tonlarda öğretici metin üretir.
    engagement_addon: content_engagement_boost çıktısı (strateji notları) — varsa modele eklenir.
    """
    topic_choice = (topic or "").strip() or "bilim ve teknoloji"
    client = get_client()

    if content_type == "ilginç_bilgi":
        prompt = (
            "Türkçe olarak, zihni açan KISA bir ilginç bilgi yaz.\n\n"
            f"Konu: {topic_choice}\n\n"
            "- Günlük hayatta işe yarayabilecek veya bakış açısı kazandıracak gerçek bir nokta seç.\n"
            "- 2-4 kısa cümle; monoton tanım veya ansiklopedi dili kullanma.\n"
            "- Bilimsel olarak makul olsun.\n"
            "- Emoji en fazla 1; hashtag yazma."
            + _caption_variety_addon()
            + "\n"
        )
    elif content_type == "bilim":
        prompt = (
            "Türkçe olarak, BİLİM temalı kısa bir bilgi veya gözlem yaz.\n\n"
            f"Alan/Konu: {topic_choice}\n\n"
            "- Gerçek bir kavram seç; 2-4 kısa cümlede sade anlat.\n"
            "- Günlük hayattan örnekle bağ kur.\n"
            "- Hashtag yok; emoji en fazla 1."
            + _caption_variety_addon()
            + "\n"
        )
    elif content_type == "teknoloji":
        prompt = (
            "Türkçe olarak, TEKNOLOJİ konusunda KISA bir metin yaz.\n\n"
            f"Konu (buna sıkı bağlı kal): {topic_choice}\n\n"
            "ÖNCELİK: Çoğu kişinin bilmediği veya az bildiği, DOĞRULANABİLİR bir teknik/operasyonel gerçek aktar "
            "(mimari, güvenlik, performans, ölçek, protokol, donanım-yazılım sınırı, maliyet/verim mantığı vb.).\n"
            "- En az bir somut detay ver (ölçü, süre, katman, örnek senaryo); uydurma istatistik yazma.\n"
            "- Sığ şaka, alay, 'komik' hashtag ima eden dil kullanma; gökyüzü/bulut kelime oyunu yapma.\n"
            "- 2-4 kısa cümle; konu başlığıyla doğrudan ilgili olsun.\n"
            "- Hashtag yok; emoji en fazla 1."
            + _caption_variety_addon()
            + "\n"
        )
    elif content_type == "yapay_zeka":
        prompt = (
            "Türkçe olarak, YAPAY ZEKA hakkında kısa ve anlaşılır bir metin yaz.\n\n"
            f"Konu: {topic_choice}\n\n"
            "- Mümkünse çoğu okuyucunun az bildiği somut bir gerçek veya mekanizma vurgusu ver (eğitim, veri, güvenlik, sınırlar).\n"
            "- Korkutmadan, abartmadan anlat; teknik terimleri sadeleştir.\n"
            "- 2-4 kısa cümle; 'akıllı asistan arkadaş' gibi süslü metaforlara sığınma.\n"
            "- Hashtag yok; emoji en fazla 1."
            + _caption_variety_addon()
            + "\n"
        )
    elif content_type == "tasarim":
        prompt = (
            "Türkçe olarak, TASARIM odaklı kısa bir ipucu veya gözlem yaz.\n\n"
            f"Konu: {topic_choice}\n\n"
            "- Grafik, UI/UX, tipografi veya renk ile ilgili somut bir içgörü.\n"
            "- 2-4 kısa cümle; herkesin anlayacağı dil.\n"
            "- Hashtag yok; emoji en fazla 1."
            + _caption_variety_addon()
            + "\n"
        )
    elif content_type == "uzay":
        prompt = (
            "Türkçe olarak, UZAY ve EVREN hakkında kısa bir bilgi yaz.\n\n"
            f"Konu: {topic_choice}\n\n"
            "- Somut bir açı seç (ölçek, süreç, gözlem mantığı).\n"
            "- 2-4 kısa cümle; abartılı bilim-kurgu dili kullanma.\n"
            "- Hashtag yok; emoji en fazla 1."
            + _caption_variety_addon()
            + "\n"
        )
    else:
        angle = random.choice(NICHE_CONTENT_ANGLES)
        prompt = (
            "Türkçe olarak, Instagram için kısa (2-4 cümle) bilgi veya tüyo yaz.\n\n"
            f"Konu: {topic_choice}\n\n"
            "Bu üretimde şu açıyı izle: " + angle + "\n\n"
            "Boş felsefi cümle yok. Hashtag yok; emoji en fazla 1."
            + _caption_variety_addon()
            + "\n"
        )

    if engagement_addon:
        prompt = prompt + "\n" + engagement_addon.strip() + "\n"

    if avoid_similar_to:
        cleaned = [x for x in avoid_similar_to if (x or "").strip()]
        if cleaned:
            prompt = prompt + _format_avoid_similar_block(cleaned)

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.88,
        frequency_penalty=0.85,
        presence_penalty=0.55,
    )
    content = resp.choices[0].message.content
    return (content or "").strip()


def generate_hashtags(topic, caption=None, count=10, engagement_focus: str | None = None):
    """
    Verilen konu ve caption'a göre Instagram hashtag'leri üretir.

    Args:
        topic: Post konusu
        caption: Post caption'ı (opsiyonel, daha iyi hashtag için)
        count: Kaç hashtag üretilecek (default: 10)
        engagement_focus: strateji katmanından ek niş kelimeler (opsiyonel)

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
        if engagement_focus and engagement_focus.strip():
            context += f"\nStrateji / niş odağı: {engagement_focus.strip()[:400]}"
        prompt = f"""Türkçe bağlamda, bu içerik için {count} adet Instagram hashtag'i üret.
{context}

- Caption ve konuyla tam uyumlu etiketler; abartılı viral hashtagle doldurma.
- Sadece genel (#bilim) ile yetinme; içeriğe özgü en az 4 etiket olsun.
- Bilim, teknoloji, yapay zeka, tasarım, uzay ve ilginç bilgiler nişine uygun; paylaşılabilir ve keşfedilebilir etiketler kullan.
- Komik, şaka veya alay ima eden etiket kullanma (ör. #BulutKomik, #TeknoŞaka yok).
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

        _ban_sub = ("komik", "şak", "saka", "lol", "funny", "ironik", "alay")
        hashtags = [h for h in hashtags if not any(b in h.lower() for b in _ban_sub)]

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


def _image_topic_family(topic: str) -> str:
    """Konu metninden görsel aile seç — varsayılan 'duygusal duvar kağıdı' olmasın."""
    t = (topic or "").lower()
    if any(
        k in t
        for k in [
            "yapay",
            "zeka",
            "gpt",
            "chatgpt",
            "makine öğren",
            "üretken",
            "neural",
            "llm",
            "derin öğren",
            "metin üretim",
            "dil model",
        ]
    ):
        return "ai_tech"
    if any(k in t for k in ["uzay", "mars", "evren", "gezegen", "yıldız", "kara delik", "astronot", "galaksi", "roket"]):
        return "space"
    if any(k in t for k in ["tasarım", "tasarim", "ux", "ui", "tipografi", "font", "renk teor", "logo", "arayüz"]):
        return "design"
    if any(k in t for k in ["bilim", "fizik", "biyoloji", "kimya", "nöro", "norö", "psikoloji", "deney", "plasebo", "kuantum"]):
        return "science"
    if any(
        k in t
        for k in [
            "teknoloji",
            "yazılım",
            "yazilim",
            "telefon",
            "şarj",
            "sarj",
            "oyun",
            "internet",
            "şifre",
            "sifre",
            "bulut",
            "cloud",
            "veri merkezi",
            "veri merkez",
            "sunucu",
            "hosting",
            "aws",
            "azure",
            "gcp",
            "kubernetes",
            "docker",
            "sanal",
            "iot",
            "robot",
            "ağ",
            "network",
            "cdn",
        ]
    ):
        return "technology"
    if any(k in t for k in ["duygusal", "ilişki", "iliski", "aşk", "ask", "arkadaş", "platonik", "dram", "romantik"]):
        return "emotional"
    return "general"


VISUAL_STYLE_POOL: dict[str, list[str]] = {
    "ai_tech": [
        "Abstract neural network motifs, soft cyan and electric violet, clean gradients, subtle grid, futuristic but not sci-fi cliché.",
        "Minimal data-viz aesthetic, flowing light particles, dark slate background, one accent color.",
        "Glass morphism layers, soft bokeh lights, tech-lab calm, high-end editorial.",
    ],
    "space": [
        "Deep space nebula hues, sharp stars, realistic cosmic depth, no text, no spaceship silhouette blocking center.",
        "Planetary surface texture hint, horizon glow, dust particles, cinematic contrast.",
        "Starfield with subtle color grading, NASA-poster calm, negative space in center.",
    ],
    "design": [
        "Swiss-style geometric blocks, limited palette, strong negative space, editorial poster.",
        "Soft paper texture, tasteful color swatches, typography-free layout grid.",
        "Minimal Bauhaus-inspired shapes, high contrast, museum catalogue feel.",
    ],
    "science": [
        "Laboratory-inspired abstract: glass refraction, soft microscope bokeh, cool white and teal.",
        "Organic cell micro-patterns, soft greens and blues, scientific but not literal diagram.",
        "Subtle molecular lattice abstraction, muted background, curiosity mood.",
    ],
    "technology": [
        "Macro printed circuit board (PCB): copper traces, solder mask teal or green, gold pads, shallow depth of field, engineering photography.",
        "Server room mood abstracted: rack silhouettes, cool blue LED strips, shallow DOF, data-center atmosphere, no readable labels.",
        "Motherboard close-up abstraction: chips and traces, dark background, amber edge light, crisp technical texture.",
        "Fiber optic and circuit hybrid: glowing lines suggesting throughput, dark slate base, copper accent, hardware feel.",
    ],
    "emotional": [
        "Warm golden-hour gradient, soft bokeh, gentle abstract forms, romantic but not kitsch.",
        "Muted rose and charcoal, cinematic softness, negative space for quote.",
        "Pastel wash, organic shapes, calm hopeful mood.",
    ],
    "general": [
        "Editorial curiosity: abstract intellectual vibe, ink-wash gradients, no romantic stock-photo look.",
        "Soft geometric sunrise palette, science-museum lobby mood.",
        "Cool teal and graphite, subtle texture, professional blog header feel.",
    ],
}


def _deterministic_hardware_image_prompt(topic: str, *, family: str) -> str:
    """
    Teknoloji / AI görsellerinde LLM'in çiçekli-romantik stoka kaymasını engellemek için
    doğrudan devre kartı, sunucu ortamı, çip makrosu tarifleri (DALL·E'ye İngilizce).
    """
    t = (topic or "").strip()[:160] or "technology"
    tl = t.lower()
    cloudish = any(
        k in tl
        for k in [
            "bulut",
            "cloud",
            "sunucu",
            "veri merkez",
            "hosting",
            "aws",
            "azure",
            "gcp",
            "cdn",
            "kubernetes",
            "docker",
            "sanallaştır",
        ]
    )
    negatives = (
        "NO flowers, NO roses, peonies, petals, botanical, wedding, bridal, pastel floral, "
        "romantic bouquet, watercolor garden, vintage botanical illustration."
    )
    if family == "ai_tech":
        core = random.choice(
            [
                "Abstract AI hardware fusion: GPU-like chip package macro, faint circuit traces, cool cyan and violet rim light, dark graphite background.",
                "Neural motif as geometric light paths on a dark PCB substrate, micro-components softly blurred, high-end tech editorial.",
                "Close-up silicon and gold bond wires stylized abstract, matrix of tiny lights suggesting computation, no text.",
            ]
        )
    elif cloudish:
        core = random.choice(
            [
                "Data center aisle abstraction: server rack silhouettes, cool blue LED strips, shallow depth of field, concrete floor hint, industrial tech mood.",
                "Rack servers and fiber-optic glow bokeh, dark cool tones, copper network cable accents abstracted, enterprise infrastructure feel.",
                "Blade server stack macro-inspired abstract: metallic vents, status LED bokeh, steel and black glass, serious infrastructure aesthetic.",
            ]
        )
    else:
        core = random.choice(
            [
                "Extreme macro printed circuit board: green or teal solder mask, copper traces, SMT pads, sharp engineering photography style.",
                "Motherboard fragment abstract: black PCB, gold contacts, silver capacitors softened into bokeh, workshop lighting.",
                "Circuit board corner with traces leading toward center, dark vignette, warm amber edge light on cold blue board.",
            ]
        )
    return (
        f"SQUARE 1:1 aspect ratio Instagram background. {core} "
        f"Clear CENTER area kept calmer, slightly darker or softly blurred for a white text overlay. "
        f"{negatives} NO readable text, NO letters, NO logos, NO watermarks, NO UI screenshots. "
        f"Photorealistic or hyper-real abstract tech, high resolution. Theme context: {t}."
    )


def generate_image_prompt(topic: str, engagement_visual_addon: str | None = None) -> str:
    """
    Kare (1:1) arka plan: metin için negatif alan, konuyla UYUMLU görsel dil.
      Yapay zeka konusuna 'emotional earth tones' varsayılmaz.
    engagement_visual_addon: İngilizce ek görsel yön (etkileşim katmanı).
    """
    family = _image_topic_family(topic)
    raw_topic = (topic or "").strip() or "science and technology curiosity"
    addon = (engagement_visual_addon or "").strip()

    # Donanım / bulut / AI: LLM ara katmanı atlanır — konu-görsel uyumu garanti olsun.
    if family in ("technology", "ai_tech"):
        return _deterministic_hardware_image_prompt(raw_topic, family=family) + (f" {addon}" if addon else "")

    style_hint = random.choice(VISUAL_STYLE_POOL.get(family, VISUAL_STYLE_POOL["general"]))
    theme_sentence = {
        "ai_tech": "Theme must reflect artificial intelligence, computation, and modern tech — not romance or generic quote art.",
        "space": "Theme must reflect space, astronomy, or cosmic scale.",
        "design": "Theme must reflect design craft: composition, color, typography culture (no letters in image).",
        "science": "Theme must reflect scientific discovery, research, or natural laws — not decorative floral wallpaper.",
        "technology": "Theme must reflect devices, connectivity, engineering, or digital life.",
        "emotional": "Theme may reflect emotional / relational mood only because the subject is about emotions or relationships.",
        "general": "Theme: curiosity, learning, knowledge — avoid cliché inspirational quote backgrounds.",
    }[family]

    try:
        client = get_client()
        prompt = (
            "Create ONE concise English image generation prompt for a square (1:1) Instagram background.\n\n"
            f"Subject context (Turkish, preserve meaning): {raw_topic}\n"
            f"Visual family locked: {family}. {theme_sentence}\n"
            f"Style direction (follow closely): {style_hint}\n\n"
            "Hard rules:\n"
            "- No readable text, letters, logos, watermarks, UI mockups.\n"
            "- Clear centered negative space for a light text overlay.\n"
            "- NO flowers, roses, peonies, wedding florals unless family is explicitly emotional/relational.\n"
            "- Unique composition; avoid generic stock motivational poster look.\n"
            "Return ONLY the final image prompt paragraph in English."
        )
        if addon:
            prompt = prompt + "\n\nAdditional creative direction (integrate naturally):\n" + addon
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.82,
            frequency_penalty=0.55,
        )
        content = resp.choices[0].message.content
        base = (content or "").strip()
        return base
    except Exception as e:
        print(f"Warning: Image prompt generation failed: {e}")
        return (
            f"Square 1:1 abstract editorial background, {style_hint} "
            f"clear center negative space for text, no typography, high quality, topic: {raw_topic}"
            + (f" {addon}" if addon else "")
        )


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
