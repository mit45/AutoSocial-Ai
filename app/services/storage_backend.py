"""Unified storage backend combining R2 and legacy upload methods.

Provides a single API used by the rest of the app:
- upload_bytes(png_bytes, filename, prefix) -> public_url
- delete_key(key) -> bool
- url_for_key(key) -> str
- generate_presigned_get_from_url(image_url, expires=300) -> Optional[str]
- upload_to_remote_server(png_bytes, filename, prefix) -> public_url
- save_png_bytes_to_generated(png_bytes) -> (relative_path, public_url)
- delete_remote_file(image_url) -> bool
"""
from __future__ import annotations
import mimetypes
import requests
from pathlib import Path, PurePosixPath
from uuid import uuid4
from typing import Optional

from app.config import (
    R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_BUCKET_NAME,
    R2_PUBLIC_BASE_URL,
    UPLOAD_BASE_URL,
    UPLOAD_API_URL,
    UPLOAD_API_KEY,
    FTP_HOST,
    FTP_USER,
    FTP_PASSWORD,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = BASE_DIR / "storage" / "generated"


def ensure_storage_dir() -> Path:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return STORAGE_DIR


def _get_s3_client():
    if not (R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME):
        return None
    import boto3
    from botocore.config import Config

    endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    cfg = Config(signature_version="s3v4", s3={"addressing_style": "virtual"})
    return boto3.client(
        "s3",
        region_name="auto",
        endpoint_url=endpoint,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=cfg,
    )


def url_for_key(key: str) -> str:
    if R2_PUBLIC_BASE_URL:
        return f"{R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"
    return f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/{R2_BUCKET_NAME}/{key}"


def generate_presigned_get_from_key(key: str, expires: int = 300) -> str:
    client = _get_s3_client()
    if not client:
        raise RuntimeError("R2 configuration missing")
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": R2_BUCKET_NAME, "Key": key},
        ExpiresIn=int(expires),
    )


def generate_presigned_get_from_url(image_url: str, expires: int = 300) -> Optional[str]:
    if not image_url or not isinstance(image_url, str):
        return None
    try:
        if R2_PUBLIC_BASE_URL and R2_PUBLIC_BASE_URL.rstrip("/") in image_url:
            key = image_url.split(R2_PUBLIC_BASE_URL.rstrip("/"))[-1].lstrip("/")
            if key:
                return generate_presigned_get_from_key(key, expires=expires)
        host_marker = f"{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        if host_marker in image_url:
            parts = image_url.split(host_marker)[-1].lstrip("/").split("/", 1)
            if len(parts) >= 2:
                key = parts[1]
            else:
                key = parts[-1]
            if key:
                return generate_presigned_get_from_key(key, expires=expires)
    except Exception:
        return None
    return None


def upload_bytes(png_bytes: bytes, filename: str, prefix: str = "ig/post") -> str:
    client = _get_s3_client()
    if not client:
        raise RuntimeError("R2 configuration missing")
    key = str(PurePosixPath(prefix) / filename)
    content_type, _ = mimetypes.guess_type(filename)
    if not content_type:
        content_type = "application/octet-stream"
    client.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=key,
        Body=png_bytes,
        ContentType=content_type,
        CacheControl="public, max-age=31536000",
    )
    return url_for_key(key)


def delete_key(key: str) -> bool:
    client = _get_s3_client()
    if not client:
        return False
    try:
        client.delete_object(Bucket=R2_BUCKET_NAME, Key=key)
        return True
    except Exception:
        return False


def upload_to_remote_server(png_bytes: bytes, filename: str, prefix: str = "ig/post") -> str:
    # Try R2 first
    if R2_ACCOUNT_ID and R2_BUCKET_NAME:
        try:
            return upload_bytes(png_bytes, filename, prefix=prefix)
        except Exception:
            pass

    # Try HTTP API
    if UPLOAD_API_URL and UPLOAD_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {UPLOAD_API_KEY}"} if UPLOAD_API_KEY else {}
            files = {"file": (filename, png_bytes, "image/png")}
            data = {"path": "ig", "filename": filename}
            resp = requests.post(UPLOAD_API_URL, files=files, data=data, headers=headers, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            if isinstance(result, dict) and "url" in result:
                return result["url"]
            if isinstance(result, dict) and "file_url" in result:
                return result["file_url"]
            if isinstance(result, str):
                return result
        except Exception:
            pass

    # Try FTP
    if FTP_HOST and FTP_USER and FTP_PASSWORD:
        try:
            from ftplib import FTP
            from io import BytesIO
            ftp = FTP(FTP_HOST)
            ftp.login(FTP_USER, FTP_PASSWORD)
            try:
                ftp.cwd("public_html")
            except Exception:
                try:
                    ftp.cwd("www")
                except Exception:
                    pass
            try:
                ftp.cwd("uploads")
            except Exception:
                try:
                    ftp.mkd("uploads")
                    ftp.cwd("uploads")
                except Exception:
                    pass
            try:
                ftp.cwd("ig")
            except Exception:
                try:
                    ftp.mkd("ig")
                    ftp.cwd("ig")
                except Exception:
                    pass
            file_obj = BytesIO(png_bytes)
            ftp.storbinary(f"STOR {filename}", file_obj)
            ftp.quit()
            return f"{UPLOAD_BASE_URL.rstrip('/')}/{filename}"
        except Exception:
            pass

    # Fallback: save locally and return a URL-ish path
    ensure_storage_dir()
    file_path = STORAGE_DIR / filename
    with open(file_path, "wb") as f:
        f.write(png_bytes)
    return f"{UPLOAD_BASE_URL.rstrip('/')}/{filename}"


def save_png_bytes_to_generated(png_bytes: bytes) -> tuple[str, str]:
    ensure_storage_dir()
    filename = f"{uuid4()}.png"
    file_path = STORAGE_DIR / filename
    with open(file_path, "wb") as f:
        f.write(png_bytes)
    relative_path = f"generated/{filename}"
    try:
        public_url = upload_to_remote_server(png_bytes, filename, prefix="ig/post")
    except Exception:
        public_url = f"/static/{relative_path}"
    return relative_path, public_url


def delete_remote_file(image_url: str) -> bool:
    if not image_url:
        return False
    filename = None
    try:
        if isinstance(image_url, str) and "uploads/ig/" in image_url:
            filename = image_url.rstrip("/").split("/")[-1]
        else:
            filename = str(image_url).rstrip("/").split("/")[-1]
    except Exception:
        filename = None

    # Try HTTP API delete
    if UPLOAD_API_URL and UPLOAD_API_KEY and filename:
        try:
            headers = {"Authorization": f"Bearer {UPLOAD_API_KEY}", "Accept": "application/json"}
            resp = requests.delete(UPLOAD_API_URL, params={"path": "ig", "filename": filename}, headers=headers, timeout=20)
            if resp.status_code in (200, 204):
                return True
            try:
                resp = requests.delete(UPLOAD_API_URL, json={"path": "ig", "filename": filename}, headers=headers, timeout=20)
                if resp.status_code in (200, 204):
                    return True
            except Exception:
                pass
        except Exception:
            pass

    # Try FTP delete
    if FTP_HOST and FTP_USER and FTP_PASSWORD and filename:
        try:
            from ftplib import FTP
            ftp = FTP(FTP_HOST)
            ftp.login(FTP_USER, FTP_PASSWORD)
            try:
                ftp.cwd("public_html")
            except Exception:
                try:
                    ftp.cwd("www")
                except Exception:
                    pass
            try:
                ftp.cwd("uploads")
            except Exception:
                try:
                    ftp.mkd("uploads")
                    ftp.cwd("uploads")
                except Exception:
                    pass
            try:
                ftp.cwd("ig")
            except Exception:
                try:
                    ftp.mkd("ig")
                    ftp.cwd("ig")
                except Exception:
                    pass
            try:
                ftp.delete(filename)
                ftp.quit()
                return True
            except Exception:
                try:
                    ftp.quit()
                except Exception:
                    pass
        except Exception:
            pass

    # Try R2 delete
    try:
        if R2_ACCOUNT_ID and R2_BUCKET_NAME:
            if R2_PUBLIC_BASE_URL and isinstance(image_url, str) and R2_PUBLIC_BASE_URL in image_url:
                key = image_url.split(R2_PUBLIC_BASE_URL.rstrip("/"))[-1].lstrip("/")
                if key:
                    return delete_key(key)
            host_marker = f"{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
            if isinstance(image_url, str) and host_marker in image_url:
                parts = image_url.split(host_marker)[-1].lstrip("/").split("/", 2)
                if len(parts) >= 2:
                    key = "/".join(parts[1:]) if len(parts) > 1 else parts[-1]
                    return delete_key(key)
    except Exception:
        pass
    return False

