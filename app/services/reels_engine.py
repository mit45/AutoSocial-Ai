from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import wave
import math
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from app.services.content_ai import generate_hashtags
from app.services.feedback_loop_engine import load_learning_state
from app.services.instagram import INSTAGRAM_API, ACCESS_TOKEN
from app.services.instagram_reels import publish_reel_container_workflow
from app.services.storage_backend import upload_to_remote_server, generate_presigned_get_from_url


def _log(tag: str, msg: str) -> None:
    try:
        print(f"[{tag}] {msg}")
    except Exception:
        pass


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x or default)
    except Exception:
        return default


def _choose_reel_profile(learning_state: dict[str, Any] | None) -> dict[str, Any]:
    """
    Very lightweight feedback integration:
    - if reels weight is high, keep scenes shorter & punchier.
    - if caption style 'short' is high, keep overlay text shorter.
    """
    ls = learning_state or {}
    cw = ls.get("content_weights") or {}
    caption_style = ls.get("caption_style") or {}
    reel_w = float(cw.get("reel", 0.0) or 0.0)
    short_w = float(caption_style.get("short", 0.0) or 0.0)

    # Deterministic profile choices
    return {
        "aggressive": reel_w >= 0.45,
        "short_text": short_w >= 0.55,
        "reel_weight": reel_w,
    }


def _default_reel_structure(topic: str, caption: str, *, aggressive: bool, short_text: bool) -> dict[str, Any]:
    """
    Fallback structure without LLM dependency.

    Rules enforced:
    - first 3 seconds attention-grabbing (scene0 duration=3)
    - total duration between 7-15 seconds
    - loop optimization: last scene text == first scene text (connects)
    """
    def _strip_hashtags(text: str) -> str:
        # Reels isteği: caption ve overlay metninde hashtag olmasın.
        return re.sub(r"(?:^|\s)#\w+", "", text).strip()

    def _split_phrases(text: str) -> list[str]:
        # Split by sentence punctuation; fallback to newline.
        parts = re.split(r"(?<=[.!?])\s+|\n+", text)
        out: list[str] = []
        for p in parts:
            s = p.strip()
            if s:
                out.append(s)
        return out

    def _trim_words(s: str, max_words: int) -> str:
        words = (s or "").split()
        if len(words) <= max_words:
            return (s or "").strip()
        return " ".join(words[:max_words]).strip()

    def _safe_overlay_text(s: str, *, short: bool) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        # Keep semantics: do not over-trim; just avoid very long overlays.
        max_words = 10 if short else 18
        s = _trim_words(s, max_words=max_words)
        # Avoid too-long strings due to emojis/URLs.
        s = re.sub(r"https?://\S+", "", s).strip()
        return s

    caption_clean = _strip_hashtags(str(caption or ""))
    phrases = _split_phrases(caption_clean)

    def _chunks_from_caption(text: str, count: int = 3, words_per_chunk: int = 12) -> list[str]:
        # Açıklamaya bağlı kal: caption kelimelerini sırayla chunk'lara böl.
        ws = [w for w in (text or "").split() if w]
        if not ws:
            return []
        chunks: list[str] = []
        idx = 0
        while idx < len(ws) and len(chunks) < count:
            piece = " ".join(ws[idx : idx + words_per_chunk]).strip()
            if piece:
                chunks.append(piece)
            idx += words_per_chunk
        return chunks

    # Öncelik: cümle tabanlı, yetmezse caption chunk. Virgül bazlı alt parçalar da alınır.
    bases = []
    for p in phrases:
        pp = p.strip()
        if not pp:
            continue
        comma_parts = [x.strip() for x in re.split(r"\s*,\s*", pp) if x.strip()]
        if len(comma_parts) > 1:
            bases.extend(comma_parts)
        else:
            bases.append(pp)
    if len(bases) < 3:
        bases = _chunks_from_caption(caption_clean, count=3, words_per_chunk=(10 if short_text else 12))

    if len(bases) < 3:
        # Son fallback yine topic'le alakalı ama açıklama yoksa devreye girer.
        t = (topic or "").strip() or "AI"
        bases = [
            f"{t} hakkında kısa bir bakış",
            "Ana fikri sade şekilde düşün",
            "Hemen bir adım dene",
        ]

    full_overlay_text = caption_clean.strip()
    hook = _safe_overlay_text(bases[0], short=short_text) or "Hemen başla"
    value1 = _safe_overlay_text(bases[1], short=short_text) or "Ana fikir"
    value2 = _safe_overlay_text(bases[2], short=short_text) or "Şimdi uygula"

    # User requirement: keep full caption text visible and repeated while
    # backgrounds keep changing across scenes.
    if full_overlay_text:
        hook = full_overlay_text
        value1 = full_overlay_text
        value2 = full_overlay_text
    cta = "Kaydet ve dene!"

    # Ensure total duration between 7-15s.
    if aggressive:
        scenes = [
            {"text": hook, "duration": 3},
            {"text": value1, "duration": 4},
            {"text": value2, "duration": 3},
            {"text": hook, "duration": 3},
        ]  # total 13s
    else:
        scenes = [
            {"text": hook, "duration": 3},
            {"text": value1, "duration": 3},
            {"text": value2, "duration": 4},
            {"text": hook, "duration": 3},
        ]  # total 13s

    script = "\n".join([f"[{s['duration']}s] {s['text']}" for s in scenes])

    video_prompt = (
        "Vertical 9:16 reel background, bold minimal typography, high contrast, "
        "motion-safe animations feel, no logos, no watermarks."
    )

    return {
        "hook": hook,
        "script": script,
        "scenes": scenes,
        "cta": cta,
        "caption": caption_clean or "",
        "video_prompt": video_prompt,
    }


def generate_reel_structure(
    *,
    topic: str,
    content_type: str,
    caption: str,
    learning_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create structured reel plan (hook/script/scenes/cta/caption/video_prompt).

    Note: This project currently relies on OpenAI for captions/images; however for
    production reliability we keep a deterministic fallback that always works.
    """
    profile = _choose_reel_profile(learning_state)
    # Keep content_type unused in fallback; can be leveraged by LLM in the future.
    _ = content_type
    return _default_reel_structure(topic, caption, aggressive=bool(profile["aggressive"]), short_text=bool(profile["short_text"]))


def _ffmpeg_available() -> bool:
    # Allow override for environments where PATH isn't set correctly.
    ffmpeg_env = os.getenv("FFMPEG_PATH")
    if ffmpeg_env and Path(ffmpeg_env).exists():
        return True
    return shutil.which("ffmpeg") is not None


def _ffmpeg_bin() -> str:
    """
    Resolve ffmpeg executable path for subprocess usage.
    """
    ffmpeg_env = os.getenv("FFMPEG_PATH")
    if ffmpeg_env:
        return ffmpeg_env
    found = shutil.which("ffmpeg")
    return found or "ffmpeg"


def _ffprobe_available() -> bool:
    ffprobe_env = os.getenv("FFPROBE_PATH")
    if ffprobe_env and Path(ffprobe_env).exists():
        return True
    return shutil.which("ffprobe") is not None


def _ffprobe_video_metadata(mp4_path: Path) -> dict[str, Any]:
    """
    Returns parsed ffprobe json:
    - codec_name
    - width/height
    - duration_s
    """
    if not _ffprobe_available():
        raise RuntimeError("ffprobe not found. Install ffprobe or ensure it's in PATH (or set FFPROBE_PATH).")

    ffprobe_bin = os.getenv("FFPROBE_PATH") or shutil.which("ffprobe") or "ffprobe"
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(mp4_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed code={proc.returncode} stderr={proc.stderr[:1200]}")

    try:
        info = json.loads(proc.stdout)
    except Exception as e:
        raise RuntimeError(f"ffprobe json parse failed: {e}")

    streams = info.get("streams") or []
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    v0 = video_streams[0] if video_streams else {}

    codec_name = v0.get("codec_name")
    width = v0.get("width")
    height = v0.get("height")

    duration_s = None
    fmt = info.get("format") or {}
    dur_raw = fmt.get("duration")
    if dur_raw is not None:
        try:
            duration_s = float(dur_raw)
        except Exception:
            duration_s = None

    return {
        "codec_name": codec_name,
        "width": width,
        "height": height,
        "duration_s": duration_s,
        "raw": info,
    }


def _optimize_reel_mp4_bytes(
    mp4_bytes: bytes,
    *,
    target_w: int = 1080,
    target_h: int = 1920,
    out_fps: int = 30,
    crf: int = 23,
) -> bytes:
    """
    Force Instagram-friendly encoding (H.264 + yuv420p + faststart).
    """
    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg not found. Install ffmpeg and ensure it's in PATH, or set FFMPEG_PATH env var.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="reels_opt_"))
    in_path = tmp_dir / "in.mp4"
    out_path = tmp_dir / "out.mp4"
    in_path.write_bytes(mp4_bytes)
    ffmpeg_bin = _ffmpeg_bin()

    # Scale + pad for exact portrait resolution.
    vf = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2"
    )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(in_path),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(crf),
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        vf,
        "-r",
        str(out_fps),
        "-movflags",
        "+faststart",
        str(out_path),
    ]

    _log("reels", f"ffmpeg optimize cmd={' '.join(cmd[:6])} ...")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        if proc.returncode != 0:
            _log("reels", f"ffmpeg optimize stderr={proc.stderr[:1200]}")
            raise RuntimeError(f"ffmpeg optimize failed code={proc.returncode}")
        return out_path.read_bytes()
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def validate_and_optimize_reel_video_mp4_bytes(
    mp4_bytes: bytes,
    *,
    require_codec_h264: bool = True,
    expected_w: int = 1080,
    expected_h: int = 1920,
    max_duration_s: float = 90.0,
    optimize: bool = True,
    expected_duration_s: float | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """
    Publish öncesi video doğrulama:
    - mp4
    - codec h264
    - 1080x1920
    - duration < 90s
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="reels_val_"))
    try:
        in_path = tmp_dir / "reel_in.mp4"
        in_path.write_bytes(mp4_bytes)

        if optimize:
            mp4_bytes = _optimize_reel_mp4_bytes(mp4_bytes, target_w=expected_w, target_h=expected_h)
            in_path.write_bytes(mp4_bytes)

        ok = True
        reasons: list[str] = []

        try:
            meta = _ffprobe_video_metadata(in_path)
            codec = meta.get("codec_name")
            width = meta.get("width")
            height = meta.get("height")
            duration_s = meta.get("duration_s")

            if require_codec_h264 and isinstance(codec, str) and codec.lower() not in ("h264", "avc1"):
                ok = False
                reasons.append(f"codec_name={codec} (expected h264)")
            if require_codec_h264 and codec is None:
                ok = False
                reasons.append("codec_name missing")

            if width != expected_w or height != expected_h:
                ok = False
                reasons.append(f"resolution={width}x{height} (expected {expected_w}x{expected_h})")

            # Duration check: ffprobe preferred, otherwise fall back to expected_duration_s.
            if duration_s is None:
                if expected_duration_s is None:
                    ok = False
                    reasons.append("duration missing (ffprobe) and expected_duration_s not provided")
                else:
                    duration_s = expected_duration_s
                    reasons.append("duration missing (ffprobe); used expected_duration_s")

            if duration_s is not None and (float(duration_s) <= 0 or float(duration_s) >= max_duration_s):
                ok = False
                reasons.append(f"duration_s={duration_s} (expected 0 < duration < {max_duration_s})")

            return (mp4_bytes, {"ok": ok, "meta": meta, "reasons": reasons})
        except Exception as e:
            # If ffprobe isn't available, we still ensured H.264 + portrait encoding via ffmpeg optimize.
            # Duration can be validated only if caller provides expected_duration_s.
            _log("reels", f"ffprobe/validation fallback: {e}")
            if expected_duration_s is not None:
                if float(expected_duration_s) <= 0 or float(expected_duration_s) >= max_duration_s:
                    ok = False
                    reasons.append(f"duration_s={expected_duration_s} (expected 0 < duration < {max_duration_s})")
            else:
                reasons.append("ffprobe missing; skipped duration check (expected_duration_s not provided)")

            return (
                mp4_bytes,
                {
                    "ok": ok,
                    "meta": {"codec_name": "h264_assumed_by_optimise", "width": expected_w, "height": expected_h, "duration_s": expected_duration_s},
                    "reasons": reasons,
                    "ffprobe_error": str(e),
                },
            )
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _generate_soundtrack_wav(
    wav_path: Path,
    *,
    duration_s: float,
    sample_rate: int = 44100,
    mode: str = "upbeat",
) -> None:
    """
    Generate a lightweight melodic soundtrack (no external dependency).
    """
    duration_s = max(1.0, float(duration_s))
    total_samples = int(sample_rate * duration_s)
    mode = (mode or "upbeat").strip().lower()
    if mode not in {"upbeat", "chill", "cinematic", "tech"}:
        mode = "upbeat"

    if mode == "chill":
        bpm = 84.0
        chords = [
            (174.61, 220.00, 261.63),  # F
            (164.81, 207.65, 246.94),  # E
            (146.83, 196.00, 246.94),  # Dm
            (130.81, 164.81, 196.00),  # C
        ]
        melody = [261.63, 293.66, 329.63, 293.66, 261.63, 246.94, 220.00, 196.00]
        bed_gain, mel_gain, kick_gain, hat_gain = (0.20, 0.20, 0.10, 0.015)
    elif mode == "cinematic":
        bpm = 92.0
        chords = [
            (110.00, 164.81, 220.00),  # A2-E3-A3
            (98.00, 146.83, 196.00),   # G2-D3-G3
            (87.31, 130.81, 174.61),   # F2-C3-F3
            (98.00, 146.83, 185.00),   # Gsus-ish
        ]
        melody = [220.00, 246.94, 261.63, 293.66, 261.63, 246.94, 220.00, 196.00]
        bed_gain, mel_gain, kick_gain, hat_gain = (0.28, 0.18, 0.14, 0.010)
    elif mode == "tech":
        bpm = 118.0
        chords = [
            (220.00, 277.18, 329.63),  # A C# E
            (246.94, 311.13, 369.99),  # B D# F#
            (196.00, 246.94, 293.66),  # G B D
            (174.61, 220.00, 261.63),  # F A C
        ]
        melody = [329.63, 369.99, 392.00, 440.00, 392.00, 369.99, 329.63, 293.66]
        bed_gain, mel_gain, kick_gain, hat_gain = (0.23, 0.24, 0.16, 0.020)
    else:  # upbeat
        bpm = 104.0
        chords = [
            (220.00, 261.63, 329.63),  # A3 C4 E4
            (174.61, 220.00, 261.63),  # F3 A3 C4
            (130.81, 164.81, 196.00),  # C3 E3 G3
            (196.00, 246.94, 293.66),  # G3 B3 D4
        ]
        melody = [329.63, 392.00, 440.00, 392.00, 349.23, 329.63, 293.66, 261.63]
        bed_gain, mel_gain, kick_gain, hat_gain = (0.24, 0.30, 0.18, 0.025)

    beat_s = 60.0 / bpm
    chord_len_s = 2.0
    melody_step_s = beat_s

    def env_adsr(t: float, note_len: float) -> float:
        a = min(1.0, t / 0.02)
        d = 1.0 - 0.25 * min(1.0, max(0.0, (t - 0.02) / 0.08))
        r_phase = max(0.0, t - (note_len - 0.08))
        r = 1.0 - min(1.0, r_phase / 0.08)
        return max(0.0, a * d * r)

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(2)  # stereo
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)

        frames = bytearray()
        for i in range(total_samples):
            t = i / sample_rate

            # Chord bed
            chord_idx = int(t / chord_len_s) % len(chords)
            c1, c2, c3 = chords[chord_idx]
            bed = (
                bed_gain * math.sin(2.0 * math.pi * c1 * t)
                + (bed_gain * 0.83) * math.sin(2.0 * math.pi * c2 * t)
                + (bed_gain * 0.75) * math.sin(2.0 * math.pi * c3 * t)
            )

            # Melody
            mel_idx = int(t / melody_step_s) % len(melody)
            mel_f = melody[mel_idx]
            mel_t = t % melody_step_s
            mel_env = env_adsr(mel_t, melody_step_s)
            mel = mel_gain * mel_env * math.sin(2.0 * math.pi * mel_f * t)

            # Kick-like pulse each beat
            beat_phase = t % beat_s
            kick_env = max(0.0, 1.0 - (beat_phase / 0.12))
            kick = kick_gain * kick_env * math.sin(2.0 * math.pi * (62.0 - 25.0 * beat_phase) * t)

            # Gentle high-hat noise-like component
            hat_env = max(0.0, 1.0 - ((t % (beat_s / 2.0)) / 0.05))
            hat = hat_gain * hat_env * math.sin(2.0 * math.pi * 6000.0 * t)

            # Master with fade in/out
            fade_in = min(1.0, t / 0.6)
            fade_out = min(1.0, (duration_s - t) / 0.9)
            master = max(0.0, min(1.0, fade_in * fade_out))
            s = (bed + mel + kick + hat) * 0.42 * master

            # Soft clip
            s = max(-1.0, min(1.0, s))
            # Stereo tiny widening
            left = s
            right = s * 0.96
            frames += struct.pack("<hh", int(left * 32767), int(right * 32767))

        wf.writeframes(frames)


def _add_background_audio_to_reel_mp4_bytes(
    mp4_bytes: bytes,
    *,
    duration_s: float | None = None,
    soundtrack_mode: str = "upbeat",
) -> bytes:
    """
    Add a lightweight generated background audio track so reels are not silent.
    Uses ffmpeg lavfi synth (no external dependency/file required).
    """
    if not _ffmpeg_available():
        return mp4_bytes

    tmp_dir = Path(tempfile.mkdtemp(prefix="reels_audio_"))
    try:
        in_path = tmp_dir / "in.mp4"
        out_path = tmp_dir / "out.mp4"
        in_path.write_bytes(mp4_bytes)

        if duration_s is None:
            try:
                md = _ffprobe_video_metadata(in_path)
                ds = md.get("duration_s")
                duration_s = float(ds) if ds is not None else 13.0
            except Exception:
                duration_s = 13.0

        duration_s = max(1.0, float(duration_s))
        fade_out_start = max(0.0, duration_s - 1.2)

        audio_path = tmp_dir / "soundtrack.wav"
        _generate_soundtrack_wav(
            audio_path,
            duration_s=duration_s,
            sample_rate=44100,
            mode=soundtrack_mode,
        )
        afilter = f"volume=0.78,afade=t=in:st=0:d=0.7,afade=t=out:st={fade_out_start:.3f}:d=1.0"

        ffmpeg_bin = _ffmpeg_bin()
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(in_path),
            "-i",
            str(audio_path),
            "-filter:a",
            afilter,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        _log("reels", f"ffmpeg audio add cmd={' '.join(cmd[:8])} ...")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            _log("reels", f"ffmpeg audio add failed: {proc.stderr[:1200]}")
            return mp4_bytes
        return out_path.read_bytes()
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _pil_load_from_bytes(png_bytes: bytes):
    from PIL import Image

    from io import BytesIO

    return Image.open(BytesIO(png_bytes)).convert("RGB")


def _pil_make_scene_frame(
    *,
    base_image,
    text: str,
    size: tuple[int, int] = (1080, 1920),
) -> Any:
    """
    Build a single frame with text overlay.
    (We still rely on ffmpeg to assemble final mp4; this is frame generation.)
    """
    from PIL import ImageDraw, ImageFont

    img = base_image.resize(size)
    draw = ImageDraw.Draw(img)

    # Font: best-effort system font, fallback to default.
    font_candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\seguisym.ttf",
        r"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        r"/Library/Fonts/Arial.ttf",
    ]
    font = None
    for fp in font_candidates:
        try:
            if os.path.exists(fp):
                font = ImageFont.truetype(fp, size=78)
                break
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()

    # Simple wrap: fit into safe width.
    words = (text or "").split()
    lines: list[str] = []
    # Allow more lines so long caption text doesn't get truncated.
    max_lines = 12
    while words and len(lines) < max_lines:
        line = ""
        # Greedy add until width would overflow
        for w in list(words):
            trial = (line + " " + w).strip()
            bbox = draw.textbbox((0, 0), trial, font=font)
            if bbox and (bbox[2] - bbox[0]) <= int(size[0] * 0.92):
                line = trial
                words.pop(0)
            else:
                break
        lines.append(line)
    if words and len(lines) < max_lines:
        lines.append(" ".join(words[:12]))

    # Draw text near lower third without background box.
    # Readability is improved with stroke + subtle shadow.
    overlay_h = int(size[1] * 0.40)
    y0 = int(size[1] * 0.52)

    total_text_h = 0
    line_bboxes: list[tuple[int, int]] = []
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=font)
        h = (bbox[3] - bbox[1]) if bbox else 0
        line_bboxes.append((h, 0))
        total_text_h += h

    cur_y = y0 + int((overlay_h - total_text_h) / max(1, len(lines)))
    for ln in lines:
        if not ln:
            continue
        bbox = draw.textbbox((0, 0), ln, font=font)
        w = (bbox[2] - bbox[0]) if bbox else 0
        x = int((size[0] - w) / 2)
        # Shadow
        draw.text((x + 2, cur_y + 2), ln, font=font, fill=(0, 0, 0))
        # Main text with stroke for contrast
        draw.text(
            (x, cur_y),
            ln,
            font=font,
            fill=(255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )
        # advance y using bbox height
        h = (bbox[3] - bbox[1]) if bbox else 0
        cur_y += h + int(size[1] * 0.01)

    return img


def _wrap_lines_for_draw(draw, text: str, font, max_width: int) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    if not words:
        return lines
    while words:
        line = ""
        while words:
            trial = (line + " " + words[0]).strip()
            bbox = draw.textbbox((0, 0), trial, font=font)
            w = (bbox[2] - bbox[0]) if bbox else 0
            if w <= max_width:
                line = trial
                words.pop(0)
            else:
                break
        if not line:
            # hard fallback for very long single token
            line = words.pop(0)
        lines.append(line)
    return lines


def _pil_make_scene_frame_scrolling_text(
    *,
    base_image,
    text: str,
    progress: float,
    size: tuple[int, int] = (1080, 1920),
) -> Any:
    """
    Film yazısı gibi yukarı kayan metin:
    - progress: 0.0 -> metin alttan başlar
    - progress: 1.0 -> metin üste yaklaşır
    """
    from PIL import ImageDraw, ImageFont

    img = base_image.resize(size)
    draw = ImageDraw.Draw(img)

    font_candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        r"/Library/Fonts/Arial.ttf",
    ]
    font = None
    for fp in font_candidates:
        try:
            if os.path.exists(fp):
                font = ImageFont.truetype(fp, size=62)
                break
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()

    safe_x = int(size[0] * 0.08)
    text_area_w = int(size[0] * 0.84)
    lines = _wrap_lines_for_draw(draw, text, font, text_area_w)
    if not lines:
        return img

    # Line heights
    line_hs: list[int] = []
    total_h = 0
    for ln in lines:
        bb = draw.textbbox((0, 0), ln, font=font)
        h = (bb[3] - bb[1]) if bb else 0
        h = max(h, 22)
        line_hs.append(h)
        total_h += h + int(size[1] * 0.008)

    # Scroll from below to above lower third
    start_y = int(size[1] * 0.92)
    end_y = int(size[1] * 0.16) - total_h
    p = max(0.0, min(1.0, float(progress)))
    y = int(start_y + (end_y - start_y) * p)

    for i, ln in enumerate(lines):
        bb = draw.textbbox((0, 0), ln, font=font)
        w = (bb[2] - bb[0]) if bb else 0
        x = int((size[0] - w) / 2)
        # shadow + stroke
        draw.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0))
        draw.text((x, y), ln, font=font, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        y += line_hs[i] + int(size[1] * 0.008)

    return img


def _pil_make_scene_frame_reveal(
    *,
    base_image,
    full_text: str,
    reveal_words: int,
    y_shift: int = 0,
    size: tuple[int, int] = (1080, 1920),
) -> Any:
    """
    Simple text animation frame:
    - reveal first N words (typewriter-like by words)
    - slight upward y_shift across subframes
    """
    words = (full_text or "").split()
    if not words:
        return _pil_make_scene_frame(base_image=base_image, text="", size=size)
    n = max(1, min(len(words), int(reveal_words)))
    text = " ".join(words[:n])
    # Keep frame fully filled to avoid black flashes between subframes.
    # (Previous canvas-shift approach introduced black bars on some frames.)
    _ = y_shift
    return _pil_make_scene_frame(base_image=base_image, text=text, size=size)


def render_reel_video_mp4_bytes(
    *,
    reel_structure: dict[str, Any],
    background_png_bytes: bytes,
    background_png_bytes_list: list[bytes] | None = None,
    out_fps: int = 30,
) -> bytes:
    """
    Render mp4 by:
    - generating one PNG frame per scene (PIL overlay)
    - assembling frames into mp4 with ffmpeg concat filter
    """
    if not _ffmpeg_available():
        raise RuntimeError(
            "ffmpeg not found. Install ffmpeg and ensure it's in PATH, or set FFMPEG_PATH env var."
        )

    from PIL import Image  # noqa: F401  (ensures Pillow is present)

    scenes = reel_structure.get("scenes") or []
    if not scenes:
        raise ValueError("reel_structure.scenes is empty")

    base_list: list[Any] = []
    if background_png_bytes_list:
        for b in background_png_bytes_list:
            if b:
                try:
                    base_list.append(_pil_load_from_bytes(b))
                except Exception:
                    pass
    if not base_list:
        base_list = [_pil_load_from_bytes(background_png_bytes)]

    tmp_dir = Path(tempfile.mkdtemp(prefix="reels_"))
    try:
        frame_paths: list[Path] = []
        durations: list[float] = []

        size = (1080, 1920)
        # Build smooth global scroll across the full reel (no per-scene reset).
        total_steps = 0
        scene_steps: list[int] = []
        for sc in scenes:
            dur = float(sc.get("duration") or 0)
            if dur <= 0:
                dur = 3.0
            steps = max(12, int(round(dur * max(24, out_fps))))  # smoother than previous ~8fps
            scene_steps.append(steps)
            total_steps += steps

        global_step = 0
        for idx, sc in enumerate(scenes):
            text = str(sc.get("text") or "")
            dur = float(sc.get("duration") or 0)
            if dur <= 0:
                dur = 3.0

            base = base_list[idx % len(base_list)]
            # Film-yazisi gibi kayma: scene içinde sub-frame.
            # Progress is GLOBAL so text scroll is continuous across scenes.
            step_count = scene_steps[idx]
            sub_dur = max(1.0 / float(max(24, out_fps)), dur / float(step_count))
            for k in range(step_count):
                if total_steps > 1:
                    progress = global_step / float(total_steps - 1)
                else:
                    progress = 1.0
                frame = _pil_make_scene_frame_scrolling_text(
                    base_image=base,
                    text=text,
                    progress=progress,
                    size=size,
                )
                fp = tmp_dir / f"scene_{idx}_{k}.png"
                frame.save(fp, format="PNG")
                frame_paths.append(fp)
                durations.append(sub_dur)
                global_step += 1

        # IMPORTANT (Windows): avoid command-length overflow (WinError 206)
        # by writing an ffmpeg concat-demuxer list file instead of hundreds of "-i" args.
        concat_list_path = tmp_dir / "concat_list.txt"
        try:
            with open(concat_list_path, "w", encoding="utf-8") as cf:
                for fp, dur in zip(frame_paths, durations, strict=False):
                    safe_fp = str(fp).replace("\\", "/").replace("'", "'\\''")
                    cf.write(f"file '{safe_fp}'\n")
                    cf.write(f"duration {float(dur):.6f}\n")
                if frame_paths:
                    # concat demuxer expects last file repeated for final duration
                    safe_last = str(frame_paths[-1]).replace("\\", "/").replace("'", "'\\''")
                    cf.write(f"file '{safe_last}'\n")
        except Exception as e:
            raise RuntimeError(f"failed to prepare concat list: {e}")

        n = len(frame_paths)
        filter_complex = "format=yuv420p[v]"

        out_path = tmp_dir / f"reel_{uuid.uuid4().hex}.mp4"
        ffmpeg_bin = _ffmpeg_bin()
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-r",
            str(out_fps),
            "-shortest",
            str(out_path),
        ]
        _log(
            "reels",
            f"ffmpeg render bin={ffmpeg_bin} cmd={' '.join(cmd[:6])} ... frames={n} total_s={sum(durations):.1f}",
        )

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            _log("reels", f"ffmpeg error: {proc.stderr[:1200]}")
            raise RuntimeError(f"ffmpeg render failed code={proc.returncode}")

        return out_path.read_bytes()
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def publish_reel_graph(
    *,
    video_url: str,
    caption: str,
    ig_user_id: str,
    access_token: str | None = None,
) -> dict[str, Any]:
    """
    Two-step container + media_publish flow.
    """
    # Compatibility wrapper. The actual Graph API steps are implemented in instagram_reels.py
    # with container status polling + retries.
    cap = str(caption or "").strip()
    if not video_url:
        return {"error": {"message": "video_url is required", "code": "invalid_video_url"}}

    return publish_reel_container_workflow(
        video_url=video_url,
        caption=cap,
        ig_user_id=ig_user_id,
        access_token=access_token,
        container_timeout_s=90.0,
    )


def generate_and_publish_reel(
    *,
    topic: str,
    content_type: str,
    caption: str,
    background_png_bytes: bytes,
    background_png_bytes_list: list[bytes] | None = None,
    ig_user_id: str,
    access_token: str | None = None,
    hashtags: list[str] | None = None,
    learning_state: dict[str, Any] | None = None,
    reel_structure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Orchestrates:
      - generate reel structure
      - render mp4 bytes
      - upload video
      - publish via Graph API

    Output:
      { "video_url": "...", "caption": "...", "type": "reel" }
    """
    ls = learning_state if learning_state is not None else load_learning_state()
    # "Trend-like" telifsiz soundtrack style selection by topic/caption keywords.
    topic_caption = f"{topic or ''} {caption or ''}".lower()
    soundtrack_mode = "upbeat"
    if any(k in topic_caption for k in ["uzay", "evren", "yıldız", "galaksi", "sinema", "hikaye"]):
        soundtrack_mode = "cinematic"
    elif any(k in topic_caption for k in ["teknoloji", "yapay", "kod", "robot", "app", "uygulama"]):
        soundtrack_mode = "tech"
    elif any(k in topic_caption for k in ["meditasyon", "sakin", "minimal", "psikoloji", "farkındalık"]):
        soundtrack_mode = "chill"
    if reel_structure is None:
        reel_structure = generate_reel_structure(
            topic=topic,
            content_type=content_type,
            caption=caption,
            learning_state=ls,
        )

    # Render mp4 bytes
    mp4_bytes = render_reel_video_mp4_bytes(
        reel_structure=reel_structure,
        background_png_bytes=background_png_bytes,
        background_png_bytes_list=background_png_bytes_list,
        out_fps=30,
    )

    # Expected duration from reel_structure (deterministic: sum scene durations).
    expected_duration_s = 0.0
    try:
        for sc in (reel_structure.get("scenes") or []):
            dur = float(sc.get("duration") or 0)
            expected_duration_s += dur if dur > 0 else 3.0
    except Exception:
        expected_duration_s = None  # type: ignore[assignment]

    # Validate + optimize before upload (H.264 + portrait resolution + duration limit).
    try:
        mp4_bytes, vinfo = validate_and_optimize_reel_video_mp4_bytes(
            mp4_bytes,
            optimize=True,
            expected_duration_s=expected_duration_s,
        )
        _log("reels", f"video_validation ok={vinfo.get('ok')} reasons={vinfo.get('reasons')}")
        if not vinfo.get("ok"):
            return {
                "error": {
                    "step": "video_validation",
                    "message": "reel video validation failed",
                    "reasons": vinfo.get("reasons"),
                }
            }
    except Exception as e:
        _log("reels", f"video_validation exception: {e}")
        return {"error": {"step": "video_validation", "message": str(e)}}

    # Add background audio track (reels should not be silent).
    try:
        duration_for_audio = None
        meta_obj = vinfo.get("meta") if isinstance(vinfo, dict) else None
        if isinstance(meta_obj, dict):
            d_audio = meta_obj.get("duration_s")
            if d_audio is not None:
                duration_for_audio = float(d_audio)
        mp4_bytes = _add_background_audio_to_reel_mp4_bytes(
            mp4_bytes,
            duration_s=duration_for_audio,
            soundtrack_mode=soundtrack_mode,
        )
    except Exception as e:
        _log("reels", f"audio_add exception: {e}")

    # Upload mp4
    filename = f"reel_{uuid.uuid4().hex}.mp4"
    video_url = upload_to_remote_server(mp4_bytes, filename, prefix="ig/reels")
    _log("reels", f"uploaded video filename={filename} url={video_url}")

    publish_caption = str((reel_structure.get("caption") if isinstance(reel_structure, dict) else caption) or caption or "").strip()
    # Caption sonunda hashtag ekle (kullanıcı talebi).
    tag_line = ""
    if hashtags:
        clean_tags: list[str] = []
        for h in hashtags:
            s = str(h or "").strip()
            if not s:
                continue
            if not s.startswith("#"):
                s = "#" + s.lstrip("#")
            clean_tags.append(s)
        if clean_tags:
            tag_line = " ".join(clean_tags[:12])
    if tag_line:
        publish_caption = f"{publish_caption}\n\n{tag_line}".strip()

    # Publish
    pub = publish_reel_graph(
        video_url=video_url,
        caption=publish_caption,
        ig_user_id=ig_user_id,
        access_token=access_token,
    )

    if isinstance(pub, dict) and pub.get("error"):
        return {
            "error": pub.get("error"),
            "video_url": video_url,
            "caption": caption,
            "type": "reel",
            "reel_structure": reel_structure,
        }

    publish_id = None
    if isinstance(pub, dict):
        publish_id = pub.get("publish_id")
        if not publish_id and isinstance(pub.get("publish_response"), dict):
            publish_id = (pub.get("publish_response") or {}).get("id")

    return {
        "video_url": video_url,
        "caption": caption,
        "type": "reel",
        "publish_response": pub,
        "publish_id": str(publish_id) if publish_id else None,
        "reel_structure": reel_structure,
    }

