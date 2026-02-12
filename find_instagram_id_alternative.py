#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Instagram Business Account ID'yi alternatif yöntemlerle bul"""

import requests
import os
from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_API = "https://graph.facebook.com/v19.0"


def find_instagram_account():
    """Instagram Business Account ID'yi bulmak için alternatif yöntemler"""

    if not ACCESS_TOKEN:
        print("HATA: INSTAGRAM_ACCESS_TOKEN .env dosyasinda tanimli degil!")
        return

    print("=== Instagram Business Account ID Bulma ===\n")

    # Yöntem 1: Mevcut sayfaları kontrol et
    print("1. Facebook sayfalari kontrol ediliyor...")
    url = f"{INSTAGRAM_API}/me/accounts"
    params = {"access_token": ACCESS_TOKEN}

    try:
        response = requests.get(url, params=params)
        data = response.json()

        if "error" in data:
            print(f"   HATA: {data['error']['message']}")
            if data["error"]["code"] == 190:
                print("   Token suresi dolmus veya gecersiz!")
            elif data["error"]["code"] == 200:
                print("   Token'in 'pages_show_list' izni olmali!")
        elif data.get("data"):
            pages = data["data"]
            print(f"   Bulunan sayfa sayisi: {len(pages)}\n")
            for page in pages:
                page_id = page.get("id")
                page_name = page.get("name", "Bilinmeyen")
                print(f"   Sayfa: {page_name} (ID: {page_id})")

                # Instagram Business Account kontrolü
                url = f"{INSTAGRAM_API}/{page_id}"
                params = {
                    "access_token": ACCESS_TOKEN,
                    "fields": "instagram_business_account",
                }
                response = requests.get(url, params=params)
                page_data = response.json()

                if "instagram_business_account" in page_data:
                    ig_account = page_data["instagram_business_account"]
                    ig_id = ig_account.get("id")
                    print(f"   ✓ Instagram Business Account ID: {ig_id}\n")
                    return ig_id
        else:
            print("   Hic sayfa bulunamadi")
            print("   Facebook sayfasi olusturmaniz gerekiyor!\n")

    except Exception as e:
        print(f"   HATA: {e}\n")

    # Yöntem 2: Instagram Business Account ID'yi direkt arama
    print("2. Alternatif yontemler:")
    print("   - Instagram Business Account ID'nizi biliyorsaniz:")
    print("     .env dosyasina direkt ekleyin:")
    print("     INSTAGRAM_USER_ID=your_instagram_business_account_id")
    print()
    print("   - Instagram Business Account ID'yi bulmak icin:")
    print("     1. Instagram mobil uygulamasinda hesabiniza gidin")
    print("     2. Ayarlar > Hesap > Hesap Tipi")
    print("     3. Business Account oldugundan emin olun")
    print("     4. Facebook sayfaniza bagli oldugundan emin olun")
    print()
    print("   - Facebook sayfasi olusturma:")
    print("     https://www.facebook.com/pages/create/")
    print("     Sayfa olusturduktan sonra Instagram hesabinizi baglayin")

    return None


if __name__ == "__main__":
    find_instagram_account()
