# AutoSocial AI - MVP Backend Skeleton
# FastAPI + Celery + Redis + PostgreSQL

# .env'i uygulama kokunden en basta yukle (uvicorn cwd farkli olabilir)
from pathlib import Path as _Path
from dotenv import load_dotenv as _load_dotenv

_env_path = _Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    _load_dotenv(dotenv_path=_env_path, override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api.routes import router
from app.services.scheduler import daily_post_cycle
from app.database import SessionLocal, Base, engine
from app.models import Account
from app.config import OPENAI_API_KEY
from app.services.scheduled_publisher import run_scheduled_publish
import threading

app = FastAPI(
    title="AutoSocial AI MVP",
    description="AI-powered social media content generation platform",
    version="1.0.0",
)

# CORS: Live Server (5500) veya başka porttan API çağrıları için
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/", include_in_schema=False)
def root():
    """Ana sayfa: kullanıcı arayüzü. API dokümantasyonu için /docs"""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return RedirectResponse(url="/docs")


@app.get("/panel", include_in_schema=False)
def panel():
    """Kullanıcı arayüzü için alternatif yol (/panel)."""
    index_path = FRONTEND_DIR / "index.html"
    return FileResponse(index_path)


# CSS ve JS: hem Live Server (frontend/index.html) hem FastAPI (/) ile uyumlu
if FRONTEND_DIR.exists():

    @app.get("/styles.css", include_in_schema=False)
    def serve_css():
        return FileResponse(
            FRONTEND_DIR / "styles.css",
            media_type="text/css",
        )

    @app.get("/app.js", include_in_schema=False)
    def serve_js():
        return FileResponse(
            FRONTEND_DIR / "app.js",
            media_type="application/javascript",
        )

    @app.get("/assets/styles.css", include_in_schema=False)
    def serve_css_assets():
        return FileResponse(FRONTEND_DIR / "styles.css", media_type="text/css")

    @app.get("/assets/app.js", include_in_schema=False)
    def serve_js_assets():
        return FileResponse(
            FRONTEND_DIR / "app.js", media_type="application/javascript"
        )

    app.mount(
        "/assets", StaticFiles(directory=str(FRONTEND_DIR.resolve())), name="assets"
    )

app.include_router(router, prefix="/api", tags=["API"])

# Static files - storage/generated/ görselleri (/static/generated/...)
STORAGE_DIR = BASE_DIR / "storage"
if STORAGE_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STORAGE_DIR)), name="static")

# Render edilen final görseller media/ klasöründe (/media/xxx.png)
MEDIA_DIR = BASE_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")


@app.on_event("startup")
def start_scheduler():
    """
    - DB tablolarini olustur
    - OPENAI_API_KEY varsa ve account varsa: gunluk post dongusunu baslat (demo)
    """
    try:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            accounts = db.query(Account).all()
            if accounts and OPENAI_API_KEY:
                daily_post_cycle(accounts)
            elif accounts and not OPENAI_API_KEY:
                print("Warning: OPENAI_API_KEY not set; skipping startup post cycle.")
        finally:
            db.close()
    except Exception as e:
        print(f"Warning: Startup task failed: {e}")
        print("Application will continue; some features may be limited.")

    # Zamanlanmış post'ları kontrol eden background task
    def check_scheduled_posts():
        try:
            run_scheduled_publish()
        except Exception as e:
            import traceback

            print(f"[SCHEDULED] Error: {e}")
            print(traceback.format_exc())
        t = threading.Timer(30.0, check_scheduled_posts)
        t.daemon = True
        t.start()

    t = threading.Timer(5.0, check_scheduled_posts)
    t.daemon = True
    t.start()
    print("[SCHEDULED] Background task started (checks every 30 seconds)")
