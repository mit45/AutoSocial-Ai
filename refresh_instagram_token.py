"""Instagram access token yenileme script'i"""

import os
import requests
from dotenv import load_dotenv
from pathlib import Path

# Load .env
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID")
INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")

print("Instagram Access Token Yenileme")
print("=" * 50)
print(f"\nApp ID: {INSTAGRAM_APP_ID}")
print(
    f"Current Token: {INSTAGRAM_ACCESS_TOKEN[:30]}..."
    if INSTAGRAM_ACCESS_TOKEN
    else "None"
)

# Yöntem 1: Token'ı yenile (eğer henüz süresi dolmadıysa)
if INSTAGRAM_ACCESS_TOKEN:
    print("\n[1] Mevcut token'ı yenilemeyi deniyoruz...")
    refresh_url = "https://graph.instagram.com/refresh_access_token"
    params = {"grant_type": "ig_refresh_token", "access_token": INSTAGRAM_ACCESS_TOKEN}

    response = requests.get(refresh_url, params=params)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")

    if response.status_code == 200:
        data = response.json()
        new_token = data.get("access_token")
        expires_in = data.get("expires_in")
        print(f"\n[OK] Token yenilendi!")
        print(f"New Token: {new_token}")
        print(f"Expires in: {expires_in} seconds ({expires_in // 86400} days)")
        print(f"\n.env dosyasına ekle:")
        print(f"INSTAGRAM_ACCESS_TOKEN={new_token}")
    else:
        print(f"\n[INFO] Token yenilenemedi (muhtemelen süresi dolmuş)")
        print("Yeni token almak için aşağıdaki adımları izleyin:")

# Yöntem 2: Yeni token alma talimatları
print("\n" + "=" * 50)
print("[2] Yeni Long-Lived Token Alma Talimatları:")
print("=" * 50)
print(
    """
1. Facebook Developer Console'a git:
   https://developers.facebook.com/apps/

2. Uygulamanı seç (App ID: {app_id})

3. Tools > Graph API Explorer'a git:
   https://developers.facebook.com/tools/explorer/

4. Aşağıdaki ayarları yap:
   - User or Page: Instagram Business Account'ını seç
   - Permissions: instagram_business_basic, instagram_business_content_publish ekle
   - Generate Access Token'a tıkla

5. Kısa ömürlü token'ı uzun ömürlüye çevir:
   Aşağıdaki URL'yi tarayıcıda aç (SHORT_LIVED_TOKEN yerine yukarıdaki token'ı yapıştır):
   
   https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token&client_id={app_id}&client_secret={app_secret}&fb_exchange_token=SHORT_LIVED_TOKEN

6. Dönen 'access_token' değerini .env dosyasındaki INSTAGRAM_ACCESS_TOKEN'a yapıştır.

6a. Code 101 / "Error validating application" aliyorsaniz:
   - developers.facebook.com/apps -> Uygulamanizi acin, durumun "Aktif" oldugunu kontrol edin
   - Ayarlar -> Temel -> Uygulama Kimligi ve Uygulama Gizi'ni TEKRAR kopyalayip .env'e yapistirin (bosluk kalmasin)
   - Bazen Meta tarafinda gecici hata olur; 1-2 saat sonra tekrar deneyin

Alternatif: Bu script'i calistir ve kisa omurlu token'i ver:
   python refresh_instagram_token.py KISA_OMURLU_TOKEN
""".format(
        app_id=INSTAGRAM_APP_ID, app_secret=INSTAGRAM_APP_SECRET
    )
)


# Kısa ömürlü token'ı uzun ömürlüye çevirme fonksiyonu
def exchange_short_lived_token(short_token):
    """Kısa ömürlü token'ı uzun ömürlüye çevir"""
    exchange_url = f"https://graph.facebook.com/v19.0/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": INSTAGRAM_APP_ID,
        "client_secret": INSTAGRAM_APP_SECRET,
        "fb_exchange_token": short_token,
    }

    response = requests.get(exchange_url, params=params)
    if response.status_code == 200:
        data = response.json()
        long_token = data.get("access_token")
        expires_in = data.get("expires_in")
        print(f"\n[OK] Long-lived token alındı!")
        print(f"Token: {long_token}")
        print(f"Expires in: {expires_in} seconds ({expires_in // 86400} days)")
        return long_token
    else:
        print(f"\n[ERROR] Token exchange failed: {response.text}")
        return None


# Eğer komut satırından token verilirse
import sys

if len(sys.argv) > 1:
    short_token = sys.argv[1]
    print(f"\nKısa ömürlü token alınıyor: {short_token[:30]}...")
    long_token = exchange_short_lived_token(short_token)
    if long_token:
        print(f"\n.env dosyasına ekle:")
        print(f"INSTAGRAM_ACCESS_TOKEN={long_token}")
