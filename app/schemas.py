from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AccountBase(BaseModel):
    ig_user_id: str
    niche: str


class AccountCreate(AccountBase):
    access_token: str


class AccountRead(AccountBase):
    id: int

    class Config:
        from_attributes = True


class GenerateAndPublishRequest(BaseModel):
    """
    Tek seferlik içerik üret + publish pipeline giriş modeli.
    """

    account_id: Optional[int] = None  # Bos ise ilk account kullanilir
    topic: Optional[str] = None  # Bos ise trend_radar'dan gelir


class PostRead(BaseModel):
    """
    Pipeline sonunda geri dönecek log modeli.
    """

    id: int
    account_id: Optional[int]
    topic: Optional[str]
    caption: Optional[str]
    image_url: Optional[str]
    status: str
    error_message: Optional[str]
    ig_post_id: Optional[str]
    created_at: datetime
    published_at: Optional[datetime]

    class Config:
        from_attributes = True


class PublishRequest(BaseModel):
    """
    Instagram'a post atma isteği.

    Not:
    - /api/publish (legacy) için image_url + caption body'den gelebilir.
    - /api/publish/{post_id} için genellikle post'un kendi image_url ve caption'ı kullanılır;
      bu yüzden bu alanlar opsiyoneldir.
    - account_id veya ig_user_id + access_token'den en az biri sağlanmalıdır (aksi hâlde 400 döner).
    - scheduled_at: Gelecek bir tarih/saat verilirse, post zamanlanır ve o zamanda otomatik yayınlanır.
    """

    image_url: Optional[str] = None  # Opsiyonel: override için
    caption: Optional[str] = None  # Opsiyonel: override için
    account_id: Optional[int] = None  # DB'deki account ID (tercih edilen)
    ig_user_id: Optional[str] = None  # Instagram Business Account ID (account_id yoksa)
    access_token: Optional[str] = None  # Sadece ig_user_id kullanılıyorsa gerekli
    scheduled_at: Optional[str] = (
        None  # Zamanlanmış yayın için tarih/saat (ISO format string, UTC)
    )
    post_type: Optional[str] = None  # post/story/reels (opsiyonel override)


class AutomationSettingCreate(BaseModel):
    enabled: bool = True
    frequency: str = "daily"
    daily_count: Optional[int] = None
    weekly_count: Optional[int] = None
    start_hour: Optional[int] = None
    end_hour: Optional[int] = None
    only_draft: bool = True


class AutomationSettingRead(BaseModel):
    id: int
    account_id: int
    enabled: bool
    frequency: str
    daily_count: Optional[int]
    weekly_count: Optional[int]
    start_hour: Optional[int]
    end_hour: Optional[int]
    only_draft: bool
    created_at: datetime
    updated_at: Optional[datetime]
    last_run_at: Optional[datetime]

    class Config:
        from_attributes = True


class PublishResponse(BaseModel):
    """
    Instagram post atma sonucu.
    """

    success: bool
    ig_post_id: Optional[str] = None  # Başarılıysa Instagram post ID
    error_message: Optional[str] = None  # Hata varsa mesaj
    instagram_url: Optional[str] = None  # Post URL'si (başarılıysa)


class RenderImageRequest(BaseModel):
    """Görsel üzerine metin basma isteği"""

    background_path: str  # Arka plan görsel yolu (örn: storage/generated/xxx.png)
    text: str  # Ana metin
    signature: str  # En altta küçük imza metni
    style: str = "minimal_dark"  # minimal_dark | pastel_soft | neon_city


class RenderImageResponse(BaseModel):
    """Render sonucu"""

    final_image_path: str  # media/{uuid}.png (relative path)


class GenerateRequest(BaseModel):
    """İçerik üretim isteği"""

    topic: Optional[str] = None  # Boş ise trend_radar'dan gelir
    post_type: Optional[str] = "post"  # post/story/reels
    render_style: Optional[str] = (
        "minimal_dark"  # minimal_dark | pastel_soft | neon_city
    )
    signature: Optional[str] = None  # İmza metni (yoksa varsayılan kullanılır)


class GenerateResponse(BaseModel):
    """İçerik üretim sonucu"""

    post_id: int
    caption: str
    hashtags: list[str]
    image_prompt: str
    image_url: str  # /static/generated/{filename}
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class PostDetailResponse(BaseModel):
    """Post detay response"""

    id: int
    topic: Optional[str]
    caption: Optional[str]
    hashtags: Optional[str]  # JSON string veya comma-separated
    image_prompt: Optional[str]
    image_url: Optional[str]
    type: str
    status: str
    created_at: datetime
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime]
    ig_post_id: Optional[str]
    error_message: Optional[str]
    account_id: Optional[int]

    class Config:
        from_attributes = True
