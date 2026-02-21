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
    image_url_post = Column(String, nullable=True)
    image_url_story = Column(String, nullable=True)

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


class AutomationSetting(Base):
    """
    Automation settings per account for automatic draft generation.
    """

    __tablename__ = "automation_settings"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    enabled = Column(Integer, default=0, nullable=False)  # use 0/1
    frequency = Column(String, nullable=False, default="daily")  # daily|weekly
    daily_count = Column(Integer, nullable=True)
    weekly_count = Column(Integer, nullable=True)
    start_hour = Column(Integer, nullable=True)
    end_hour = Column(Integer, nullable=True)
    # store full time strings "HH:MM"
    start_time = Column(String, nullable=True)
    end_time = Column(String, nullable=True)
    only_draft = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    # lists stored as JSON strings
    daily_times = Column(Text, nullable=True)  # JSON array of "HH:MM"
    weekly_times = Column(Text, nullable=True)  # JSON array of {"day": "Mon", "time":"HH:MM"}


class AutomationRun(Base):
    """
    Records automation scheduler runs to prevent duplicate draft generation across processes.
    Unique constraint on (setting_id, run_date) ensures a single claim per day per setting.
    """

    __tablename__ = "automation_runs"

    id = Column(Integer, primary_key=True, index=True)
    setting_id = Column(Integer, ForeignKey("automation_settings.id"), nullable=False)
    run_date = Column(String, nullable=False)  # ISO date YYYY-MM-DD
    created_at = Column(DateTime, default=datetime.utcnow)

