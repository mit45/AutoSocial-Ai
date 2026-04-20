from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    UniqueConstraint,
    Index,
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


class UserRole(str, enum.Enum):
    """Sistem kullanıcı rolleri."""

    ADMIN = "admin"
    USER = "user"


class User(Base):
    """
    SaaS kullanıcısı. Bir kullanıcı birden fazla Instagram Account bağlayabilir.
    Parola bcrypt hash olarak saklanır (security.hash_password).
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    role = Column(SQLEnum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)


class Post(Base):
    """
    İçerik üretim/publish akışının log kaydı.

    Status flow:
    draft -> approved -> published
    """

    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)

    # Sahiplik
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

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
    `access_token` Fernet ile şifreli saklanır (security.encrypt_secret).
    """

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    ig_user_id = Column(String, nullable=False)
    access_token = Column(Text, nullable=False)
    niche = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)


class AutomationSetting(Base):
    """
    Automation settings per account for automatic draft generation.
    """

    __tablename__ = "automation_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
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
    slot_key separates multiple daily/weekly time slots on the same calendar day.
    """

    __tablename__ = "automation_runs"
    __table_args__ = (
        UniqueConstraint("setting_id", "run_date", "slot_key", name="uq_automation_run_slot"),
    )

    id = Column(Integer, primary_key=True, index=True)
    setting_id = Column(Integer, ForeignKey("automation_settings.id"), nullable=False)
    run_date = Column(String, nullable=False)  # ISO date YYYY-MM-DD (local calendar day)
    slot_key = Column(String, nullable=False, default="")  # e.g. d|08:00, w|Mon|09:00, __fb__
    created_at = Column(DateTime, default=datetime.utcnow)


class CaptionHistory(Base):
    """
    Üretilen caption metinlerinin izi (Post dışı akışlar ve benzerlik havuzu).
    Örn. /api/generate-post önizlemesi; ana akışta metin zaten posts.caption içinde tutulur.
    """

    __tablename__ = "caption_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    caption = Column(Text, nullable=False)
    topic = Column(String, nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    source = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """
    Kritik işlemlerin (publish, delete, settings değişimi vb.) iz kaydı.
    Kullanıcı bazlı güvenlik ve hata ayıklama için.
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(64), nullable=False)
    entity = Column(String(64), nullable=True)  # e.g. "post", "account"
    entity_id = Column(String(64), nullable=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("ix_audit_logs_user_created", AuditLog.user_id, AuditLog.created_at)
