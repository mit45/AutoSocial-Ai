"""Unified image API: generation (bytes) and rendering from bytes/path.

Provides:
- generate_image_bytes(prompt) -> bytes
- render_from_bytes(background_bytes, text, signature, style='minimal_dark', target='square') -> (rel_path, abs_path)
- generate_image_url(prompt) -> str  (delegates to visual_ai.generate_image)
"""
from __future__ import annotations
import tempfile
from typing import Tuple

from app.services import content_ai, visual_ai, image_render


def generate_image_bytes(prompt: str) -> bytes:
    """Generate an image and return PNG bytes."""
    return content_ai.generate_image_png_bytes(prompt)


def generate_image_url(prompt: str) -> str:
    """Generate an image and return a URL (fallbacks handled by visual_ai)."""
    return visual_ai.generate_image(prompt)


def render_from_bytes(background_bytes: bytes, text: str, signature: str, style: str = "minimal_dark", target: str = "square") -> Tuple[str, str]:
    """Save background_bytes to a temporary file, call image_render.render_image and return its result."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    try:
        tmp.write(background_bytes)
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()
    try:
        return image_render.render_image(str(tmp_path), text, signature, style, target)
    finally:
        try:
            import os

            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

