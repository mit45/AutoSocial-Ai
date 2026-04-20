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
from app.api.auth import router as auth_router
from app.services.scheduler import daily_post_cycle
from app.database import SessionLocal, Base, engine
from app.models import Account, User, UserRole
from app.config import (
    OPENAI_API_KEY,
    BOOTSTRAP_ADMIN_EMAIL,
    BOOTSTRAP_ADMIN_PASSWORD,
)
from app.security import ensure_env_secrets, hash_password, encrypt_secret, ENC_PREFIX
from app.services.scheduler_api import run_scheduled_publish, run_automation_check
from app.services.analytics_service import refresh_pipeline, build_posts_for_feedback
from app.services.feedback_loop_engine import update_learning_state_from_posts
import threading
import os
import errno

# Süreç ömründe SECRET_KEY / ENCRYPTION_KEY eksikse geçici üret (uyarı basar).
ensure_env_secrets()

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


@app.get("/insights", include_in_schema=False)
def insights_page():
    """Instagram istatistikleri sayfası (yayınlanan içerikler, görüntülenme, beğeni, yorumlar)."""
    path = FRONTEND_DIR / "insights.html"
    if path.exists():
        return FileResponse(path)
    return RedirectResponse(url="/")


@app.get("/settings", include_in_schema=False)
def settings_page():
    """Sistem ayarları sayfası."""
    path = FRONTEND_DIR / "settings.html"
    if path.exists():
        return FileResponse(path)
    return RedirectResponse(url="/")


@app.get("/login", include_in_schema=False)
def login_page():
    path = FRONTEND_DIR / "login.html"
    if path.exists():
        return FileResponse(path)
    return RedirectResponse(url="/")


@app.get("/register", include_in_schema=False)
def register_page():
    path = FRONTEND_DIR / "register.html"
    if path.exists():
        return FileResponse(path)
    return RedirectResponse(url="/login")


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

    @app.get("/auth.js", include_in_schema=False)
    def serve_auth_js():
        return FileResponse(
            FRONTEND_DIR / "auth.js",
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

# Public auth endpoint'leri
app.include_router(auth_router, prefix="/api", tags=["Auth"])
# Diğer tüm /api/* endpoint'leri route'ların içindeki CurrentUser ile korunur.
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


def _run_auth_migrations() -> None:
    """
    Auth/multi-tenant geçişi için güvenli ALTER TABLE'lar:
    - users tablosunu oluştur
    - posts/accounts/automation_settings/caption_history'ye user_id kolonu ekle
    - audit_logs tablosunu oluştur
    - accounts.display_name, accounts.created_at varsa atla
    - Mevcut access_token'ları Fernet ile şifrele (prefix kontrolüyle idempotent)
    - .env BOOTSTRAP_ADMIN_* dolu ise ilk admin'i oluştur
    - Sahipsiz (user_id NULL) kayıtları en eski admin/kullanıcıya bağla
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        def _col_exists(table: str, col: str) -> bool:
            try:
                rows = conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall()
                return any(r[1] == col for r in rows)
            except Exception:
                return False

        def _add_col(table: str, ddl: str, col: str) -> None:
            if _col_exists(table, col):
                return
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                conn.commit()
                print(f"[MIGRATE] {table}.{col} eklendi")
            except Exception as e:
                print(f"[MIGRATE] {table}.{col} eklenemedi: {e}")

        # Yeni kolonlar
        _add_col("posts", "user_id INTEGER", "user_id")
        _add_col("accounts", "user_id INTEGER", "user_id")
        _add_col("accounts", "display_name VARCHAR", "display_name")
        _add_col("accounts", "created_at DATETIME", "created_at")
        _add_col("automation_settings", "user_id INTEGER", "user_id")
        _add_col("caption_history", "user_id INTEGER", "user_id")


def _bootstrap_admin_user() -> None:
    """
    .env'de BOOTSTRAP_ADMIN_EMAIL ve BOOTSTRAP_ADMIN_PASSWORD varsa ve DB'de
    hiç kullanıcı yoksa, otomatik admin oluşturur. Tek kullanımlık kolaylık:
    üretimde kayıt formundan ilk kullanıcı açıldığında rolü otomatik admin olur.
    """
    if not (BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD):
        return
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return
        user = User(
            email=BOOTSTRAP_ADMIN_EMAIL.lower().strip(),
            hashed_password=hash_password(BOOTSTRAP_ADMIN_PASSWORD),
            full_name="Bootstrap Admin",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(user)
        db.commit()
        print(f"[BOOTSTRAP] Admin kullanıcı oluşturuldu: {user.email}")
    except Exception as e:
        print(f"[BOOTSTRAP] Admin oluşturma hatası: {e}")
        db.rollback()
    finally:
        db.close()


def _claim_orphan_rows_for_first_user() -> None:
    """
    Eski kurulumdan gelen user_id=NULL kayıtları ilk admin kullanıcıya bağlar.
    Böylece single-user modunda çalışan mevcut veri kaybolmaz.
    """
    db = SessionLocal()
    try:
        owner = (
            db.query(User)
            .filter(User.is_active == True)  # noqa: E712
            .order_by(User.role.desc(), User.id.asc())
            .first()
        )
        if not owner:
            return
        from sqlalchemy import text as _text
        for table in ("posts", "accounts", "automation_settings", "caption_history"):
            try:
                db.execute(
                    _text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),
                    {"uid": owner.id},
                )
            except Exception as e:
                print(f"[MIGRATE] {table}.user_id backfill hatası: {e}")
        db.commit()
    except Exception as e:
        print(f"[MIGRATE] Orphan claim hatası: {e}")
        db.rollback()
    finally:
        db.close()


def _encrypt_plain_access_tokens() -> None:
    """Mevcut `accounts.access_token` değerleri düz metin ise Fernet ile şifreler."""
    db = SessionLocal()
    try:
        accounts = db.query(Account).all()
        changed = 0
        for a in accounts:
            tok = str(a.access_token or "")
            if tok and not tok.startswith(ENC_PREFIX):
                enc = encrypt_secret(tok)
                if enc and enc != tok:
                    a.access_token = enc  # type: ignore[assignment]
                    changed += 1
        if changed:
            db.commit()
            print(f"[MIGRATE] {changed} hesabın access_token alanı şifrelendi.")
    except Exception as e:
        print(f"[MIGRATE] access_token şifreleme hatası: {e}")
        db.rollback()
    finally:
        db.close()


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
                # automation_runs: one row per (setting, local day, slot_key) for multiple daily times
                try:
                    conn.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS automation_runs (id INTEGER PRIMARY KEY, setting_id INTEGER NOT NULL, run_date VARCHAR NOT NULL, slot_key VARCHAR NOT NULL DEFAULT '', created_at DATETIME, UNIQUE(setting_id, run_date, slot_key))"
                        )
                    )
                    conn.commit()
                except Exception as e:
                    print(f"[MIGRATE] Failed to ensure automation_runs table: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                # Legacy DBs: table exists but no slot_key (or failed mig left automation_runs_mig behind)
                try:
                    ar_rows = conn.execute(text("PRAGMA table_info('automation_runs')")).fetchall()
                    ar_cols = [row[1] for row in ar_rows] if ar_rows else []
                    if ar_cols and "slot_key" not in ar_cols:
                        conn.execute(text("DROP TABLE IF EXISTS automation_runs_mig"))
                        conn.execute(
                            text(
                                "CREATE TABLE automation_runs_mig (id INTEGER PRIMARY KEY, setting_id INTEGER NOT NULL, run_date VARCHAR NOT NULL, slot_key VARCHAR NOT NULL DEFAULT '', created_at DATETIME, UNIQUE(setting_id, run_date, slot_key))"
                            )
                        )
                        # Legacy DBs often have many rows per (setting_id, run_date); empty slot_key
                        # would violate UNIQUE(setting_id, run_date, slot_key). One stable key per row.
                        conn.execute(
                            text(
                                "INSERT INTO automation_runs_mig (id, setting_id, run_date, slot_key, created_at) "
                                "SELECT id, setting_id, run_date, '__legacy__' || CAST(id AS TEXT), created_at FROM automation_runs"
                            )
                        )
                        conn.execute(text("DROP TABLE automation_runs"))
                        conn.execute(text("ALTER TABLE automation_runs_mig RENAME TO automation_runs"))
                        conn.commit()
                        print("[MIGRATE] automation_runs: added slot_key for multi-slot daily automation")
                except Exception as e:
                    print(f"[MIGRATE] automation_runs slot_key migration: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
        except Exception as me:
            print(f"[MIGRATE] Migration check failed: {me}")

        # --- Auth & multi-tenant migration'ları ---
        try:
            _run_auth_migrations()
        except Exception as e:
            print(f"[MIGRATE] Auth migrations failed: {e}")
        try:
            _bootstrap_admin_user()
        except Exception as e:
            print(f"[BOOTSTRAP] failed: {e}")
        try:
            _claim_orphan_rows_for_first_user()
        except Exception as e:
            print(f"[MIGRATE] orphan claim failed: {e}")
        try:
            _encrypt_plain_access_tokens()
        except Exception as e:
            print(f"[MIGRATE] access_token encryption failed: {e}")

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

    def refresh_instagram_analytics():
        """
        Background job: her saatte bir Instagram analytics pipeline'ını ve öğrenme durumunu günceller.
        """
        try:
            db = SessionLocal()
            try:
                account = db.query(Account).first()
                if not account:
                    return
                ig_user_id = str(account.ig_user_id) if account.ig_user_id else ""
                from app.security import decrypt_secret
                raw_token = os.getenv("INSTAGRAM_ACCESS_TOKEN") or decrypt_secret(str(account.access_token or ""))
                access_token = str(raw_token) if raw_token else None
                if not access_token or not ig_user_id:
                    print("[ANALYTICS] Instagram token veya kullanıcı ID eksik; analytics refresh atlandı.")
                    return

                # 1) Pipeline: medya + insights cache'ini güncelle
                try:
                    stats = refresh_pipeline(ig_user_id, access_token, full_sync=False)
                    print(f"[ANALYTICS] Pipeline refresh: {stats}")
                except Exception as e:
                    print(f"[ANALYTICS] refresh_pipeline error: {e}")

                # 2) Feedback loop: cached veriden öğrenme durumunu güncelle
                try:
                    posts = build_posts_for_feedback()
                    if posts:
                        learned = update_learning_state_from_posts(posts)
                        print(f"[ANALYTICS] Learning update: posts={len(posts)} state_meta={learned.get('learning_state', {}).get('meta')}")
                except Exception as e:
                    print(f"[ANALYTICS] feedback update error: {e}")
            finally:
                db.close()
        except Exception as e:
            import traceback

            print(f"[ANALYTICS] Background analytics error: {e}")
            print(traceback.format_exc())

        t = threading.Timer(3600.0, refresh_instagram_analytics)
        t.daemon = True
        t.start()

    scheduler_timer = threading.Timer(5.0, check_scheduled_posts)
    scheduler_timer.daemon = True
    analytics_timer = threading.Timer(10.0, refresh_instagram_analytics)
    analytics_timer.daemon = True
    # Acquire lock before starting the background scheduler/analytics loops
    if acquire_scheduler_lock():
        scheduler_timer.start()
        analytics_timer.start()
        print("[SCHEDULED] Background task started (checks every 30 seconds)")
        print("[ANALYTICS] Background analytics started (runs every 3600 seconds)")
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
