"""
Kalıcı SECRET_KEY ve ENCRYPTION_KEY üretir. Çıktıyı .env dosyanıza kopyalayın.

Kullanım:
    python scripts/generate_secrets.py
"""

from __future__ import annotations

import secrets

from cryptography.fernet import Fernet


def main() -> None:
    print("# Aşağıdaki iki satırı `.env` dosyanıza ekleyin / güncelleyin.")
    print("# DİKKAT: ENCRYPTION_KEY değiştirilirse önceden şifrelenmiş veriler çözülemez!")
    print()
    print(f"SECRET_KEY={secrets.token_urlsafe(64)}")
    print(f"ENCRYPTION_KEY={Fernet.generate_key().decode('utf-8')}")


if __name__ == "__main__":
    main()
