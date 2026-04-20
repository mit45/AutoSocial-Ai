"""
FastAPI dependency'leri: mevcut kullanıcıyı JWT'den çözüp döndürür.

Kullanım:

    from app.api.deps import CurrentUser

    @router.get("/me")
    def me(user: CurrentUser):
        return {"id": user.id, "email": user.email}

AUTH_REQUIRED=0 ise dev modunda ilk (veya default) kullanıcıyı döndürür.
Bu sayede mevcut panel akışı kırılmadan geçiş yapılabilir.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import AUTH_REQUIRED
from app.database import get_db
from app.models import User, UserRole
from app.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def _extract_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    """Authorization header veya (fallback) `access_token` cookie'sinden token çıkar."""
    if credentials and credentials.scheme.lower() == "bearer" and credentials.credentials:
        return credentials.credentials
    cookie_tok = request.cookies.get("access_token") if request else None
    if cookie_tok:
        return cookie_tok
    return None


def get_current_user(
    request: Request,
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)] = None,
    db: Session = Depends(get_db),
) -> User:
    """Geçerli JWT'den kullanıcıyı döner. Yoksa 401.

    Geliştirme modunda (AUTH_REQUIRED=0) ilk aktif kullanıcı döner; hiç kullanıcı
    yoksa 401 fırlatılır (en az bir kullanıcı oluşturulmalı).
    """
    token = _extract_token(request, credentials)

    if not token:
        if not AUTH_REQUIRED:
            user = db.query(User).filter(User.is_active == True).order_by(User.id.asc()).first()  # noqa: E712
            if user:
                return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturum gerekli. Lütfen giriş yapın.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz veya süresi dolmuş token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sub = payload.get("sub")
    try:
        user_id = int(sub) if sub is not None else None
    except (TypeError, ValueError):
        user_id = None
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token geçersiz.")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı bulunamadı veya pasif.",
        )
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için admin yetkisi gerekli.",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
