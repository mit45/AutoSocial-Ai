"""
Pillow ile 1080x1080 görsele metin basma.
Arka plan üzerine ortalanmış ana metin + en altta küçük imza.
Temalar: minimal_dark, pastel_soft, neon_city.
Fontlar app/assets/fonts/ içinde TTF olarak kullanılır.
"""

import os
import re
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent.parent.parent
APP_DIR = BASE_DIR / "app"
FONTS_DIR = APP_DIR / "assets" / "fonts"
MEDIA_DIR = BASE_DIR / "media"

# Tema: ana metin rengi, imza rengi, gölge/outline, font boyutları (1080x1080'da rahat okunur)
THEMES = {
    "minimal_dark": {
        "text_color": (255, 255, 255),
        "signature_color": (200, 200, 200),
        "shadow_color": (0, 0, 0),
        "main_font_size": 108,
        "signature_font_size": 54,
        "overlay_color": (0, 0, 0, 150),
        "stroke_width": 2,
    },
    "pastel_soft": {
        "text_color": (80, 70, 90),
        "signature_color": (120, 110, 130),
        "shadow_color": (255, 255, 255),
        "main_font_size": 104,
        "signature_font_size": 52,
        "overlay_color": (255, 255, 255, 180),
        "stroke_width": 1,
    },
    "neon_city": {
        "text_color": (0, 255, 255),
        "signature_color": (255, 100, 255),
        "shadow_color": (0, 0, 20),
        "main_font_size": 110,
        "signature_font_size": 56,
        "overlay_color": (0, 0, 0, 120),
        "stroke_width": 2,
    },
}

# Görsel dışına taşmayı önlemek için maksimum satır sayısı
MAX_TEXT_LINES = 6


def _strip_hashtags_from_text(text: str) -> str:
    """Metinden # ile başlayan etiketleri kaldırır; görselde sadece ana metin kalır."""
    if not text:
        return text
    return re.sub(r"\s*#\S+", "", text).strip()


def _get_font_path(name: str = "main") -> Path | None:
    """app/assets/fonts/ içinde TTF dosyası bulur. Öncelik: main.ttf, *.ttf."""
    if FONTS_DIR.exists():
        preferred = FONTS_DIR / f"{name}.ttf"
        if preferred.exists():
            return preferred
        for f in FONTS_DIR.glob("*.ttf"):
            return f
    return None


def _get_system_font_path() -> Path | None:
    """Sistem TTF fontu (PIL default çok küçük kalmasın diye fallback)."""
    candidates = []
    if os.name == "nt":  # Windows
        windir = os.environ.get("WINDIR", "C:\\Windows")
        candidates = [
            Path(windir) / "Fonts" / "arial.ttf",
            Path(windir) / "Fonts" / "segoeui.ttf",
            Path(windir) / "Fonts" / "calibri.ttf",
        ]
    else:
        candidates = [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _get_emoji_font_path() -> Path | None:
    """Emoji glifleri içeren sistem fontu (🌙 vb. görünsün diye)."""
    if os.name == "nt":  # Windows: Segoe UI Emoji
        windir = os.environ.get("WINDIR", "C:\\Windows")
        candidates = [
            Path(windir) / "Fonts" / "seguiemj.ttf",  # Segoe UI Emoji
            Path(windir) / "Fonts" / "seguiemj_1.ttf",
        ]
    else:
        candidates = [
            Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
            Path("/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf"),
            Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
        ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _is_emoji_char(c: str) -> bool:
    """Karakterin emoji (veya fontta glifi olmayan sembol) olup olmadığı."""
    if len(c) != 1:
        return False
    o = ord(c)
    if o < 0x2600:
        return False
    if 0x2600 <= o <= 0x26FF:
        return True
    if 0x2700 <= o <= 0x27BF:
        return True
    if 0x1F300 <= o <= 0x1F9FF:
        return True
    if 0x1F600 <= o <= 0x1F64F:
        return True
    if 0x1FA00 <= o <= 0x1FA6F:
        return True
    return False


def _split_line_runs(line: str) -> list[tuple[str, bool]]:
    """Satırı (metin, emoji) parçalarına böler. Her öğe (substring, is_emoji)."""
    runs: list[tuple[str, bool]] = []
    current = []
    current_emoji: bool | None = None
    for c in line:
        em = _is_emoji_char(c)
        if current_emoji is None:
            current_emoji = em
            current.append(c)
        elif current_emoji == em:
            current.append(c)
        else:
            runs.append(("".join(current), current_emoji))
            current = [c]
            current_emoji = em
    if current:
        runs.append(("".join(current), current_emoji))
    return runs


def _load_font(
    size: int, name: str = "main"
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Önce app/assets/fonts/, yoksa sistem fontu, son çare PIL default."""
    path = _get_font_path(name)
    if not path:
        path = _get_system_font_path()
    if path:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    return ImageFont.load_default()


def _load_emoji_font(size: int) -> ImageFont.FreeTypeFont | None:
    """Emoji fontu yükler (varsa). Segoe UI Emoji vb."""
    path = _get_emoji_font_path()
    if path:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    return None


def _wrap_text(
    text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int
) -> list[str]:
    """Uzun metni max_width piksel genişliğine göre satırlara böler."""
    words = text.split()
    lines = []
    current = []
    for word in words:
        test = current + [word]
        # draw.textbbox kullan (Pillow 9+); yoksa textsize
        try:
            bbox = font.getbbox(" ".join(test))
            w = bbox[2] - bbox[0]
        except AttributeError:
            w = (
                sum(font.getsize(w)[0] for w in test)
                + (len(test) - 1) * font.getsize(" ")[0]
            )
        if w <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _measure_run(
    s: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None
) -> tuple[int, int]:
    """(genişlik, yükseklik) döner."""
    if not font or not s:
        return 0, 0
    try:
        bbox = font.getbbox(s)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        w, h = font.getsize(s)
        return w, h


def _draw_text_centered(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    img_width: int,
    y_center: int,
    color: tuple[int, int, int],
    shadow_color: tuple[int, int, int] | None = None,
    emoji_font: ImageFont.FreeTypeFont | None = None,
    stroke_width: int = 2,
) -> None:
    """Satırları dikey merkezde ortalanmış çizer. Emoji varsa emoji_font ile çizilir."""
    line_heights = []
    for line in lines:
        if not emoji_font or not any(_is_emoji_char(c) for c in line):
            _, h = _measure_run(line, font)
            line_heights.append(h)
        else:
            runs = _split_line_runs(line)
            h = 0
            for run_text, is_emoji in runs:
                f = emoji_font if is_emoji else font
                _, rh = _measure_run(run_text, f)
                h = max(h, rh)
            line_heights.append(h)
    total_height = sum(line_heights) + (len(lines) - 1) * int(
        (line_heights[0] if line_heights else 0) * 0.2
    )
    y_start = y_center - total_height // 2
    offset = 2 if shadow_color else 0
    for i, line in enumerate(lines):
        line_h = line_heights[i]
        if not emoji_font or not any(_is_emoji_char(c) for c in line):
            line_w, _ = _measure_run(line, font)
            x = (img_width - line_w) // 2
            y = y_start
            if shadow_color and offset:
                # shadow as offset text behind (also acts as stroke fallback)
                draw.text(
                    (x + offset, y + offset),
                    line,
                    font=font,
                    fill=shadow_color,
                    stroke_width=0,
                )
            # draw main text with stroke for better contrast
            try:
                draw.text(
                    (x, y),
                    line,
                    font=font,
                    fill=color,
                    stroke_width=stroke_width,
                    stroke_fill=shadow_color or (0, 0, 0),
                )
            except TypeError:
                # older Pillow may not support stroke_width - fallback
                draw.text((x, y), line, font=font, fill=color)
        else:
            runs = _split_line_runs(line)
            total_w = sum(
                _measure_run(run_text, emoji_font if is_emoji else font)[0]
                for run_text, is_emoji in runs
            )
            x = (img_width - total_w) // 2
            y = y_start
            for run_text, is_emoji in runs:
                if not run_text:
                    continue
                f = emoji_font if is_emoji else font
                run_w, _ = _measure_run(run_text, f)
                if shadow_color and offset:
                    draw.text(
                        (x + offset, y + offset),
                        run_text,
                        font=f,
                        fill=shadow_color,
                        stroke_width=0,
                    )
                try:
                    draw.text(
                        (x, y),
                        run_text,
                        font=f,
                        fill=color,
                        stroke_width=stroke_width,
                        stroke_fill=shadow_color or (0, 0, 0),
                    )
                except TypeError:
                    draw.text((x, y), run_text, font=f, fill=color)
                x += run_w
        y_start += line_h + int(line_h * 0.2)


def ensure_media_dir() -> Path:
    """media/ klasörünü oluşturur."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def render_image(
    background_path: str,
    text: str,
    signature: str,
    style: str = "minimal_dark",
    target: str = "square",
) -> tuple[str, str]:
    """
    1080x1080 arka plan üzerine ortalanmış metin + altta imza basar.

    Args:
        background_path: Arka plan görsel dosya yolu (mutlak veya proje köküne göre).
        text: Ana metin (otomatik satır kırılır).
        signature: En altta küçük imza metni.
        style: minimal_dark | pastel_soft | neon_city

    Returns:
        (relative_path, absolute_path)
        - relative_path: "media/{uuid}.png"
        - absolute_path: Tam dosya yolu (okuma/yükleme için).
    """
    theme = THEMES.get(style, THEMES["minimal_dark"])
    path = Path(background_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        raise FileNotFoundError(f"Background image not found: {path}")

    img = Image.open(path).convert("RGBA")
    # choose canvas size based on target
    if target == "story":
        width, height = 1080, 1920
    else:
        width, height = 1080, 1080
    img = img.resize((width, height), Image.Resampling.LANCZOS)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Görselde etiket (#hashtag) olmasın; sadece ana metin
    text_only = _strip_hashtags_from_text((text or "").strip() or " ")

    # Dynamically choose main font size so that all text fits within the allowed box.
    preferred_size = int(theme.get("main_font_size", 108))
    min_size = 10  # minimum readable size (more aggressive to fit long text)
    max_text_width = width - 40
    # reserve space for signature and margins (proportional to canvas)
    top_margin = int(height * 0.04)
    bottom_margin = int(height * 0.08)
    max_text_height = height - (top_margin + bottom_margin)

    chosen_size = preferred_size
    chosen_font = _load_font(chosen_size, "main")
    emoji_font = _load_emoji_font(chosen_size)

    def text_block_dimensions(font, emoji_f):
        lines_local = _wrap_text(text_only, font, max_text_width)
        # allow more lines but cap to a reasonable maximum to avoid excessive overflow
        if len(lines_local) > max(20, MAX_TEXT_LINES):
            lines_local = lines_local[: max(20, MAX_TEXT_LINES)]
        total_h_local = 0
        max_w_local = 0
        for line in lines_local:
            if emoji_f and any(_is_emoji_char(c) for c in line):
                runs = _split_line_runs(line)
                line_w = 0
                line_h = 0
                for run_text, is_emoji in runs:
                    f = emoji_f if is_emoji else font
                    w, h = _measure_run(run_text, f)
                    line_w += w
                    line_h = max(line_h, h)
            else:
                line_w, line_h = _measure_run(line, font)
            max_w_local = max(max_w_local, line_w)
            total_h_local += line_h
        # line spacing (reduced)
        spacing_local = (
            int((line_h if "line_h" in locals() else preferred_size) * 0.12)
            if total_h_local
            else 0
        )
        total_h_local += spacing_local * (
            len(lines_local) - 1 if len(lines_local) > 1 else 0
        )
        return max_w_local, total_h_local, lines_local

    # Try decreasing sizes until it fits within allowed height and width
    for size in range(preferred_size, min_size - 1, -1):
        f = _load_font(size, "main")
        ef = _load_emoji_font(size)
        max_w_local, total_h_local, lines_try = text_block_dimensions(f, ef)
        if max_w_local <= max_text_width and total_h_local <= max_text_height:
            chosen_size = size
            chosen_font = f
            emoji_font = ef
            lines = lines_try
            break
    else:
        # fallback: use min size and wrap/truncate
        chosen_font = _load_font(min_size, "main")
        emoji_font = _load_emoji_font(min_size)
        lines = _wrap_text(text_only, chosen_font, max_text_width)[:MAX_TEXT_LINES]

    sig_font = _load_font(theme["signature_font_size"], "signature")
    if sig_font == chosen_font or getattr(sig_font, "getsize", None) is None:
        sig_font = _load_font(theme["signature_font_size"], "main")

    # lines and chosen_font determined above by dynamic sizing

    # Ana metin: dikey merkeze yakın (imza için altta yer bırak); emoji ayrı font ile
    if target == "story":
        # slightly higher for stories to avoid UI overlays
        text_center_y = int(height * 0.45)
    else:
        text_center_y = height // 2 - int(height * 0.055)

    # Compute bounding box for the text block to draw a translucent overlay behind it for legibility
    line_dims = []
    max_w = 0
    total_h = 0
    for line in lines:
        if emoji_font and any(_is_emoji_char(c) for c in line):
            runs = _split_line_runs(line)
            line_w = 0
            line_h = 0
            for run_text, is_emoji in runs:
                f = emoji_font if is_emoji else chosen_font
                w, h = _measure_run(run_text, f)
                line_w += w
                line_h = max(line_h, h)
        else:
            line_w, line_h = _measure_run(line, chosen_font)
        line_dims.append((line_w, line_h))
        max_w = max(max_w, line_w)
        total_h += line_h
    # line spacing (reduced)
    spacing = int((line_dims[0][1] if line_dims else 40) * 0.12) if line_dims else 4
    total_h += spacing * (len(line_dims) - 1 if len(line_dims) > 1 else 0)

    padding_x = max(12, int(width * 0.01))
    padding_y = max(10, int(height * 0.005))
    box_w = max_w + padding_x * 2
    box_h = total_h + padding_y * 2
    box_x0 = (width - box_w) // 2
    box_y0 = text_center_y - (box_h // 2)
    box_x1 = box_x0 + box_w
    box_y1 = box_y0 + box_h

    # MOBILE SAFE AREA: ensure the text box fits within a central safe area
    SAFE_PCT = 0.06  # 6% inset on each side as safe margins for mobile cropping
    safe_left = int(width * SAFE_PCT)
    safe_right = int(width * (1 - SAFE_PCT))
    safe_width = safe_right - safe_left
    # safe height reserve (avoid top UI and bottom overlays)
    safe_top = int(height * SAFE_PCT)
    safe_bottom = int(height * (1 - SAFE_PCT))
    safe_height = (
        safe_bottom - safe_top - int(height * 0.06)
    )  # reserve some space for signature etc.

    # If box exceeds safe bounds, reduce font size further until it fits (aggressive)
    while (box_w > safe_width or box_h > safe_height) and chosen_size > min_size:
        chosen_size -= 1
        chosen_font = _load_font(chosen_size, "main")
        emoji_font = _load_emoji_font(chosen_size)
        # recompute lines and dims
        max_w = 0
        total_h = 0
        line_dims = []
        for line in _wrap_text(text_only, chosen_font, max_text_width):
            if emoji_font and any(_is_emoji_char(c) for c in line):
                runs = _split_line_runs(line)
                line_w = 0
                line_h = 0
                for run_text, is_emoji in runs:
                    f = emoji_font if is_emoji else chosen_font
                    w, h = _measure_run(run_text, f)
                    line_w += w
                    line_h = max(line_h, h)
            else:
                line_w, line_h = _measure_run(line, chosen_font)
            line_dims.append((line_w, line_h))
            max_w = max(max_w, line_w)
            total_h += line_h
        spacing = int((line_dims[0][1] if line_dims else 40) * 0.12) if line_dims else 4
        total_h += spacing * (len(line_dims) - 1 if len(line_dims) > 1 else 0)
        box_w = max_w + padding_x * 2
        box_h = total_h + padding_y * 2
        box_x0 = (width - box_w) // 2
        box_y0 = text_center_y - (box_h // 2)
        box_x1 = box_x0 + box_w
        box_y1 = box_y0 + box_h

    # Draw overlay rectangle on overlay layer for improved contrast
    overlay_color = theme.get("overlay_color", (0, 0, 0, 140))
    try:
        draw.rectangle([(box_x0, box_y0), (box_x1, box_y1)], fill=overlay_color)
    except Exception:
        # fallback if draw.rectangle doesn't accept RGBA on this layer
        draw.rectangle([(box_x0, box_y0), (box_x1, box_y1)], fill=overlay_color[:3])

    # Draw the text (with stroke/shadow)
    _draw_text_centered(
        draw,
        lines,
        chosen_font,
        width,
        text_center_y,
        theme["text_color"],
        theme.get("shadow_color"),
        emoji_font=emoji_font,
        stroke_width=theme.get("stroke_width", 2),
    )

    # İmza: sadece altta "ince düşlerim" (veya body'den gelen)
    sig_text = (signature or "ince düşlerim").strip() or "ince düşlerim"
    try:
        sb = sig_font.getbbox(sig_text)
        sig_w = sb[2] - sb[0]
        sig_h = sb[3] - sb[1]
    except AttributeError:
        sig_w, sig_h = sig_font.getsize(sig_text)
    sig_x = (width - sig_w) // 2
    sig_y = height - int(height * 0.05) - sig_h
    if theme.get("shadow_color"):
        draw.text(
            (sig_x + 1, sig_y + 1), sig_text, font=sig_font, fill=theme["shadow_color"]
        )
    draw.text((sig_x, sig_y), sig_text, font=sig_font, fill=theme["signature_color"])

    out = Image.alpha_composite(img, overlay).convert("RGB")
    ensure_media_dir()
    filename = f"{uuid4()}.png"
    rel_path = f"media/{filename}"
    abs_path = MEDIA_DIR / filename
    out.save(abs_path, "PNG", optimize=True)
    return rel_path, str(abs_path)
