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
        "signature_color": (220, 220, 220),
        "shadow_color": (0, 0, 0),
        "main_font_size": 140,
        "signature_font_size": 28,
        "overlay_color": (0, 0, 0, 230),
        "stroke_width": 4,
    },
    "pastel_soft": {
        "text_color": (40, 30, 40),
        "signature_color": (100, 95, 110),
        "shadow_color": (255, 255, 255),
        "main_font_size": 128,
        "signature_font_size": 28,
        "overlay_color": (255, 255, 255, 230),
        "stroke_width": 3,
    },
    "neon_city": {
        "text_color": (255, 255, 255),
        "signature_color": (240, 150, 240),
        "shadow_color": (0, 0, 20),
        "main_font_size": 140,
        "signature_font_size": 28,
        "overlay_color": (0, 0, 0, 200),
        "stroke_width": 4,
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
                # Manual outline fallback: draw text multiple times offset to simulate stroke
                sw = max(1, int(stroke_width))
                for dx in range(-sw, sw + 1):
                    for dy in range(-sw, sw + 1):
                        if dx == 0 and dy == 0:
                            continue
                        draw.text((x + dx, y + dy), line, font=font, fill=shadow_color or (0, 0, 0))
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
                    sw = max(1, int(stroke_width))
                    for dx in range(-sw, sw + 1):
                        for dy in range(-sw, sw + 1):
                            if dx == 0 and dy == 0:
                                continue
                            draw.text((x + dx, y + dy), run_text, font=f, fill=shadow_color or (0, 0, 0))
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
    full_height: bool = True,
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
    # choose canvas size based on target (enforce exact sizes)
    if target == "story":
        width, height = 1080, 1920
    else:
        width, height = 1080, 1080
    # For stories, avoid cropping important parts by fitting the image inside the canvas
    # (scale down to fit and paste centered) instead of resizing to cover which may crop edges.
    if target == "story":
        # compute scale to fit inside canvas
        img_w, img_h = img.width, img.height
        scale = min(width / img_w, height / img_h)
        new_w = max(1, int(img_w * scale))
        new_h = max(1, int(img_h * scale))
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        paste_x = (width - new_w) // 2
        paste_y = (height - new_h) // 2
        canvas.paste(img_resized, (paste_x, paste_y))
        img = canvas
    else:
        img = img.resize((width, height), Image.Resampling.LANCZOS)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Görselde etiket (#hashtag) olmasın; sadece ana metin
    text_only = _strip_hashtags_from_text((text or "").strip() or " ")

    # Dynamically choose main font size so that all text fits within the allowed box.
    min_size = 10  # minimum readable size
    # Set defaults that respect requested story/post rules:
    if target == "story":
        # Story safe area (fixed as requested)
        SAFE_TOP = 250
        SAFE_BOTTOM = height - 350
        SAFE_LEFT = 80
        SAFE_RIGHT = width - 80
        # Wrap and font defaults for story
        preferred_size = 72  # story default font size
        max_text_width = 850  # px as requested
        # Max text height is safe area height
        top_margin = SAFE_TOP
        bottom_margin = height - SAFE_BOTTOM
        max_text_height = SAFE_BOTTOM - SAFE_TOP
        single_line_mode = False
        desired_text_height = int(max_text_height * 0.85)
    else:
        # Post defaults
        preferred_size = 58  # post default font size
        max_text_width = 900  # px as requested
        # Use conservative margins for post
        top_margin = int(height * 0.04)
        bottom_margin = int(height * 0.08)
        max_text_height = height - (top_margin + bottom_margin)
        single_line_mode = False

    chosen_size = preferred_size
    chosen_font = _load_font(chosen_size, "main")
    emoji_font = _load_emoji_font(chosen_size)

    def text_block_dimensions(font, emoji_f):
        # If single_line_mode requested, treat the whole text as one line (no wrapping)
        if single_line_mode:
            lines_local = [text_only]
        else:
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

    # Select font size.
    if full_height:
        # Try different target line counts to find the combination that fills
        # the height best while respecting width. Prefer fewer, larger lines.
        best_score = -1
        best_choice = None
        max_lines_try = max(1, min(MAX_TEXT_LINES, 12))
        for target_lines in range(1, max_lines_try + 1):
            # try font sizes from preferred down to min to find largest that produces <= target_lines
            for size in range(preferred_size, min_size - 1, -1):
                f = _load_font(size, "main")
                ef = _load_emoji_font(size)
                # wrap text with this font and measure lines
                lines_try = _wrap_text(text_only, f, max_text_width)
                if len(lines_try) > target_lines:
                    continue
                # measure total height for these lines
                _, total_h_local, lines_measured = text_block_dimensions(f, ef)
                if total_h_local <= max_text_height:
                    # score by how much of desired_text_height we fill (closer is better)
                    score = total_h_local
                    if score > best_score:
                        best_score = score
                        best_choice = {
                            "size": size,
                            "font": f,
                            "ef": ef,
                            "lines": lines_measured,
                        }
                    # since we iterate sizes descending, break to try fewer lines (bigger sizes first)
                    break
        if best_choice:
            chosen_size = best_choice["size"]
            chosen_font = best_choice["font"]
            emoji_font = best_choice["ef"]
            lines = best_choice["lines"]
        else:
            # fallback: reduce until something fits
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
        # Try decreasing sizes until it fits within allowed height and width.
        # Start from preferred_size.
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
    # Ensure fallback if nothing set
    if "lines" not in locals() or not lines:
        chosen_font = _load_font(min_size, "main")
        emoji_font = _load_emoji_font(min_size)
        lines = _wrap_text(text_only, chosen_font, max_text_width)[:MAX_TEXT_LINES]

    # If full_height requested, try increasing font size (grow) while it still fits width
    if full_height:
        try:
            size = chosen_size
            while True:
                nxt = size + 1
                f = _load_font(nxt, "main")
                ef = _load_emoji_font(nxt)
                max_w_local, total_h_local, lines_try = text_block_dimensions(f, ef)
                if max_w_local <= max_text_width and total_h_local <= max_text_height and total_h_local < desired_text_height:
                    size = nxt
                    chosen_size = size
                    chosen_font = f
                    emoji_font = ef
                    lines = lines_try
                    # continue trying to grow
                    continue
                break
        except Exception:
            pass

    # Load signature font; for story target use a slightly smaller signature to avoid bottom UI overlap
    sig_size = theme.get("signature_font_size", 28)
    if target == "story":
        sig_size = max(12, int(sig_size * 0.75))
    sig_font = _load_font(sig_size, "signature")
    if sig_font == chosen_font or getattr(sig_font, "getsize", None) is None:
        sig_font = _load_font(sig_size, "main")

    # lines and chosen_font determined above by dynamic sizing

    # Compute text center relative to safe area so text is always inside safe area
    if target == "story":
        # center of safe area
        SAFE_TOP = 250
        SAFE_BOTTOM = height - 350
        safe_center_y = SAFE_TOP + (SAFE_BOTTOM - SAFE_TOP) // 2
        text_center_y = int(safe_center_y)
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
    # For story target, use slightly larger vertical padding so text doesn't touch UI edges
    padding_y = max(12, int(height * 0.02)) if target == "story" else max(10, int(height * 0.005))
    box_w = max_w + padding_x * 2
    box_h = total_h + padding_y * 2
    box_x0 = (width - box_w) // 2
    box_y0 = text_center_y - (box_h // 2)
    box_x1 = box_x0 + box_w
    box_y1 = box_y0 + box_h

    # Ensure the text box fits within the safe area for story
    if target == "story":
        SAFE_LEFT = 80
        SAFE_RIGHT = width - 80
        SAFE_TOP = 250
        SAFE_BOTTOM = height - 350
        # clamp horizontally
        if box_x0 < SAFE_LEFT:
            shift = SAFE_LEFT - box_x0
            box_x0 += shift
            box_x1 += shift
        if box_x1 > SAFE_RIGHT:
            shift = box_x1 - SAFE_RIGHT
            box_x0 -= shift
            box_x1 -= shift
        # clamp vertically
        if box_y0 < SAFE_TOP:
            shift = SAFE_TOP - box_y0
            box_y0 += shift
            box_y1 += shift
        if box_y1 > SAFE_BOTTOM:
            shift = box_y1 - SAFE_BOTTOM
            box_y0 -= shift
            box_y1 -= shift

    # MOBILE SAFE AREA: ensure the text box fits within a central safe area
    # Increase safe area for stories to avoid mobile UI overlays (status bar, gestures)
    SAFE_PCT = 0.10 if target == "story" else 0.06  # inset on each side as safe margins for mobile cropping
    safe_left = int(width * SAFE_PCT)
    safe_right = int(width * (1 - SAFE_PCT))
    safe_width = safe_right - safe_left
    # safe height reserve (avoid top UI and bottom overlays)
    safe_top = int(height * SAFE_PCT)
    safe_bottom = int(height * (1 - SAFE_PCT))
    safe_height = (
        safe_bottom - safe_top - int(height * 0.06)
    )  # reserve some space for signature etc.

    # If box exceeds safe bounds, reduce font size further until it fits (aggressive).
    # For story target we DO perform aggressive shrinking even in full_height mode to avoid mobile overflow.
    if not full_height or target == "story":
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
    # If full_height mode requested, use fully opaque black overlay and force white bold text
    if full_height:
        # Use a semi-transparent (opal) overlay so the background image is slightly visible.
        overlay_color = (0, 0, 0, 160)
        text_color_local = (255, 255, 255)
        signature_color_local = (255, 255, 255)
        # Reduce stroke for large story text so outline doesn't push into safe area
        stroke_w_local = 2 if target == "story" else max(3, int(theme.get("stroke_width", 2)))
    else:
        overlay_color = theme.get("overlay_color", (0, 0, 0, 140))
        text_color_local = theme.get("text_color")
        signature_color_local = theme.get("signature_color")
        stroke_w_local = theme.get("stroke_width", 2)
    # Removed translucent background box per user request: only draw text (keep stroke/shadow for contrast)
    # Previously: draw.rectangle([(box_x0, box_y0), (box_x1, box_y1)], fill=overlay_color)

    # Draw the text (with stroke/shadow)
    # Use local overrides for full_height readability
    _draw_text_centered(
        draw,
        lines,
        chosen_font,
        width,
        text_center_y,
        text_color_local,
        theme.get("shadow_color"),
        emoji_font=emoji_font,
        stroke_width=stroke_w_local,
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
    # For story target, move signature further up to avoid bottom UI on mobile
    if target == "story":
        sig_y = height - int(height * 0.08) - sig_h
    else:
        sig_y = height - int(height * 0.05) - sig_h
    # draw signature with local signature color override if present
    try:
        shadow_col = theme.get("shadow_color")
        sig_col = signature_color_local if "signature_color_local" in locals() else theme["signature_color"]
        if shadow_col:
            draw.text((sig_x + 1, sig_y + 1), sig_text, font=sig_font, fill=shadow_col)
        draw.text((sig_x, sig_y), sig_text, font=sig_font, fill=sig_col)
    except Exception:
        draw.text((sig_x, sig_y), sig_text, font=sig_font, fill=theme.get("signature_color", (200, 200, 200)))

    out = Image.alpha_composite(img, overlay).convert("RGB")
    ensure_media_dir()
    filename = f"{uuid4()}.png"
    rel_path = f"media/{filename}"
    abs_path = MEDIA_DIR / filename
    out.save(abs_path, "PNG", optimize=True)
    return rel_path, str(abs_path)


def render_story_image(text: str, output_filename: str | None = None, style: str = "minimal_dark") -> str:
    """
    Generate an AI background, render `text` centered inside the story safe area,
    save and upload to remote storage under ig/story and return public URL.

    Returns public URL string on success, raises on failure.
    """
    from app.services import content_ai
    from app.services import storage_backend
    import tempfile
    import os

    # Ensure exact story canvas
    width, height = 1080, 1920
    SAFE_TOP = 250
    SAFE_BOTTOM = height - 250
    SAFE_LEFT = 120
    SAFE_RIGHT = width - 120
    SAFE_WIDTH = SAFE_RIGHT - SAFE_LEFT
    SAFE_HEIGHT = SAFE_BOTTOM - SAFE_TOP
    # Text box visual parameters
    BOX_MAX_WIDTH = 720
    BOX_PADDING = 40
    BOX_BG = (0, 0, 0, int(0.45 * 255))  # rgba(0,0,0,0.45)
    BOX_RADIUS = 28
    FONT_MAX = 64
    FONT_MIN = 34
    CONTENT_MAX_WIDTH = min(SAFE_WIDTH, BOX_MAX_WIDTH) - BOX_PADDING * 2

    # Generate AI background bytes using content_ai (uses OpenAI)
    try:
        prompt = content_ai.generate_image_prompt(text or "soft background")
        bg_bytes = content_ai.generate_image_png_bytes(prompt)
    except Exception as e:
        # fallback to visual_ai fallback URL
        from app.services.visual_ai import FALLBACK_IMAGE_URL
        import requests

        try:
            r = requests.get(FALLBACK_IMAGE_URL, timeout=30)
            r.raise_for_status()
            bg_bytes = r.content
        except Exception as e2:
            raise RuntimeError(f"Failed to obtain background image: {e} / {e2}") from e2

    # Write bg_bytes to temp file and open
    tmp_bg = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    try:
        tmp_bg.write(bg_bytes)
        tmp_bg.flush()
        tmp_bg_path = tmp_bg.name
    finally:
        tmp_bg.close()

    try:
        img = Image.open(tmp_bg_path).convert("RGBA")
        # Fit background to story canvas: prefer fitting by width so left/right are never cropped.
        # We choose width-scaling when it keeps height within canvas; otherwise scale by height.
        img_w, img_h = img.width, img.height
        scale_w = width / img_w
        scale_h = height / img_h
        # Prefer scaling to width if it doesn't overflow vertically; otherwise scale to height.
        if img_h * scale_w <= height:
            scale = scale_w
        else:
            scale = scale_h
        new_w = max(1, int(img_w * scale))
        new_h = max(1, int(img_h * scale))
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        # center image on canvas (no cropping), allowing vertical margins if any
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        paste_x = (width - new_w) // 2
        paste_y = (height - new_h) // 2
        canvas.paste(img_resized, (paste_x, paste_y))

        # Prepare drawing layers
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Clean text
        text_only = _strip_hashtags_from_text((text or "").strip() or " ")

        # Helper to try fit text at a font size
        def fit_text_at_size(font_size):
            f = _load_font(font_size, "main")
            ef = _load_emoji_font(font_size)
            lines = _wrap_text(text_only, f, CONTENT_MAX_WIDTH)
            # compute total height
            heights = []
            for ln in lines:
                if ef and any(_is_emoji_char(c) for c in ln):
                    runs = _split_line_runs(ln)
                    h = 0
                    for rt, is_e in runs:
                        h = max(h, _measure_run(rt, ef if is_e else f)[1])
                    heights.append(h)
                else:
                    heights.append(_measure_run(ln, f)[1])
            spacing = int(font_size * 0.12) if heights else 0
            total_h = sum(heights) + spacing * (len(heights) - 1 if len(heights) > 1 else 0)
            return lines, total_h, f, ef

        # Try decreasing font until fits within safe area (account for box padding)
        chosen_font_size = FONT_MAX
        chosen_lines = []
        chosen_font = None
        chosen_ef = None
        max_box_height = SAFE_HEIGHT - BOX_PADDING * 2
        for fs in range(FONT_MAX, FONT_MIN - 1, -2):
            lines, total_h, f, ef = fit_text_at_size(fs)
            if total_h <= max_box_height and len(lines) > 0 and max(_measure_run(ln, f)[0] for ln in lines) <= CONTENT_MAX_WIDTH:
                chosen_font_size = fs
                chosen_lines = lines
                chosen_font = f
                chosen_ef = ef
                break

        # If still not fitted, use min font and then truncate words until fits
        truncated = False
        if not chosen_lines:
            fs = FONT_MIN
            lines, total_h, f, ef = fit_text_at_size(fs)
            # If total_h too large or some line too wide, truncate text words
            if total_h <= max_box_height and max(_measure_run(ln, f)[0] for ln in lines) <= CONTENT_MAX_WIDTH:
                chosen_font_size = fs
                chosen_lines = lines
                chosen_font = f
                chosen_ef = ef
            else:
                words = text_only.split()
                if not words:
                    chosen_font_size = fs
                    chosen_lines = [text_only]
                    chosen_font = f
                    chosen_ef = ef
                else:
                    # progressively shorten
                    for n in range(len(words), 0, -1):
                        candidate = " ".join(words[:n]) + ("…" if n < len(words) else "")
                        # measure
                        tmp_lines = _wrap_text(candidate, f, CONTENT_MAX_WIDTH)
                        heights = []
                        for ln in tmp_lines:
                            if ef and any(_is_emoji_char(c) for c in ln):
                                runs = _split_line_runs(ln)
                                h = 0
                                for rt, is_e in runs:
                                    h = max(h, _measure_run(rt, ef if is_e else f)[1])
                                heights.append(h)
                            else:
                                heights.append(_measure_run(ln, f)[1])
                        spacing = int(fs * 0.12) if heights else 0
                        tot_h = sum(heights) + spacing * (len(heights) - 1 if len(heights) > 1 else 0)
                        if tot_h <= max_box_height and max(_measure_run(ln, f)[0] for ln in tmp_lines) <= CONTENT_MAX_WIDTH:
                            chosen_font_size = fs
                            chosen_lines = tmp_lines
                            chosen_font = f
                            chosen_ef = ef
                            truncated = (n < len(words))
                            break
        # If still nothing, fallback to single-line truncate
        if not chosen_lines:
            fs = FONT_MIN
            f = _load_font(fs, "main")
            ef = _load_emoji_font(fs)
            # truncate to fit width with ellipsis
            s = text_only
            while s and _measure_run(s + "…", f)[0] > CONTENT_MAX_WIDTH:
                s = s[:-1]
            chosen_lines = [s + "…"]
            chosen_font = f
            chosen_ef = ef
            truncated = True

        # Compute box dimensions
        line_heights = [(_measure_run(ln, chosen_ef if (chosen_ef and any(_is_emoji_char(c) for c in ln)) else chosen_font)[1]) for ln in chosen_lines]
        spacing = int(chosen_font_size * 0.12) if line_heights else 0
        total_h = sum(line_heights) + spacing * (len(line_heights) - 1 if len(line_heights) > 1 else 0)
        box_w = min(BOX_MAX_WIDTH, SAFE_WIDTH)
        box_h = total_h + BOX_PADDING * 2
        box_x0 = SAFE_LEFT + (SAFE_WIDTH - box_w) // 2
        box_y0 = SAFE_TOP + (SAFE_HEIGHT - box_h) // 2
        box_x1 = box_x0 + box_w
        box_y1 = box_y0 + box_h

        # Removed rounded rectangle background box per user request:
        # keep text_layer (transparent background) pasted over the image so only text is visible.

        # Draw text centered inside box onto a clipped text layer to avoid overflow
        text_layer_w = CONTENT_MAX_WIDTH
        max_box_inner_h = box_h - BOX_PADDING * 2
        text_layer_h = max_box_inner_h
        text_layer = Image.new("RGBA", (text_layer_w, text_layer_h), (0, 0, 0, 0))
        tdraw = ImageDraw.Draw(text_layer)
        ty = 0
        for ln in chosen_lines:
            # measure with chosen_font / chosen_ef
            if chosen_ef and any(_is_emoji_char(c) for c in ln):
                # draw runs centered within text_layer_w
                runs = _split_line_runs(ln)
                total_w = sum(_measure_run(rt, chosen_ef if is_e else chosen_font)[0] for rt, is_e in runs)
                tx = (text_layer_w - total_w) // 2
                for rt, is_e in runs:
                    f2 = chosen_ef if is_e else chosen_font
                    tdraw.text((tx, ty), rt, font=f2, fill=(255, 255, 255))
                    w, h = _measure_run(rt, f2)
                    tx += w
                # advance by line height using chosen_font metrics
                lh = _measure_run(ln, chosen_font)[1]
                ty += lh + spacing
            else:
                line_w, line_h = _measure_run(ln, chosen_font)
                tx = (text_layer_w - line_w) // 2
                tdraw.text((tx, ty), ln, font=chosen_font, fill=(255, 255, 255))
                ty += line_h + spacing

        # Paste the clipped text layer into overlay at box position (respecting padding)
        overlay.paste(text_layer, (box_x0 + BOX_PADDING, box_y0 + BOX_PADDING), text_layer)

        out = Image.alpha_composite(canvas, overlay).convert("RGB")

        # Save and upload
        out_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        try:
            out.save(out_tmp.name, "PNG", optimize=True)
            out_tmp.flush()
            final_path = out_tmp.name
        finally:
            out_tmp.close()

        with open(final_path, "rb") as f:
            final_bytes = f.read()
        filename = output_filename or f"{uuid4()}.png"
        public_url = storage_backend.upload_to_remote_server(final_bytes, filename, prefix="ig/story")

        try:
            os.remove(tmp_bg_path)
        except Exception:
            pass
        try:
            os.remove(final_path)
        except Exception:
            pass

        return public_url
    except Exception as e:
        try:
            os.remove(tmp_bg_path)
        except Exception:
            pass
        raise


def make_story_from_post(image_path_or_url: str, output_filename: str | None = None, bg_mode: str = "blur", solid_color: str = "#111") -> str:
    """
    Create a 1080x1920 story image from a post image (1:1). The post image is NOT cropped and is centered.

    bg_mode: "blur" (use enlarged blurred background from post) or "solid" (use solid color).
    solid_color: hex string for solid background.

    Returns public URL after uploading to storage (prefix: ig/story).
    """
    import tempfile
    import requests
    from app.services import storage_backend
    import os
    from PIL import ImageFilter

    width, height = 1080, 1920

    # Load source image (local path or URL)
    tmp_src = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    try:
        if str(image_path_or_url).startswith("http"):
            # If the URL is an R2 URL that requires presigning, try to generate a presigned GET first.
            try:
                from app.services import r2_storage

                presigned = r2_storage.generate_presigned_get_from_url(image_path_or_url, expires=60)
            except Exception:
                presigned = None
            # try presigned first, then original
            tried_urls = []
            download_url = presigned or image_path_or_url
            tried_urls.append(download_url)
            r = None
            try:
                r = requests.get(download_url, timeout=30)
                r.raise_for_status()
            except Exception:
                # try original if different
                if presigned and image_path_or_url not in tried_urls:
                    try:
                        r = requests.get(image_path_or_url, timeout=30)
                        r.raise_for_status()
                    except Exception as e:
                        raise
                else:
                    raise
            tmp_src.write(r.content)
            tmp_src.flush()
            src_path = tmp_src.name
        else:
            # assume local path
            src_path = str(Path(image_path_or_url))
        tmp_src.close()

        src = Image.open(src_path).convert("RGBA")
        src_w, src_h = src.width, src.height

        # Create background
        if bg_mode == "solid":
            # parse solid_color
            try:
                col = tuple(int(s, 16) for s in (solid_color.lstrip("#")[0:2], solid_color.lstrip("#")[2:4], solid_color.lstrip("#")[4:6]))
            except Exception:
                col = (17, 17, 17)
            bg = Image.new("RGBA", (width, height), col + (255,))
        else:
            # blur mode: create cover background from source (may crop here), then blur
            scale = max(width / src_w, height / src_h)
            new_w = max(1, int(src_w * scale))
            new_h = max(1, int(src_h * scale))
            bg_tmp = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
            left = (new_w - width) // 2
            top = (new_h - height) // 2
            bg = bg_tmp.crop((left, top, left + width, top + height)).convert("RGBA")
            # apply strong blur
            try:
                bg = bg.filter(ImageFilter.GaussianBlur(radius=25))
            except Exception:
                pass

        # Prepare final canvas and paste background
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        # If bg smaller (unlikely), center it
        canvas.paste(bg, (0, 0))

        # Prepare foreground post image: scale down/up to fit within 1080x1080 without cropping
        max_fg = 1080
        fg_scale = min(max_fg / src_w, max_fg / src_h)
        fg_w = max(1, int(src_w * fg_scale))
        fg_h = max(1, int(src_h * fg_scale))
        fg = src.resize((fg_w, fg_h), Image.Resampling.LANCZOS)

        # Paste fg centered
        paste_x = (width - fg_w) // 2
        paste_y = (height - fg_h) // 2
        canvas.paste(fg, (paste_x, paste_y), fg)

        # Save to temp and upload
        out_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        try:
            canvas.convert("RGB").save(out_tmp.name, "PNG", optimize=True)
            out_tmp.flush()
            final_path = out_tmp.name
        finally:
            out_tmp.close()

        with open(final_path, "rb") as f:
            final_bytes = f.read()
        filename = output_filename or f"{uuid4()}.png"
        public_url = storage_backend.upload_to_remote_server(final_bytes, filename, prefix="ig/story")

        try:
            os.remove(tmp_src.name)
        except Exception:
            pass
        try:
            os.remove(final_path)
        except Exception:
            pass

        return public_url
    except Exception:
        try:
            os.remove(tmp_src.name)
        except Exception:
            pass
        raise


def generate_post_image(prompt: str, caption: str | None = None, output_filename: str | None = None, style: str = "minimal_dark") -> str:
    """
    Generate a 1080x1080 post image via AI and render caption text onto it.
    Returns absolute path to saved image in media/.
    """
    from app.services import content_ai
    import tempfile
    import os

    width, height = 1080, 1080
    tmp_bg = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    try:
        # Generate prompt from given prompt/text
        try:
            image_prompt = content_ai.generate_image_prompt(prompt)
        except Exception:
            image_prompt = prompt
        bg_bytes = content_ai.generate_image_png_bytes(image_prompt)
        tmp_bg.write(bg_bytes)
        tmp_bg.flush()
        tmp_bg_path = tmp_bg.name
    finally:
        tmp_bg.close()

    try:
        # Render text onto the square canvas using existing render_image
        rel, abs_path = render_image(tmp_bg_path, caption or "", "ince düşlerim", style=style, target="square")
        try:
            os.remove(tmp_bg_path)
        except Exception:
            pass
        return abs_path
    except Exception:
        try:
            os.remove(tmp_bg_path)
        except Exception:
            pass
        raise


def generate_story_image_from_post(image_path_or_url: str, output_filename: str | None = None, bg_mode: str = "blur", solid_color: str = "#111") -> str:
    """
    Create a 1080x1920 story image from a post image (1:1). Returns absolute local path under media/.
    """
    import tempfile
    import requests
    from PIL import ImageFilter
    import os
    from pathlib import Path

    width, height = 1080, 1920
    tmp_src = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    try:
        if str(image_path_or_url).startswith("http"):
            r = requests.get(image_path_or_url, timeout=30)
            r.raise_for_status()
            tmp_src.write(r.content)
            tmp_src.flush()
            src_path = tmp_src.name
        else:
            src_path = str(Path(image_path_or_url))
        tmp_src.close()

        src = Image.open(src_path).convert("RGBA")
        src_w, src_h = src.width, src.height

        # Background
        if bg_mode == "solid":
            try:
                col = tuple(int(s, 16) for s in (solid_color.lstrip("#")[0:2], solid_color.lstrip("#")[2:4], solid_color.lstrip("#")[4:6]))
            except Exception:
                col = (17, 17, 17)
            bg = Image.new("RGBA", (width, height), col + (255,))
        else:
            scale = max(width / src_w, height / src_h)
            new_w = max(1, int(src_w * scale))
            new_h = max(1, int(src_h * scale))
            bg_tmp = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
            left = max(0, (new_w - width) // 2)
            top = max(0, (new_h - height) // 2)
            bg = bg_tmp.crop((left, top, left + width, top + height)).convert("RGBA")
            try:
                bg = bg.filter(ImageFilter.GaussianBlur(radius=25))
            except Exception:
                pass

        # Compose canvas
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        canvas.paste(bg, (0, 0))

        # Foreground: fit post into max 1080x1080 without cropping (scale down if necessary)
        max_fg = 1080
        fg_scale = min(max_fg / src_w, max_fg / src_h, 1.0)
        fg_w = max(1, int(src_w * fg_scale))
        fg_h = max(1, int(src_h * fg_scale))
        fg = src.resize((fg_w, fg_h), Image.Resampling.LANCZOS)
        paste_x = (width - fg_w) // 2
        paste_y = (height - fg_h) // 2
        canvas.paste(fg, (paste_x, paste_y), fg)

        # Save to media dir
        ensure_media_dir()
        filename = output_filename or f"{uuid4()}.png"
        abs_path = MEDIA_DIR / filename
        canvas.convert("RGB").save(abs_path, "PNG", optimize=True)
        print(f"[LOG][GENERATE_STORY] saved story local path: {abs_path}")

        try:
            os.remove(tmp_src.name)
        except Exception:
            pass
        return str(abs_path)
    except Exception:
        try:
            os.remove(tmp_src.name)
        except Exception:
            pass
        raise
