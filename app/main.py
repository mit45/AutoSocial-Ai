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
from app.services.scheduler_api import run_scheduled_publish, run_automation_check
import threading
import os
import errno

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
    # Serve favicon.ico for browsers requesting root favicon
    @app.get("/favicon.ico", include_in_schema=False)
    def serve_favicon():
        ico_path = FRONTEND_DIR / "favicon.svg"
        if ico_path.exists():
            return FileResponse(ico_path, media_type="image/svg+xml")
        return FileResponse(FRONTEND_DIR / "styles.css", media_type="text/css")

app.include_router(router, prefix="/api", tags=["API"])

# Static files - storage/generated/ görselleri (/static/generated/...)
# Ensure storage dir exists at startup so StaticFiles is always mounted.
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
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
        # Ensure new columns exist in existing SQLite DB (safe, non-destructive ALTERs)
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                existing = conn.execute(text("PRAGMA table_info('posts')")).fetchall()
                cols = [row[1] for row in existing]  # second field is name
                # Add image_url_post and image_url_story if missing
                if "image_url_post" not in cols:
                    try:
                        conn.execute(text("ALTER TABLE posts ADD COLUMN image_url_post VARCHAR"))
                        print("[MIGRATE] Added column posts.image_url_post")
                    except Exception as e:
                        print(f"[MIGRATE] Failed to add image_url_post: {e}")
                if "image_url_story" not in cols:
                    try:
                        conn.execute(text("ALTER TABLE posts ADD COLUMN image_url_story VARCHAR"))
                        print("[MIGRATE] Added column posts.image_url_story")
                    except Exception as e:
                        print(f"[MIGRATE] Failed to add image_url_story: {e}")
                # Create automation_runs table if missing
                try:
                    conn.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS automation_runs (id INTEGER PRIMARY KEY, setting_id INTEGER NOT NULL, run_date VARCHAR NOT NULL, created_at DATETIME, UNIQUE(setting_id, run_date))"
                        )
                    )
                except Exception as e:
                    print(f"[MIGRATE] Failed to ensure automation_runs table: {e}")
        except Exception as me:
            print(f"[MIGRATE] Migration check failed: {me}")
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

    # Prevent multiple scheduler instances (when using uvicorn --reload) by acquiring a PID lock.
    lock_path = BASE_DIR / ".scheduler.lock"
    def acquire_scheduler_lock():
        try:
            # Try create file exclusively
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return True
        except OSError as e:
            if e.errno == errno.EEXIST:
                # file exists - check if pid inside is alive
                try:
                    with open(lock_path, "r") as f:
                        pid = int(f.read().strip() or "0")
                    if pid:
                        try:
                            os.kill(pid, 0)
                            # process alive - do not start another scheduler
                            print("[SCHEDULED] Scheduler lock present, another process owns the scheduler (pid=%s)." % pid)
                            return False
                        except OSError:
                            # stale pid file - remove and try again
                            try:
                                os.remove(lock_path)
                            except Exception:
                                pass
                            return acquire_scheduler_lock()
                except Exception:
                    # couldn't read pid - skip starting scheduler
                    return False
            return False

    # Zamanlanmış post'ları kontrol eden background task
    def check_scheduled_posts():
        try:
            # Run automation generation only. Scheduled publishes are handled by explicit endpoints
            # or by the worker tasks dispatched by the automation scheduler to avoid duplicate publishes.
            try:
                run_automation_check()
            except Exception as e:
                print(f"[SCHEDULED][AUTOMATION] Error: {e}")
            # NOTE: Do NOT call run_scheduled_publish() here to avoid duplicate publishing paths.
        except Exception as e:
            import traceback

            print(f"[SCHEDULED] Error: {e}")
            print(traceback.format_exc())
        t = threading.Timer(30.0, check_scheduled_posts)
        t.daemon = True
        t.start()

    t = threading.Timer(5.0, check_scheduled_posts)
    t.daemon = True
    # Acquire lock before starting the background scheduler loop
    if acquire_scheduler_lock():
        t.start()
        print("[SCHEDULED] Background task started (checks every 30 seconds)")
    else:
        print("[SCHEDULED] Background task not started (lock not acquired).")
    # ensure lock removal on shutdown
    @app.on_event("shutdown")
    def _remove_scheduler_lock():
        try:
            if lock_path.exists():
                with open(lock_path, "r") as f:
                    pid = int(f.read().strip() or "0")
                if pid == os.getpid():
                    try:
                        os.remove(lock_path)
                    except Exception:
                        pass
        except Exception:
            pass
