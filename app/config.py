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
