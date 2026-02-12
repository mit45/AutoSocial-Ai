from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Force using SQLite for this deployment - never attempt PostgreSQL connections.
# This avoids startup delays and external dependency requirements.
_effective_url = "sqlite:///./autosocial.db"

connect_args = {"check_same_thread": False}

engine = create_engine(_effective_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """
    FastAPI dependency: her istek icin bir DB session olusturur
    ve is bitince otomatik kapatir.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
