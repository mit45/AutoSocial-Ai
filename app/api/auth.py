"""
Kimlik doğrulama endpoint'leri:
- POST /api/auth/register
- POST /api/auth/login
- POST /api/auth/refresh
- GET  /api/auth/me
- POST /api/auth/change-password
- POST /api/auth/logout  (istemci tarafında token'ı silmek için bilgilendirici)
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.config import ACCESS_TOKEN_EXPIRE_MINUTES
from app.database import get_db
from app.models import User, UserRole
from app.schemas import (
    PasswordChange,
    TokenPair,
    TokenRefresh,
    UserLogin,
    UserRead,
    UserRegister,
)
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _make_token_pair(user: User) -> TokenPair:
    uid = int(user.id)  # type: ignore[arg-type]
    return TokenPair(
        access_token=create_access_token(uid),
        refresh_token=create_refresh_token(uid),
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)) -> TokenPair:
    email = payload.email.lower().strip()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bu e-posta ile zaten kayıt var.")
    # Sistemdeki ilk kullanıcı otomatik admin olur.
    is_first = db.query(User).count() == 0
    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=(payload.full_name or None),
        role=UserRole.ADMIN if is_first else UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _make_token_pair(user)


@router.post("/login", response_model=TokenPair)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> TokenPair:
    email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(payload.password, str(user.hashed_password or "")):
        raise HTTPException(status_code=401, detail="E-posta veya parola hatalı.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Hesap pasif.")
    user.last_login_at = datetime.utcnow()
    db.commit()
    return _make_token_pair(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: TokenRefresh, db: Session = Depends(get_db)) -> TokenPair:
    data = decode_token(payload.refresh_token)
    if not data or data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Refresh token geçersiz.")
    try:
        sub_raw = data.get("sub") if data else None
        user_id = int(sub_raw) if sub_raw is not None else 0
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh token geçersiz.")
    if not user_id:
        raise HTTPException(status_code=401, detail="Refresh token geçersiz.")
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı.")
    return _make_token_pair(user)


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.post("/change-password")
def change_password(
    payload: PasswordChange,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(payload.old_password, str(user.hashed_password or "")):
        raise HTTPException(status_code=400, detail="Mevcut parola hatalı.")
    user.hashed_password = hash_password(payload.new_password)
    user.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True}


@router.post("/logout")
def logout(_: CurrentUser) -> dict:
    # Stateless JWT: sunucu tarafında iptal listesi tutmuyoruz.
    # İstemci sadece token'ı siler. (İleride blacklist tablosu eklenebilir.)
    return {"success": True}
