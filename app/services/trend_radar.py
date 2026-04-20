import random

# İçerik türleri: ilginç bilgiler, bilim, teknoloji, yapay zeka, tasarım, uzay
CONTENT_TYPES = [
    "ilginç_bilgi",
    "bilim",
    "teknoloji",
    "yapay_zeka",
    "tasarim",
    "uzay",
]

# Tür bazlı konu havuzları – aynı konu peş peşe gelmesin diye tür ve konu çeşitliliği
TOPICS_ILGINC = [
    "çoğu insanın yanlış bildiği ama günlük hayatta sık görülen bir gerçek",
    "fazla mantıklı görünüp aslında tam tersi olan günlük bir inanç",
    "telefonda / ekranda fark etmeden yaptığın davranışın psikolojik karşılığı",
    "dünyadaki en ilginç hayvan savunma mekanizmaları",
    "renk algısının kültüre göre değişmesi",
    "uykuda beynin yaptığı gizli temizlik",
    "zaman algısının stres altında neden bozulduğu",
    "alışkanlıkların beyindeki izi",
    "bir gününü kurtaracak küçük ama şaşırtıcı bir bilgi",
    "akışta 'dur bi dakika' dedirtecek az bilinen bir gerçek",
]

TOPICS_BILIM = [
    "herkesin 'bildiğini sandığı' ama bilimde tartışmalı veya yanlış anlaşılan bir şey",
    "kuantum fiziğinin günlük hayata etkileri",
    "evrende rastgelelik mi düzen mi baskın",
    "plasebo etkisinin bilimi",
    "beyin plastisitesi ve öğrenme",
    "ışık hızına yaklaşmanın sonuçları",
    "kaos teorisi ve hava durumu",
    "iklim biliminin temel gerçekleri",
    "bilimsel düşünme ve yalın deneyler",
    "stres anında vücudunun yaptığı 'sessiz alarm' ve algı",
]

TOPICS_TEKNOLOJI = [
    "uygulamaların seni ekranda tutmak için kullandığı 'küçük hileler' (etik çerçevede)",
    "akıllı telefonların gizli sensörleri",
    "şarj döngüleri ve pil sağlığı",
    "bulut teknolojisinin perde arkası",
    "oyun motorlarının gerçekçi fizik hileleri",
    "şifre güvenliği ve parola üretme ipuçları",
    "nesnelerin interneti ile akıllı evler",
    "giyilebilir teknolojilerin geleceği",
    "internet altyapısının basitleştirilmiş haritası",
    "VPN / izleme / çerez konusunda herkesin karıştırdığı nokta",
]

TOPICS_AI = [
    "ChatGPT / benzeri araçlarda herkesin yaptığı 1 yaygın hata ve doğrusu",
    "yapay zekanın nasıl öğrendiğini basitçe anlatmak",
    "günlük hayatta fark etmeden kullandığımız yapay zeka örnekleri",
    "yapay zeka önyargıları ve veri setleri",
    "dijital asistanların perde arkası",
    "makine öğrenmesi ile klasik programlama farkı",
    "yapay zekayla üretkenliği artırma yolları",
    "metin üretim modellerinin sınırları",
    "yapay zekayı doğru sorularla yönlendirmek",
    "AI ile içerik üretirken 'insan gibi duran ama riskli' tuzak",
]

TOPICS_TASARIM = [
    "profil veya feed'inde 'ucuz görünen' 3 küçük tasarım hatası",
    "göz yormayan arayüz tasarımı püf noktaları",
    "renk teorisi ve markalaşma",
    "tipografinin hissettirdikleri",
    "boşluk (white space) kullanımının gücü",
    "kötü tasarım örneklerinden öğrenilen dersler",
    "ikna edici landing page öğeleri",
    "mobil öncelikli tasarım düşüncesi",
    "ikon tasarımında yapılmaması gerekenler",
]

TOPICS_UZAY = [
    "kara delikleri günlük dilde anlatırken yapılan en büyük kafa karışıklığı",
    "kara deliklerin gerçekten ne yaptığı",
    "ışık yılının günlük hayatta anlaşılır karşılığı",
    "Mars'a gitmenin mühendislik zorlukları",
    "evrende yalnız mıyız sorusuna bilimsel bakış",
    "uzay istasyonunda yaşamın tuhaflıkları",
    "gezegenlerin oluşum süreci",
    "evrenin sonu hakkında senaryolar",
    "gözle görülebilen takımyıldızların hikayeleri",
    "Mars gökyüzü / Dünya'dan bakış: ölçek şoku hissi veren bir karşılaştırma",
]

# Genel havuz: yukarıdaki tüm konuların birleşimi
TOPIC_POOL = (
    TOPICS_ILGINC
    + TOPICS_BILIM
    + TOPICS_TEKNOLOJI
    + TOPICS_AI
    + TOPICS_TASARIM
    + TOPICS_UZAY
)


def get_topic_pool_for_type(content_type: str) -> list[str]:
    """Verilen içerik türüne göre konu havuzu döndürür."""
    if content_type == "ilginç_bilgi":
        return list(TOPICS_ILGINC)
    if content_type == "bilim":
        return list(TOPICS_BILIM)
    if content_type == "teknoloji":
        return list(TOPICS_TEKNOLOJI)
    if content_type == "yapay_zeka":
        return list(TOPICS_AI)
    if content_type == "tasarim":
        return list(TOPICS_TASARIM)
    if content_type == "uzay":
        return list(TOPICS_UZAY)
    # Varsayılan: tüm havuzdan karışık
    return list(TOPIC_POOL)


def get_next_topic_and_type(
    exclude_last_topic: str | None = None,
    exclude_last_type: str | None = None,
    exclude_recent_topics: list[str] | None = None,
    exclude_recent_types: list[str] | None = None,
) -> tuple[str, str]:
    """
    Her seferinde farklı tür ve konu seçer. Güncel trend ve çeşitlilik öncelikli.
    exclude_recent_topics: Son N gönderide kullanılan konular (hepsi hariç tutulur).
    exclude_recent_types: Son gönderilerde kullanılan türler (mümkünse farklı tür seçilir).
    Returns: (topic, content_type)
    """
    types_available = list(CONTENT_TYPES)
    # Önce son kullanılan türleri çıkar (tür çeşitliliği)
    if exclude_recent_types:
        types_available = [t for t in types_available if t not in exclude_recent_types]
    if exclude_last_type and exclude_last_type in types_available:
        types_available = [t for t in types_available if t != exclude_last_type]
    if not types_available:
        types_available = list(CONTENT_TYPES)
    content_type = random.choice(types_available)
    pool = get_topic_pool_for_type(content_type)
    # Son konuyu ve son N konuyu hariç tut
    exclude_set = set()
    if exclude_last_topic:
        exclude_set.add(exclude_last_topic)
    if exclude_recent_topics:
        exclude_set.update(exclude_recent_topics)
    candidates = [t for t in pool if t not in exclude_set] if exclude_set else pool
    if not candidates:
        candidates = pool
    topic = random.choice(candidates)
    return (topic, content_type)


def get_trending_topics(count: int = 7, exclude_last_topic: str | None = None) -> list[str]:
    """
    Güncel trend ve çeşitli konulardan rastgele seçim. exclude_last_topic verilirse havuzdan çıkarılır.
    """
    pool = list(TOPIC_POOL)
    if exclude_last_topic and exclude_last_topic in pool:
        pool = [t for t in pool if t != exclude_last_topic]
    if not pool:
        pool = list(TOPIC_POOL)
    random.shuffle(pool)
    return list(pool[: min(count, len(pool))])
