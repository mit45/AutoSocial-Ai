import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
# Get the project root directory (parent of app directory)
BASE_DIR = Path(__file__).resolve().parent.parent
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
else:
    print(f"Warning: .env file not found at {env_path}")


# BOM: .env UTF-8 BOM ile kaydedilirse ilk anahtar '\ufeffOPENAI_API_KEY' olur
def _getenv(key: str, default: str = ""):
    v = os.getenv(key)
    if v is not None and v != "":
        return v
    return os.getenv("\ufeff" + key, default) or ""


# Core services
# Use SQLite by default for the MVP (no PostgreSQL connection attempts).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./autosocial.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
OPENAI_API_KEY = _getenv("OPENAI_API_KEY")

# Instagram / Facebook App config
INSTAGRAM_APP_NAME = os.getenv("INSTAGRAM_APP_NAME")
INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID")
INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET")

# Image upload config
UPLOAD_BASE_URL = os.getenv("UPLOAD_BASE_URL", "https://umittopuz.com/uploads/ig")
UPLOAD_API_URL = os.getenv(
    "UPLOAD_API_URL", "https://umittopuz.com/api/upload"
)  # Upload API endpoint'i
UPLOAD_API_KEY = os.getenv("UPLOAD_API_KEY", "")  # API key varsa

# FTP config (görsel yükleme için)
FTP_HOST = os.getenv("FTP_HOST", "")
FTP_USER = os.getenv("FTP_USER", "")
FTP_PASSWORD = os.getenv("FTP_PASSWORD", "")

# Base URL for serving media (set to your domain, e.g. https://umittopuz.com)
BASE_URL = _getenv("BASE_URL", "http://127.0.0.1:8000")

# Cloudflare R2 (S3-compatible) configuration (optional)
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "")  # e.g. https://cdn.umittopuz.com/ig


# ---------------------------------------------------------------------------
# Authentication & Encryption
# ---------------------------------------------------------------------------
# SECRET_KEY: JWT imzalama anahtarı.
# ENCRYPTION_KEY: Fernet için hassas alanların simetrik şifrelenmesi.
# Her ikisi de .env içinde atanmalı; yoksa süreç başında rastgele üretilir
# (bu durumda sunucu yeniden başlatıldığında eski şifreli veriler çözülemez!).
SECRET_KEY = _getenv("SECRET_KEY", "")
ENCRYPTION_KEY = _getenv("ENCRYPTION_KEY", "")
JWT_ALGORITHM = _getenv("JWT_ALGORITHM", "HS256")
try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(_getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
except Exception:
    ACCESS_TOKEN_EXPIRE_MINUTES = 60
try:
    REFRESH_TOKEN_EXPIRE_DAYS = int(_getenv("REFRESH_TOKEN_EXPIRE_DAYS", "14"))
except Exception:
    REFRESH_TOKEN_EXPIRE_DAYS = 14

# Geliştirme kolaylığı: AUTH_REQUIRED=0 ise auth dependency'leri pas geçilir
# (yalnızca lokal debug için). Varsayılan 1 (zorunlu).
AUTH_REQUIRED = _getenv("AUTH_REQUIRED", "1").strip() not in ("0", "false", "False", "")

# İlk kurulum için (yalnızca DB boşsa) otomatik oluşturulacak admin kullanıcı.
# Atanmamışsa ilk açılışta kullanıcı UI'dan kayıt olmalı.
BOOTSTRAP_ADMIN_EMAIL = _getenv("BOOTSTRAP_ADMIN_EMAIL", "")
BOOTSTRAP_ADMIN_PASSWORD = _getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
