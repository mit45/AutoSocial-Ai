import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Post, Account
from app.schemas import (
    AccountCreate,
    AccountRead,
    GenerateAndPublishRequest,
    PostRead,
    PublishRequest,
    PublishResponse,
    GenerateRequest,
    GenerateResponse,
    PostDetailResponse,
    RenderImageRequest,
    RenderImageResponse,
)
from app.models import PostStatus, PostType
from app.services.trend_radar import get_trending_topics
from app.services.content_ai import (
    generate_caption,
    generate_hashtags,
    format_post_text,
    generate_image_prompt,
    generate_image_png_bytes,
)
from app.services.storage_service import (
    save_png_bytes_to_generated,
    upload_to_remote_server,
)
from app.services.storage_service import delete_remote_file
from app.services.image_render import render_image
from app.config import BASE_URL
from app.services.visual_ai import generate_image
from app.services.monetization import attach_affiliate
from app.services.instagram import publish_image
from app.services.scheduler import next_post_time
from app.services.scheduled_publisher import run_scheduled_publish
import json

BASE_DIR = Path(__file__).resolve().parent.parent.parent

router = APIRouter()


@router.post("/accounts", response_model=AccountRead)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    """
    Yeni bir Instagram account kaydi olustur.
    """
    account = Account(
        ig_user_id=payload.ig_user_id,
        access_token=payload.access_token,
        niche=payload.niche,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/accounts", response_model=list[AccountRead])
def list_accounts(db: Session = Depends(get_db)):
    """
    Tum account'lari listele.
    """
    return db.query(Account).all()


@router.get("/generate-post")
def generate_post():
    """
    Basit Post Üretme Testi - Sadece AI çıktısını test eder.

    Bu endpoint:
    - OpenAI ile caption üretir
    - Hashtag üretir
    - Post metnini formatlar
    - Instagram'a dokunmaz, sadece AI çıktısını döner

    Returns:
        dict: {
            "topic": str,
            "raw_caption": str,  # OpenAI'den gelen ham caption
            "hashtags": list[str],  # Üretilen hashtag'ler
            "formatted_post": str,  # Formatlanmış post metni (caption + hashtag'ler)
            "image_url": str,  # Görsel URL'si
            "schedule": datetime  # Önerilen yayın zamanı
        }
    """
    # 1) Konu seç
    topic = get_trending_topics()[0]

    # 2) OpenAI ile caption üret
    try:
        raw_caption = generate_caption(topic)
    except Exception as e:
        raw_caption = f"Test post about {topic}. #AI #Automation"
        print(f"Warning: Caption generation failed: {e}")

    # 3) Affiliate link ekle (opsiyonel)
    caption_with_affiliate = attach_affiliate(raw_caption)

    # 4) Hashtag üret
    try:
        hashtags = generate_hashtags(topic, caption=raw_caption, count=10)
    except Exception as e:
        hashtags = ["#AI", "#Technology", "#Innovation", "#Motivation", "#Success"]
        print(f"Warning: Hashtag generation failed: {e}")

    # 5) Post metnini formatla
    formatted_post = format_post_text(caption_with_affiliate, hashtags)

    # 6) Görsel URL'si (OpenAI ile üretilmeye çalışılır, fallback varsa kullanılır)
    image_url = generate_image(topic)

    # 7) Önerilen yayın zamanı
    schedule = next_post_time()

    return {
        "topic": topic,
        "raw_caption": raw_caption,
        "caption_with_affiliate": caption_with_affiliate,
        "hashtags": hashtags,
        "formatted_post": formatted_post,
        "image_url": image_url,
        "schedule": schedule.isoformat(),
    }


@router.post("/publish", response_model=PublishResponse)
def publish_now(
    body: PublishRequest,
    db: Session = Depends(get_db),
):
    """
    Instagram'a gerçek post atma endpoint'i (Publish Now).

    Bu endpoint:
    - image_url ve caption alır
    - account_id veya ig_user_id kullanarak Instagram'a post atar
    - Sonucu döndürür (başarılıysa ig_post_id, hata varsa error_message)

    Args:
        body: PublishRequest
            - image_url: Görsel URL'si (public erişilebilir olmalı)
            - caption: Post caption'ı
            - account_id: DB'deki account ID (tercih edilen)
            - ig_user_id: Instagram Business Account ID (account_id yoksa)
            - access_token: Sadece ig_user_id kullanılıyorsa gerekli

    Returns:
        PublishResponse: {
            "success": bool,
            "ig_post_id": str | None,
            "error_message": str | None,
            "instagram_url": str | None
        }
    """
    # 1) Account bilgilerini al
    ig_user_id: str | None = None
    access_token: str | None = None

    if body.account_id:
        # DB'den account bilgilerini al
        account = db.query(Account).filter(Account.id == body.account_id).first()
        if not account:
            raise HTTPException(
                status_code=404, detail=f"Account with id {body.account_id} not found"
            )
        # SQLAlchemy model attribute'ları runtime'da string döner
        ig_user_id = account.ig_user_id  # type: ignore[assignment]
        access_token = account.access_token  # type: ignore[assignment]
    elif body.ig_user_id:
        # Direkt ig_user_id kullanılıyor
        ig_user_id = body.ig_user_id
        access_token = body.access_token
        if not access_token:
            raise HTTPException(
                status_code=400,
                detail="access_token is required when using ig_user_id directly",
            )
    else:
        raise HTTPException(
            status_code=400, detail="Either account_id or ig_user_id must be provided"
        )

    # 2) Instagram'a post at
    try:
        ig_response = publish_image(
            image_url=body.image_url,
            caption=body.caption,
            ig_user_id=ig_user_id,
            access_token=access_token,
        )

        # 3) Sonucu kontrol et
        if isinstance(ig_response, dict) and "error" in ig_response:
            # Hata durumu
            error_msg = str(
                ig_response.get("error", {}).get("message", "Unknown error")
            )
            return PublishResponse(
                success=False,
                error_message=error_msg,
            )
        elif isinstance(ig_response, dict) and "id" in ig_response:
            # Başarılı
            post_id = str(ig_response["id"])
            return PublishResponse(
                success=True,
                ig_post_id=post_id,
                instagram_url=f"https://www.instagram.com/p/{post_id}/",
            )
        else:
            # Beklenmeyen response formatı
            return PublishResponse(
                success=False,
                error_message=f"Unexpected response format: {ig_response}",
            )

    except Exception as exc:  # noqa: BLE001
        return PublishResponse(
            success=False,
            error_message=f"Publish failed: {exc}",
        )


@router.post("/pipeline/run", response_model=PostRead)
def run_pipeline(
    body: GenerateAndPublishRequest,
    db: Session = Depends(get_db),
):
    """
    Core MVP pipeline (Legacy - artık sadece DRAFT üretir).

    NOT: Bu endpoint artık otomatik publish ETMEZ!
    Sadece içerik üretir ve DRAFT olarak kaydeder.
    Yayınlamak için POST /api/approve/{post_id} ve POST /api/publish/{post_id} kullanın.

    Bu endpoint:
    - Konu sec (manual veya trend_radar)
    - OpenAI ile caption uret (+ affiliate ekle)
    - Gorsel URL uret
    - DRAFT olarak DB'ye kaydet (PUBLISH ETMEZ!)
    """

    # 1) Hangi account adina calisacagiz?
    if body.account_id is not None:
        account = db.query(Account).filter(Account.id == body.account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
    else:
        account = db.query(Account).first()
        if not account:
            raise HTTPException(
                status_code=400,
                detail="No accounts configured. Create one with POST /api/accounts",
            )

    # 2) Konu secimi
    topic = body.topic or get_trending_topics()[0]

    # 3) Caption uret (OpenAI + affiliate)
    caption = None
    error_message: str | None = None
    try:
        caption = generate_caption(topic)
        caption = attach_affiliate(caption)
    except Exception as exc:  # noqa: BLE001
        error_message = f"caption_error: {exc}"
        # Basarisiz olsa da fallback caption ile devam edebiliriz
        caption = f"Test post: {topic} #AI #Automation #Test"

    # 4) Gorsel URL uret
    image_url = generate_image(topic)

    # 5) Hashtag üret (opsiyonel, eğer yoksa)
    hashtags_list = []
    try:
        hashtags_list = generate_hashtags(topic, caption=caption, count=10)
    except Exception:
        hashtags_list = ["#AI", "#Technology", "#Innovation"]

    # 6) Image prompt üret (opsiyonel)
    image_prompt = None
    try:
        image_prompt = generate_image_prompt(topic)
    except Exception:
        image_prompt = f"Square 1:1 Instagram post image, high quality, {topic}"

    # 7) Post'u DRAFT olarak kaydet (PUBLISH ETMEZ!)
    post = Post(
        account_id=account.id,
        topic=topic,
        caption=caption,
        hashtags=json.dumps(hashtags_list),
        image_prompt=image_prompt,
        image_url=image_url,
        status=PostStatus.DRAFT,  # DRAFT olarak kaydet
        error_message=error_message,
        created_at=datetime.utcnow(),
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    # NOT: Artık otomatik publish yapılmıyor!
    # Yayınlamak için:
    # 1) POST /api/approve/{post_id}
    # 2) POST /api/publish/{post_id}

    return post


@router.post("/generate", response_model=GenerateResponse)
def generate_content(
    body: GenerateRequest,
    db: Session = Depends(get_db),
):
    """
    İçerik üretimi endpoint'i - DRAFT olarak kaydeder, publish etmez.

    Bu endpoint:
    - Caption üretir (OpenAI)
    - Hashtag üretir (OpenAI)
    - Image prompt üretir (OpenAI)
    - Görsel üretir (OpenAI gpt-image-1 / dall-e-3)
    - Görseli local storage'a kaydeder
    - Post'u DRAFT olarak DB'ye kaydeder

    Returns:
        GenerateResponse: {
            "post_id": int,
            "caption": str,
            "hashtags": list[str],
            "image_prompt": str,
            "image_url": str,  # /static/generated/{filename}
            "status": "draft",
            "created_at": datetime
        }
    """
    # 1) Konu seçimi
    topic = body.topic or get_trending_topics()[0]

    # 2) Caption üret
    try:
        caption = generate_caption(topic)
    except Exception as e:
        caption = f"Test post about {topic}. #AI #Automation"
        print(f"Warning: Caption generation failed: {e}")

    # 3) Hashtag üret
    try:
        hashtags = generate_hashtags(topic, caption=caption, count=10)
    except Exception as e:
        hashtags = ["#AI", "#Technology", "#Innovation", "#Motivation", "#Success"]
        print(f"Warning: Hashtag generation failed: {e}")

    # 4) Image prompt üret
    try:
        image_prompt = generate_image_prompt(topic)
    except Exception as e:
        image_prompt = (
            f"Square 1:1 Instagram post image, high quality, modern style, {topic}"
        )
        print(f"Warning: Image prompt generation failed: {e}")

    # 5) Arka plan görseli üret ve kaydet
    try:
        png_bytes = generate_image_png_bytes(image_prompt)
        relative_path_bg, public_url_bg = save_png_bytes_to_generated(png_bytes)
    except Exception as e:
        print(f"Warning: Image generation failed: {e}")
        relative_path_bg = None
        public_url_bg = (
            "https://images.pexels.com/photos/1032650/pexels-photo-1032650.jpeg"
        )

    # 6) Arka plan üzerine metin bas (render-image); final görsel media/ içinde
    relative_path = relative_path_bg
    public_url = public_url_bg
    background_full = (
        BASE_DIR / "storage" / relative_path_bg if relative_path_bg else None
    )
    if background_full and background_full.exists():
        try:
            signature = (body.signature or "ince düşlerim").strip()
            # If user requested story format, render a vertical story-sized image
            target = (
                "story" if getattr(body, "post_type", None) == "story" else "square"
            )
            rel_path_final, abs_path_final = render_image(
                background_path=str(background_full),
                text=caption,
                signature=signature,
                style=body.render_style or "minimal_dark",
                target=target,
            )
            with open(abs_path_final, "rb") as f:
                final_bytes = f.read()
            # Final görsel media/ klasöründe kaydedildi; şimdi remote server'a yükleyip public URL al
            filename_final = os.path.basename(abs_path_final)
            try:
                public_url = upload_to_remote_server(final_bytes, filename_final)
            except Exception as e:
                print(f"[WARNING] Final image upload failed: {e}")
                # Fallback: local media path
                public_url = f"/media/{filename_final}"
            relative_path = rel_path_final
        except Exception as e:
            print(f"Warning: Render image failed, using background only: {e}")

    # 7) Post type
    post_type = PostType.POST
    if body.post_type == "story":
        post_type = PostType.STORY
    elif body.post_type == "reels":
        post_type = PostType.REELS

    # 8) DB'ye DRAFT olarak kaydet (kullanıcı onaylamadan paylaşım yapılmaz)
    post = Post(
        topic=topic,
        caption=caption,
        hashtags=json.dumps(hashtags),  # JSON string olarak sakla
        image_prompt=image_prompt,
        image_path=relative_path,
        image_url=public_url,
        type=post_type,
        status=PostStatus.DRAFT,
        created_at=datetime.utcnow(),
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    # 9) Response döndür
    return GenerateResponse(
        post_id=post.id,
        caption=caption,
        hashtags=hashtags,
        image_prompt=image_prompt,
        image_url=public_url,
        status="draft",
        created_at=post.created_at,
    )


@router.post("/render-image", response_model=RenderImageResponse)
def api_render_image(body: RenderImageRequest):
    """
    1080x1080 arka plan üzerine ortalanmış metin + altta imza basar.
    Görsel media/ klasörüne kaydedilir.

    Input: background_path, text, signature, style (minimal_dark | pastel_soft | neon_city)
    Output: final_image_path (örn: media/{uuid}.png)
    """
    try:
        rel_path, _ = render_image(
            background_path=body.background_path,
            text=body.text,
            signature=body.signature,
            style=body.style or "minimal_dark",
        )
        return RenderImageResponse(final_image_path=rel_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render failed: {e}")


@router.post("/approve/{post_id}")
def approve_post(
    post_id: int,
    db: Session = Depends(get_db),
):
    """
    Post'u onayla - status'u "approved" yapar.

    Args:
        post_id: Onaylanacak post ID'si

    Returns:
        dict: {"success": bool, "message": str}
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail=f"Post with id {post_id} not found")

    if post.status == PostStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Post is already published")

    post.status = PostStatus.APPROVED  # type: ignore[assignment]
    db.add(post)
    db.commit()

    return {"success": True, "message": f"Post {post_id} approved successfully"}


@router.post("/scheduled/check")
def trigger_scheduled_check():
    """
    Zamanlanmış post kontrolünü hemen çalıştır (manuel tetikleme).
    Zamanı gelen post'lar yayınlanır.
    Returns: {"checked": int, "published": int, "errors": list}
    """
    checked, published, errors = run_scheduled_publish()
    return {"checked": checked, "published": published, "errors": errors}


@router.post("/publish/{post_id}", response_model=PublishResponse)
def publish_post_by_id(
    post_id: int,
    body: PublishRequest,
    db: Session = Depends(get_db),
):
    """
    Onaylanmış bir post'u Instagram'a yayınla.

    Post'un status'u "approved" olmalı, aksi halde 400 hatası döner.

    Args:
        post_id: Yayınlanacak post ID'si
        body: Account bilgileri (account_id veya ig_user_id + access_token)

    Returns:
        PublishResponse: Yayınlama sonucu
    """
    # 1) Post'u yükle
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail=f"Post with id {post_id} not found")

    # 2) Status kontrolü - sadece approved post'lar yayınlanabilir
    if post.status != PostStatus.APPROVED:
        raise HTTPException(
            status_code=400,
            detail=f"Post must be approved before publishing. Current status: {post.status.value}",
        )

    # 3) Account bilgilerini al
    ig_user_id: str | None = None
    access_token: str | None = None

    if body.account_id:
        account = db.query(Account).filter(Account.id == body.account_id).first()
        if not account:
            raise HTTPException(
                status_code=404, detail=f"Account with id {body.account_id} not found"
            )
        ig_user_id = account.ig_user_id  # type: ignore[assignment]
        access_token = account.access_token  # type: ignore[assignment]
    elif body.ig_user_id:
        ig_user_id = body.ig_user_id
        access_token = body.access_token
        if not access_token:
            raise HTTPException(
                status_code=400,
                detail="access_token is required when using ig_user_id directly",
            )
    else:
        # Body'de account bilgisi yoksa, ilk account'u fallback olarak kullan
        account = db.query(Account).first()
        if not account:
            raise HTTPException(
                status_code=400,
                detail="No accounts configured. Create one with POST /api/accounts or provide account_id / ig_user_id.",
            )
        ig_user_id = account.ig_user_id  # type: ignore[assignment]
        access_token = account.access_token  # type: ignore[assignment]
        body.account_id = account.id  # type: ignore[assignment]

    # .env'deki token guncel olabilir (DB'deki Account eski token tutuyor olabilir)
    env_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if env_token:
        access_token = env_token

    # Eğer body ile post_type gönderildiyse, post.type'ı override edelim
    if getattr(body, "post_type", None):
        try:
            post.type = PostType(body.post_type)
            db.add(post)
            db.commit()
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid post_type: {body.post_type}"
            )

    # 4) Instagram'a post at
    # Post'un kendi image_url ve caption'ını kullan
    # Eğer local storage'dan geliyorsa, full URL'e çevir
    image_url = post.image_url or body.image_url
    if image_url and (
        image_url.startswith("/static/") or image_url.startswith("/media/")
    ):
        # Local static/media file ise, full URL'e çevir
        # Use BASE_URL from config if available, otherwise fall back to localhost
        domain = BASE_URL or "http://127.0.0.1:8000"
        # ensure no trailing slash duplication
        image_url = domain.rstrip("/") + image_url

    caption = post.caption or body.caption
    # Eğer story ise caption zorunlu değil
    if post.type != PostType.STORY and not caption:
        raise HTTPException(status_code=400, detail="Post caption is required")

    # Post'taki hashtag'leri al (DB'de JSON veya comma-separated olabilir)
    hashtags_list = []
    if post.hashtags:
        try:
            hashtags_list = json.loads(post.hashtags)
        except Exception:
            hashtags_list = [
                h.strip() for h in str(post.hashtags).split(",") if h.strip()
            ]

    # Instagram'a gidecek tam metni oluştur (caption + hashtag'ler)
    try:
        formatted_caption = (
            format_post_text(caption, hashtags_list) if hashtags_list else caption
        )
    except Exception:
        formatted_caption = caption

    # 5) Zamanlanmış yayın kontrolü
    now = datetime.utcnow()
    if body.scheduled_at:
        try:
            # ISO format string'i datetime'a çevir
            scheduled_str = body.scheduled_at.strip()
            # 'Z' karakterini '+00:00' ile değiştir (Python fromisoformat için)
            if scheduled_str.endswith("Z"):
                scheduled_str = scheduled_str[:-1] + "+00:00"
            # ISO format parse et
            try:
                scheduled_at_utc = datetime.fromisoformat(scheduled_str)
            except ValueError:
                # Fallback: strptime ile parse et
                # ISO format: 2026-02-05T20:31:00.000Z veya 2026-02-05T20:31:00Z
                scheduled_str_clean = scheduled_str.replace("+00:00", "").replace(
                    "Z", ""
                )
                if "." in scheduled_str_clean:
                    scheduled_at_utc = datetime.strptime(
                        scheduled_str_clean, "%Y-%m-%dT%H:%M:%S.%f"
                    )
                else:
                    scheduled_at_utc = datetime.strptime(
                        scheduled_str_clean, "%Y-%m-%dT%H:%M:%S"
                    )
            # Her zaman naive UTC yap (karşılaştırma için now ile uyumlu; aksi halde TypeError)
            if scheduled_at_utc.tzinfo is not None:
                scheduled_at_utc = scheduled_at_utc.astimezone(timezone.utc).replace(
                    tzinfo=None
                )

            if scheduled_at_utc <= now:
                raise HTTPException(
                    status_code=400,
                    detail="Seçilen yayın saati geçmişe denk geliyor. Lütfen gelecek bir tarih ve saat seçin.",
                )
            # Zamanlanmış yayın: post'u scheduled olarak işaretle, hemen yayınlama
            post.scheduled_at = scheduled_at_utc  # type: ignore[assignment]
            db.add(post)
            db.commit()
            return PublishResponse(
                success=True,
                error_message=None,
                ig_post_id=None,
                instagram_url=None,
            )
        except HTTPException:
            raise  # 400 "Scheduled time must be in the future" vb. olduğu gibi dönsün
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid scheduled_at format. Expected ISO format (e.g., 2026-02-05T20:31:00Z). Error: {str(e)}",
            )
        except Exception as e:
            import traceback

            print(f"[ERROR] Scheduled publish failed: {e}")
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=500, detail=f"Failed to schedule post: {str(e)}"
            )

    # scheduled_at yoksa veya None ise, hemen yayınla
    try:
        from app.services.instagram import publish_story

        # Branch for story vs post
        if post.type == PostType.STORY:
            # Story paylaşımı için image_url zorunludur
            if not image_url:
                raise HTTPException(
                    status_code=400, detail="Story paylaşımı için image_url zorunludur"
                )
            # DEBUG: log container create payload intent
            try:
                print(
                    f"[DEBUG][routes.publish_post_by_id] Preparing STORY container for post {post_id}: image_url={image_url}"
                )
            except Exception:
                pass
            # Before publishing story: if our stored image is square (local media), create a proper 1080x1920 story image
            try:
                from PIL import Image

                # Determine possible local path for the image
                abs_candidate = None
                if getattr(post, "image_path", None):
                    p = Path(post.image_path)
                    if not p.is_absolute():
                        p = BASE_DIR / p
                    if p.exists():
                        abs_candidate = p
                # If image_url points to local media path, derive local file
                if not abs_candidate and image_url and image_url.startswith("/media/"):
                    p = BASE_DIR / image_url.lstrip("/")
                    if p.exists():
                        abs_candidate = p
                elif (
                    not abs_candidate
                    and image_url
                    and image_url.startswith((BASE_URL or ""))
                ):
                    # strip BASE_URL to find local media
                    try:
                        rel = image_url.replace(BASE_URL.rstrip("/"), "")
                        if rel.startswith("/"):
                            p = BASE_DIR / rel.lstrip("/")
                            if p.exists():
                                abs_candidate = p
                    except Exception:
                        abs_candidate = None

                if abs_candidate and abs_candidate.exists():
                    # create 1080x1920 canvas and paste centered scaled image
                    img = Image.open(abs_candidate).convert("RGBA")
                    target_w, target_h = 1080, 1920
                    # scale image to fit inside target while preserving aspect ratio
                    img_ratio = img.width / img.height
                    max_w = target_w
                    max_h = target_h
                    if img.width > max_w or img.height > max_h:
                        # scale down
                        if img_ratio >= 1:
                            # wide
                            new_w = min(img.width, max_w)
                            new_h = int(new_w / img_ratio)
                            if new_h > max_h:
                                new_h = max_h
                                new_w = int(new_h * img_ratio)
                        else:
                            # tall
                            new_h = min(img.height, max_h)
                            new_w = int(new_h * img_ratio)
                            if new_w > max_w:
                                new_w = max_w
                                new_h = int(new_w / img_ratio)
                        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    # paste centered on story canvas
                    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 255))
                    x = (target_w - img.width) // 2
                    y = (target_h - img.height) // 2
                    canvas.paste(img, (x, y), img)
                    # save to media
                    ensure_media_dir = None
                    try:
                        from app.services.image_render import ensure_media_dir

                        ensure_media_dir()
                    except Exception:
                        pass
                    out_name = f"story-{uuid4()}.png"
                    out_path = BASE_DIR / "media" / out_name
                    canvas.convert("RGB").save(out_path, "PNG")
                    # upload to remote
                    try:
                        with open(out_path, "rb") as _f:
                            public_url_story = upload_to_remote_server(
                                _f.read(), out_name
                            )
                        image_url = public_url_story
                    except Exception:
                        image_url = f"/media/{out_name}"
            except Exception as e:
                print(
                    f"[WARN] Failed to generate story canvas from existing image: {e}"
                )

            # Call publish_story which returns creation_id and publish_response
            story_result = publish_story(
                image_url=image_url, ig_user_id=ig_user_id, access_token=access_token
            )
            # If error returned
            if isinstance(story_result, dict) and story_result.get("error"):
                err = story_result.get("error")
                # Save failure to DB and return clear message
                post.status = PostStatus.FAILED  # type: ignore[assignment]
                post.error_message = str(err.get("message", err))
                db.add(post)
                db.commit()
                raise HTTPException(
                    status_code=500,
                    detail=f"Story container oluşturulamadı: {err.get('message', err)}",
                )

            # story_result expected: {'creation_id':..., 'creation_response':..., 'publish_response':...}
            creation_id = story_result.get("creation_id")
            publish_resp = story_result.get("publish_response")
            # save creation_id temporarily in error_message field (or log). Better DB schema change can be added later.
            post.error_message = f"story_creation_id:{creation_id}"
            db.add(post)
            db.commit()

            ig_response = publish_resp
        else:
            # DEBUG: log container create payload intent (post)
            try:
                print(
                    f"[DEBUG][routes.publish_post_by_id] Preparing POST container for post {post_id}: image_url={image_url}, caption_present={bool(formatted_caption)}"
                )
            except Exception:
                pass
            ig_response = publish_image(
                image_url=image_url,
                caption=formatted_caption,
                ig_user_id=ig_user_id,
                access_token=access_token,
            )

        # 5) Sonucu kontrol et ve DB'yi güncelle
        if isinstance(ig_response, dict) and "error" in ig_response:
            post.status = PostStatus.FAILED  # type: ignore[assignment]
            post.error_message = str(ig_response.get("error", {}).get("message", "Unknown error"))  # type: ignore[assignment]
            db.add(post)
            db.commit()

            return PublishResponse(
                success=False,
                error_message=str(
                    ig_response.get("error", {}).get("message", "Unknown error")
                ),
            )
        elif isinstance(ig_response, dict) and "id" in ig_response:
            # Başarılı
            post.status = PostStatus.PUBLISHED  # type: ignore[assignment]
            post.published_at = datetime.utcnow()  # type: ignore[assignment]
            post.ig_post_id = str(ig_response["id"])  # type: ignore[assignment]
            if body.account_id:
                post.account_id = body.account_id  # type: ignore[assignment]
            db.add(post)
            db.commit()

            post_id_str = str(ig_response["id"])
            return PublishResponse(
                success=True,
                ig_post_id=post_id_str,
                instagram_url=f"https://www.instagram.com/p/{post_id_str}/",
            )
        else:
            post.status = PostStatus.FAILED  # type: ignore[assignment]
            post.error_message = f"Unexpected response format: {ig_response}"  # type: ignore[assignment]
            db.add(post)
            db.commit()

            return PublishResponse(
                success=False,
                error_message=f"Unexpected response format: {ig_response}",
            )

    except Exception as exc:  # noqa: BLE001
        post.status = PostStatus.FAILED  # type: ignore[assignment]
        post.error_message = f"Publish failed: {exc}"  # type: ignore[assignment]
        db.add(post)
        db.commit()

        return PublishResponse(
            success=False,
            error_message=f"Publish failed: {exc}",
        )


@router.get("/posts", response_model=list[PostDetailResponse])
def list_posts(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Tüm post'ları listele (opsiyonel status filtresi ile).

    Args:
        status: Filtreleme için status (draft/approved/published/failed)

    Returns:
        list[PostDetailResponse]: Post listesi
    """
    query = db.query(Post)

    if status:
        try:
            status_enum = PostStatus(status)
            query = query.filter(Post.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    posts = query.order_by(Post.created_at.desc()).all()

    # Hashtags'i JSON'dan parse et
    result = []
    for post in posts:
        hashtags_str = post.hashtags
        if hashtags_str:
            try:
                hashtags_list = json.loads(hashtags_str)
                hashtags_str = (
                    ", ".join(hashtags_list)
                    if isinstance(hashtags_list, list)
                    else hashtags_str
                )
            except json.JSONDecodeError:
                pass  # Zaten string ise olduğu gibi kullan

        result.append(
            PostDetailResponse(
                id=post.id,
                topic=post.topic,
                caption=post.caption,
                hashtags=hashtags_str,
                image_prompt=post.image_prompt,
                image_url=post.image_url,
                type=post.type.value if post.type else "post",
                status=post.status.value if post.status else "draft",
                created_at=post.created_at,
                scheduled_at=post.scheduled_at,
                published_at=post.published_at,
                ig_post_id=post.ig_post_id,
                error_message=post.error_message,
                account_id=post.account_id,
            )
        )

    return result


@router.delete("/posts/{post_id}")
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
):
    """
    Bir gönderiyi siler. Tüm durumlar (taslak, onaylı, yayında, hata) silinebilir.
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail=f"Post with id {post_id} not found")
    # Attempt to delete remote image if exists and points to uploads/ig or known upload base
    try:
        image_url = post.image_url
        if image_url:
            try:
                deleted = delete_remote_file(image_url)
                if deleted:
                    print(
                        f"[DELETE] Remote image deleted for post {post_id}: {image_url}"
                    )
                else:
                    print(
                        f"[DELETE] Remote image not deleted (may not exist or no creds): {image_url}"
                    )
            except Exception as e:
                print(f"[DELETE] Error deleting remote image for post {post_id}: {e}")
        # Also attempt to remove local media/storage files if present
        try:
            # image_path may reference storage/generated/{file}
            if getattr(post, "image_path", None):
                from pathlib import Path

                BASE_DIR = Path(__file__).resolve().parent.parent.parent
                local_path = BASE_DIR / str(post.image_path)
                if local_path.exists():
                    try:
                        local_path.unlink()
                        print(f"[DELETE] Removed local file: {local_path}")
                    except Exception as e:
                        print(f"[DELETE] Failed to remove local file {local_path}: {e}")
            # if image_url points to /media/{file}, try remove
            if image_url and image_url.startswith("/media/"):
                from pathlib import Path

                BASE_DIR = Path(__file__).resolve().parent.parent.parent
                local_media = BASE_DIR / image_url.lstrip("/")
                if local_media.exists():
                    try:
                        local_media.unlink()
                        print(f"[DELETE] Removed local media file: {local_media}")
                    except Exception as e:
                        print(
                            f"[DELETE] Failed to remove local media file {local_media}: {e}"
                        )
        except Exception as e:
            print(f"[DELETE] Local cleanup error for post {post_id}: {e}")

    except Exception as e:
        print(
            f"[DELETE] Error while attempting remote/local deletion for post {post_id}: {e}"
        )

    db.delete(post)
    db.commit()
    return {"success": True, "message": f"Post {post_id} deleted"}


@router.post("/posts/{post_id}/republish", response_model=PublishResponse)
def republish_post(
    post_id: int,
    body: PublishRequest,
    db: Session = Depends(get_db),
):
    """
    Herhangi bir gönderiyi onaylayıp yeniden Instagram'a yayınlar.
    - Draft/Failed → approved yapılır ve publish edilir
    - Approved → direkt publish edilir
    - Published → tekrar publish edilir (Instagram'da aynı görsel tekrar yayınlanabilir)
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail=f"Post with id {post_id} not found")

    # Eğer draft veya failed ise, önce approved yap
    if post.status in (PostStatus.DRAFT, PostStatus.FAILED):
        post.status = PostStatus.APPROVED  # type: ignore[assignment]
        post.error_message = None  # type: ignore[assignment]
        db.add(post)
        db.commit()

    # Şimdi publish işlemini çalıştır (approved veya published olsun)
    # publish_post_by_id sadece approved kontrolü yapıyor, bu yüzden published için bypass edelim
    original_status = post.status
    if post.status == PostStatus.PUBLISHED:
        # Published post'u geçici olarak approved yap ki publish_post_by_id çalışsın
        post.status = PostStatus.APPROVED  # type: ignore[assignment]
        db.add(post)
        db.commit()

    try:
        result = publish_post_by_id(post_id, body, db)
        return result
    except HTTPException:
        # Eğer publish başarısız olursa, orijinal status'u geri yükle
        if original_status == PostStatus.PUBLISHED:
            post.status = PostStatus.PUBLISHED  # type: ignore[assignment]
            db.add(post)
            db.commit()
        raise


@router.get("/posts/{post_id}", response_model=PostDetailResponse)
def get_post(
    post_id: int,
    db: Session = Depends(get_db),
):
    """
    Belirli bir post'un detaylarını getir.

    Args:
        post_id: Post ID'si

    Returns:
        PostDetailResponse: Post detayları
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail=f"Post with id {post_id} not found")

    hashtags_str = post.hashtags
    if hashtags_str:
        try:
            hashtags_list = json.loads(hashtags_str)
            hashtags_str = (
                ", ".join(hashtags_list)
                if isinstance(hashtags_list, list)
                else hashtags_str
            )
        except json.JSONDecodeError:
            pass

    return PostDetailResponse(
        id=post.id,
        topic=post.topic,
        caption=post.caption,
        hashtags=hashtags_str,
        image_prompt=post.image_prompt,
        image_url=post.image_url,
        type=post.type.value if post.type else "post",
        status=post.status.value if post.status else "draft",
        created_at=post.created_at,
        scheduled_at=post.scheduled_at,
        published_at=post.published_at,
        ig_post_id=post.ig_post_id,
        error_message=post.error_message,
        account_id=post.account_id,
    )
