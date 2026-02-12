from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
)
from datetime import datetime
import enum
from app.database import Base


class PostStatus(str, enum.Enum):
    """Post durumları"""

    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"


class PostType(str, enum.Enum):
    """Post türleri"""

    POST = "post"
    STORY = "story"
    REELS = "reels"


class Post(Base):
    """
    İçerik üretim/publish akışının log kaydı.

    Status flow:
    draft -> approved -> published
    """

    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)

    # İçerik bilgileri
    topic = Column(String, nullable=True)
    caption = Column(Text, nullable=True)
    hashtags = Column(
        Text, nullable=True
    )  # JSON array olarak saklanabilir veya comma-separated
    image_prompt = Column(Text, nullable=True)  # OpenAI'ye gönderilen görsel prompt'u
    image_path = Column(
        String, nullable=True
    )  # Local storage path (örn: generated/abc.png)
    image_url = Column(
        String, nullable=True
    )  # Public URL (örn: /static/generated/abc.png)

    # Post türü
    type = Column(SQLEnum(PostType), default=PostType.POST, nullable=False)

    # Zaman bilgileri
    scheduled_at = Column(DateTime, nullable=True)
    # Separate scheduling for post and story (allow scheduling both at different times)
    scheduled_at_post = Column(DateTime, nullable=True)
    scheduled_at_story = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)
    # Separate published timestamps and IG ids for post/story
    published_at_post = Column(DateTime, nullable=True)
    published_at_story = Column(DateTime, nullable=True)
    ig_post_id_post = Column(String, nullable=True)
    ig_post_id_story = Column(String, nullable=True)

    # Durum bilgileri
    status = Column(SQLEnum(PostStatus), default=PostStatus.DRAFT, nullable=False)
    error_message = Column(Text, nullable=True)
    ig_post_id = Column(String, nullable=True)  # Instagram media ID

    # Hangi account adına yayınlandı?
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)


class Account(Base):
    """
    Instagram Business hesabı + access token bilgilerinin saklandığı tablo.
    """

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    ig_user_id = Column(String, nullable=False)
    access_token = Column(Text, nullable=False)
    niche = Column(String, nullable=False)
