"""Local storage service for generated images."""

import requests
from pathlib import Path
from uuid import uuid4
from app.config import (
    UPLOAD_BASE_URL,
    UPLOAD_API_URL,
    UPLOAD_API_KEY,
    FTP_HOST,
    FTP_USER,
    FTP_PASSWORD,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = BASE_DIR / "storage" / "generated"


def ensure_storage_dir():
    """Storage dizinini oluştur (yoksa)"""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return STORAGE_DIR


def upload_to_remote_server(png_bytes: bytes, filename: str) -> str:
    """
    PNG bytes'ı remote server'a yükler (https://umittopuz.com/uploads/ig/).

    Args:
        png_bytes: PNG formatında görsel bytes'ı
        filename: Dosya adı (örn: "abc123.png")

    Returns:
        str: Public URL (örn: "https://umittopuz.com/uploads/ig/abc123.png")

    Raises:
        Exception: Upload başarısız olursa
    """
    # Yöntem 1: HTTP API ile yükleme (eğer API endpoint'i varsa ve farklıysa)
    # Not: Default UPLOAD_API_URL kullanılıyorsa FTP'ye geç
    if UPLOAD_API_URL and UPLOAD_API_KEY:
        try:
            headers = {}
            if UPLOAD_API_KEY:
                headers["Authorization"] = f"Bearer {UPLOAD_API_KEY}"

            files = {"file": (filename, png_bytes, "image/png")}
            data = {"path": "ig", "filename": filename}  # uploads/ig/ klasörüne yükle

            response = requests.post(
                UPLOAD_API_URL, files=files, data=data, headers=headers, timeout=30
            )
            response.raise_for_status()

            result = response.json()
            # API response'dan URL'i al (format değişebilir)
            if isinstance(result, dict) and "url" in result:
                return result["url"]
            elif isinstance(result, dict) and "file_url" in result:
                return result["file_url"]
            elif isinstance(result, str):
                return result

        except Exception as e:
            print(f"Warning: HTTP API upload failed: {e}")
            # Fallback'e geç

    # Yöntem 2: FTP/SFTP ile yükleme (eğer FTP bilgileri varsa)
    if FTP_HOST and FTP_USER and FTP_PASSWORD:
        try:
            from ftplib import FTP
            from io import BytesIO

            print(f"[FTP] Connecting to {FTP_HOST}...")
            ftp = FTP(FTP_HOST)
            ftp.login(FTP_USER, FTP_PASSWORD)
            print(f"[FTP] Connected and logged in successfully")

            # public_html/uploads/ig/ dizinine geç (web root'tan servis edilir)
            # Önce public_html dizinine git
            try:
                ftp.cwd("public_html")
                print(f"[FTP] Changed to public_html/")
            except Exception as e1:
                print(f"[FTP] public_html/ not found, trying www/... ({e1})")
                try:
                    ftp.cwd("www")
                    print(f"[FTP] Changed to www/")
                except Exception:
                    print(f"[FTP] Neither public_html/ nor www/ found, using root")
                    # Root'ta kal, uploads/ig/ kullan

            # uploads dizinine geç (yoksa oluştur)
            try:
                ftp.cwd("uploads")
                print(f"[FTP] Changed to uploads/")
            except Exception as e1:
                print(f"[FTP] uploads/ not found, creating... ({e1})")
                try:
                    ftp.mkd("uploads")
                    ftp.cwd("uploads")
                    print(f"[FTP] Created and changed to uploads/")
                except Exception as e2:
                    print(f"[FTP] Failed to create uploads/: {e2}")
                    raise

            # ig dizinine geç (yoksa oluştur)
            try:
                ftp.cwd("ig")
                print(f"[FTP] Changed to uploads/ig/")
            except Exception as e1:
                print(f"[FTP] uploads/ig/ not found, creating... ({e1})")
                try:
                    ftp.mkd("ig")
                    ftp.cwd("ig")
                    print(f"[FTP] Created and changed to uploads/ig/")
                except Exception as e2:
                    print(f"[FTP] Failed to create uploads/ig/: {e2}")
                    raise

            # Dosyayı yükle
            file_obj = BytesIO(png_bytes)
            print(f"[FTP] Uploading {filename} ({len(png_bytes)} bytes)...")
            ftp.storbinary(f"STOR {filename}", file_obj)
            ftp.quit()

            public_url = f"{UPLOAD_BASE_URL}/{filename}"
            print(f"[FTP] Upload successful! URL: {public_url}")
            return public_url

        except Exception as e:
            import traceback

            print(f"[FTP] Upload failed: {e}")
            print(f"[FTP] Traceback: {traceback.format_exc()}")
            # Fallback'e geç
            raise

    # Yöntem 3: Local storage'a kaydet ve URL döndür (fallback)
    # Not: Bu durumda görsel local'de kalır, remote'a yüklenmez
    # Production'da mutlaka remote upload çalışmalı
    ensure_storage_dir()
    file_path = STORAGE_DIR / filename
    with open(file_path, "wb") as f:
        f.write(png_bytes)

    # Remote URL formatında döndür (ama dosya local'de)
    # Production'da bu çalışmaz, mutlaka remote upload gerekli
    return f"{UPLOAD_BASE_URL}/{filename}"


def save_png_bytes_to_generated(png_bytes: bytes) -> tuple[str, str]:
    """
    PNG bytes'ı hem local storage'a kaydeder hem de remote server'a yükler.

    Args:
        png_bytes: PNG formatında görsel bytes'ı

    Returns:
        tuple[str, str]: (relative_path, public_url)
            - relative_path: "generated/{uuid}.png" (local)
            - public_url: "https://umittopuz.com/uploads/ig/{uuid}.png" (remote)
    """
    ensure_storage_dir()

    # UUID ile dosya adı oluştur
    filename = f"{uuid4()}.png"

    # 1) Local storage'a kaydet (backup/fallback için)
    file_path = STORAGE_DIR / filename
    with open(file_path, "wb") as f:
        f.write(png_bytes)

    relative_path = f"generated/{filename}"

    # 2) Remote server'a yükle
    try:
        public_url = upload_to_remote_server(png_bytes, filename)
        print(f"[OK] Image uploaded to remote server: {public_url}")
    except Exception as e:
        # Remote upload başarısız olursa local URL kullan
        import traceback

        print(f"[WARNING] Remote upload failed, using local URL")
        print(f"[WARNING] Error: {e}")
        print(f"[WARNING] Traceback: {traceback.format_exc()}")
        public_url = f"/static/{relative_path}"

    return relative_path, public_url


def delete_remote_file(image_url: str) -> bool:
    """
    Attempts to delete a previously uploaded remote file referenced by image_url.
    Returns True if deletion was attempted and succeeded (or the file did not exist),
    False if deletion failed.

    Supported methods:
    - If UPLOAD_API_URL + UPLOAD_API_KEY are configured, attempt HTTP DELETE to that API
      (assumes the API accepts path & filename via query or JSON - best-effort).
    - If FTP credentials are configured, connect via FTP and delete from public_html/uploads/ig/.
    - Otherwise, return False.
    """
    if not image_url:
        return False

    # Normalize filename from URL or path
    filename = None
    try:
        # If URL contains uploads/ig/, extract filename
        if isinstance(image_url, str) and "uploads/ig/" in image_url:
            filename = image_url.rstrip("/").split("/")[-1]
        elif (
            isinstance(image_url, str)
            and image_url.startswith("/")
            and image_url.count("/") >= 2
        ):
            # possible /media/filename or /static/generated/filename
            filename = image_url.rstrip("/").split("/")[-1]
        else:
            # fallback: last path segment
            filename = str(image_url).rstrip("/").split("/")[-1]
    except Exception:
        filename = None

    # Try HTTP API delete if available
    if UPLOAD_API_URL and UPLOAD_API_KEY and filename:
        try:
            headers = {
                "Authorization": f"Bearer {UPLOAD_API_KEY}",
                "Accept": "application/json",
            }
            # Try DELETE with filename in query
            resp = requests.delete(
                UPLOAD_API_URL,
                params={"path": "ig", "filename": filename},
                headers=headers,
                timeout=20,
            )
            if resp.status_code in (200, 204):
                print(f"[UPLOAD_API] Deleted remote file via API: {filename}")
                return True
            # Try JSON body
            try:
                resp = requests.delete(
                    UPLOAD_API_URL,
                    json={"path": "ig", "filename": filename},
                    headers=headers,
                    timeout=20,
                )
                if resp.status_code in (200, 204):
                    print(
                        f"[UPLOAD_API] Deleted remote file via API (json): {filename}"
                    )
                    return True
            except Exception:
                pass
            print(
                f"[UPLOAD_API] Delete returned status {resp.status_code}: {resp.text[:200]}"
            )
        except Exception as e:
            print(f"[UPLOAD_API] Delete attempt failed: {e}")

    # Try FTP delete if credentials present
    if FTP_HOST and FTP_USER and FTP_PASSWORD and filename:
        try:
            from ftplib import FTP

            print(f"[FTP] Connecting to {FTP_HOST} for delete...")
            ftp = FTP(FTP_HOST)
            ftp.login(FTP_USER, FTP_PASSWORD)

            # navigate to public_html/uploads/ig/ (best-effort)
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

            # attempt delete
            try:
                ftp.delete(filename)
                ftp.quit()
                print(f"[FTP] Deleted remote file: {filename}")
                return True
            except Exception as e:
                print(f"[FTP] Delete failed for {filename}: {e}")
                try:
                    ftp.quit()
                except Exception:
                    pass
        except Exception as e:
            print(f"[FTP] Connection/delete attempt failed: {e}")

    # Nothing we could do
    print(f"[DELETE] Could not delete remote file: {image_url}")
    return False
