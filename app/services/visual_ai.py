"""Görsel üretimi (OpenAI Images API üzerinden)."""

from app.services.content_ai import get_client


FALLBACK_IMAGE_URL = (
    "https://images.pexels.com/photos/1032650/pexels-photo-1032650.jpeg"
)


def generate_image(prompt: str) -> str:
    """
    Verilen prompt'a göre Instagram için kare bir görsel üretir.

    OpenAI Images API kullanılır; hata olursa fallback URL döner.
    """
    try:
        client = get_client()
        resp = client.images.generate(
            model="dall-e-3",  # gpt-image-1 yok, dall-e-3 kullan
            prompt=f"Square 1:1 Instagram post image, high quality, {prompt}",
            size="1024x1024",
            n=1,
            response_format="url",  # DALL-E 3 için tek desteklenen format
        )
        # openai>=1.x response
        url = resp.data[0].url  # type: ignore[attr-defined]
        if not url:
            raise ValueError("Empty image URL from OpenAI")
        return url
    except Exception as e:  # noqa: BLE001
        # Log ve fallback
        import traceback

        print(f"Warning: OpenAI image generation failed, using fallback. Error: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return FALLBACK_IMAGE_URL
