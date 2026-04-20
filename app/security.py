"""
Güvenlik katmanı:
- Bcrypt ile parola hashleme/doğrulama
- JWT access/refresh token oluşturma ve doğrulama
- Fernet ile hassas verilerin simetrik şifrelenmesi (ör. Instagram access_token)

Tüm ortam değişkenleri `app.config` üzerinden geliyor. Üretim ortamında
`SECRET_KEY` ve `ENCRYPTION_KEY` mutlaka güçlü ve kalıcı olarak atanmalı.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ENCRYPTION_KEY,
    JWT_ALGORITHM,
    REFRESH_TOKEN_EXPIRE_DAYS,
    SECRET_KEY,
)

# --- Parola hashleme --------------------------------------------------------
#
# Passlib x bcrypt 5.x uyumsuzluğu nedeniyle doğrudan `bcrypt` paketini kullanıyoruz.
# Uzun parolalar için önce SHA-256 özeti alıp sonucu hex string (64 byte) olarak
# bcrypt'e veriyoruz → 72 byte sınırının altında kalır.


def _prehash(plain: str) -> bytes:
    if not isinstance(plain, str):
        raise TypeError("password must be a string")
    return hashlib.sha256(plain.encode("utf-8")).hexdigest().encode("ascii")


def hash_password(plain: str) -> str:
    pre = _prehash(plain)
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pre, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(_prehash(plain), hashed.encode("utf-8"))
    except Exception:
        return False


# --- JWT --------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> str:
    """Kısa ömürlü access token üretir. `sub` içinde user id (str) taşır."""
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": "access",
        "iat": int(_now_utc().timestamp()),
        "exp": int((_now_utc() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(subject: str | int) -> str:
    """Uzun ömürlü refresh token üretir."""
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": "refresh",
        "iat": int(_now_utc().timestamp()),
        "exp": int((_now_utc() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).timestamp()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    """Token doğrulanamazsa None döner (süre dolmuş / imzası hatalı vb.)."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


# --- Fernet simetrik şifreleme ---------------------------------------------

# Fernet 32 byte (44 karakter base64) anahtar bekler. Kullanıcı `.env` içine
# herhangi bir string koyabilsin diye SHA-256 üzerinden deterministik türetme
# yapıyoruz. Üretimde mutlaka `cryptography.fernet.Fernet.generate_key()`
# çıktısı kullanılmalı.
def _derive_fernet_key(raw: str) -> bytes:
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


_FERNET: Fernet | None = None


def _get_fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        raw = ENCRYPTION_KEY or SECRET_KEY or "autosocial-dev-insecure-key"
        _FERNET = Fernet(_derive_fernet_key(raw))
    return _FERNET


ENC_PREFIX = "enc::v1::"


def encrypt_secret(plain: str | None) -> str | None:
    """Düz metni Fernet ile şifreler ve `enc::v1::...` öneki ile döndürür.
    Boş değerler aynen döner (None → None, "" → "")."""
    if plain is None or plain == "":
        return plain
    if isinstance(plain, str) and plain.startswith(ENC_PREFIX):
        return plain
    token = _get_fernet().encrypt(plain.encode("utf-8"))
    return ENC_PREFIX + token.decode("utf-8")


def decrypt_secret(value: str | None) -> str | None:
    """Şifreliyse çözer; değilse aynen döndürür (geri uyumluluk için)."""
    if not value:
        return value
    if not isinstance(value, str) or not value.startswith(ENC_PREFIX):
        return value
    payload = value[len(ENC_PREFIX):].encode("utf-8")
    try:
        return _get_fernet().decrypt(payload).decode("utf-8")
    except InvalidToken:
        return None
    except Exception:
        return None


def mask_secret(value: str | None, visible: int = 4) -> str:
    """UI'da gösterim için son `visible` karakter dışındakileri maskeler."""
    if not value:
        return ""
    s = str(value)
    if len(s) <= visible:
        return "*" * len(s)
    return "*" * (len(s) - visible) + s[-visible:]


def generate_fresh_encryption_key() -> str:
    """Üretimde .env'e yazılacak rastgele, güçlü Fernet anahtarı üretir."""
    return Fernet.generate_key().decode("utf-8")


def ensure_env_secrets() -> None:
    """İlk çalıştırmada SECRET_KEY / ENCRYPTION_KEY boşsa süreç ömrü için
    güvenli değer üretir (memory'de), uyarı basar. `.env` dosyasına yazmaz;
    kalıcı değer kullanıcıya bırakılır."""
    if not SECRET_KEY:
        os.environ["SECRET_KEY"] = generate_fresh_encryption_key()
        print("[SECURITY] SECRET_KEY yok; geçici üretildi. Üretimde .env'e sabit değer koyun!")
    if not ENCRYPTION_KEY:
        os.environ["ENCRYPTION_KEY"] = generate_fresh_encryption_key()
        print("[SECURITY] ENCRYPTION_KEY yok; geçici üretildi. Üretimde .env'e sabit değer koyun!")
