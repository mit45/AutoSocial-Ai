"""
Kısa ömürlü Instagram/Facebook token'ı uzun ömürlü (long-lived) token'a çevirir
ve .env içindeki INSTAGRAM_ACCESS_TOKEN değerini günceller.

Kullanım: python tools/exchange_instagram_token.py "SHORT_LIVED_TOKEN"
"""
import os
import sys
from pathlib import Path

# Proje kökü
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def main():
    short_token = (sys.argv[1] or "").strip()
    if not short_token:
        print("Kullanım: python tools/exchange_instagram_token.py \"SHORT_LIVED_TOKEN\"")
        sys.exit(1)

    env_path = ROOT / ".env"
    if not env_path.exists():
        print(".env bulunamadı:", env_path)
        sys.exit(1)

    # .env'den app id ve secret oku
    load_dotenv = None
    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    if load_dotenv:
        load_dotenv(dotenv_path=env_path)
    app_id = os.getenv("INSTAGRAM_APP_ID") or os.getenv("FACEBOOK_APP_ID")
    app_secret = os.getenv("INSTAGRAM_APP_SECRET") or os.getenv("FACEBOOK_APP_SECRET")
    if not app_id or not app_secret:
        # .env dosyasını satır satır oku
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("INSTAGRAM_APP_ID="):
                app_id = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.strip().startswith("INSTAGRAM_APP_SECRET="):
                app_secret = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not app_id or not app_secret:
        print("INSTAGRAM_APP_ID ve INSTAGRAM_APP_SECRET .env içinde tanımlı olmalı.")
        sys.exit(1)

    import requests
    url = "https://graph.facebook.com/v19.0/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    }
    r = requests.get(url, params=params, timeout=30)
    data = r.json()
    if "error" in data:
        print("Token değişim hatası:", data["error"].get("message", data))
        sys.exit(1)
    long_token = data.get("access_token")
    if not long_token:
        print("Yanıtta access_token bulunamadı:", data)
        sys.exit(1)
    print("Uzun ömürlü token alındı (yaklaşık 60 gün geçerli).")

    # .env dosyasını güncelle: INSTAGRAM_ACCESS_TOKEN= satırını yeni token ile değiştir
    lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    new_line = "INSTAGRAM_ACCESS_TOKEN=" + long_token
    updated = False
    out = []
    for line in lines:
        if line.strip().startswith("INSTAGRAM_ACCESS_TOKEN="):
            out.append(new_line)
            updated = True
        else:
            out.append(line)
    if not updated:
        out.append(new_line)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(".env içindeki INSTAGRAM_ACCESS_TOKEN güncellendi.")

if __name__ == "__main__":
    main()
