# AutoSocial-AI — English / Türkçe

This repository contains a lightweight FastAPI + SQLAlchemy MVP that generates, renders and schedules Instagram posts and stories using OpenAI (chat + image), Pillow for rendering text onto images, and optional FTP/HTTP upload for serving media.

--------------------------------------------------------------------------------

ENGLISH
-------

## What it does
- Generate captions, hashtags and image prompts using OpenAI.
- Generate or use background images, then render centered text + small signature on the image (Post: 1080×1080, Story: 1080×1920).
- Save final images locally and optionally upload to a remote server via FTP or an HTTP upload API.
- Publish posts and stories to Instagram using the Instagram Graph API (create media container → publish).
- Schedule posts for future publishing with a background checker.

## Quickstart (development)
1. Clone the repository:

   git clone <your-repo-url>.git
   cd AutoSocial-AI

2. Create and activate a virtual environment, then install dependencies:

   python -m venv .venv
   # macOS / Linux
   source .venv/bin/activate
   # Windows PowerShell
   .venv\\Scripts\\activate
   pip install -r requirements.txt

3. Copy `.env.example` to `.env` and fill required values (do NOT commit `.env`):

   cp .env.example .env

   Minimum environment variables:
   - OPENAI_API_KEY
   - INSTAGRAM_ACCESS_TOKEN
   - INSTAGRAM_USER_ID
   - BASE_URL (e.g. https://umittopuz.com)

   Optional:
   - UPLOAD_BASE_URL, UPLOAD_API_URL, UPLOAD_API_KEY
   - FTP_HOST / FTP_USER / FTP_PASSWORD
   - DATABASE_URL (default uses sqlite:///./autosocial.db)

4. Run the app:

   uvicorn app.main:app --reload --host 0.0.0.0 --port 9001

5. Open the UI:

   http://127.0.0.1:9001/

## Notes
- Do NOT commit secrets. `.env` is included in `.gitignore`.
- Generated backgrounds are stored in `storage/generated/` and final renders in `media/`. Those are ignored by git — prefer remote upload in production.
- Instagram tokens expire; monitor and refresh them as needed.
- If deployment requires reliable scheduling, run the app continuously (systemd / supervisor) or use OS scheduling to call `/api/scheduled/check`.

--------------------------------------------------------------------------------

TÜRKÇE
------

## Neler yapar
- OpenAI kullanarak başlık (caption), hashtag ve görsel promptu üretir.
- Arka plan görseli oluşturur veya var olanı kullanır; görsel üzerine ortalanmış ana metin ve küçük imza basar (Post: 1080×1080, Story: 1080×1920).
- Final görselleri yerel olarak kaydeder ve istenirse uzak sunucuya FTP veya HTTP upload API ile yükler.
- Instagram Graph API ile Post ve Story yayınlar (media container oluştur → publish).
- Zamanlanmış paylaşımlar için arka planda kontrol eden bir işçi içerir.

## Hızlı başlangıç (geliştirme)
1. Depoyu klonlayın:

   git clone <your-repo-url>.git
   cd AutoSocial-AI

2. Sanal ortam oluşturup bağımlılıkları yükleyin:

   python -m venv .venv
   # macOS / Linux
   source .venv/bin/activate
   # Windows PowerShell
   .venv\\Scripts\\activate
   pip install -r requirements.txt

3. `.env.example` dosyasını `.env` yapıp gerekli alanları doldurun (GİT'e commit etmeyin):

   cp .env.example .env

   Zorunlu alanlar:
   - OPENAI_API_KEY
   - INSTAGRAM_ACCESS_TOKEN
   - INSTAGRAM_USER_ID
   - BASE_URL (örn: https://umittopuz.com)

   Opsiyonel:
   - UPLOAD_BASE_URL, UPLOAD_API_URL, UPLOAD_API_KEY
   - FTP_HOST / FTP_USER / FTP_PASSWORD
   - DATABASE_URL (default sqlite)

4. Uygulamayı çalıştırın:

   uvicorn app.main:app --reload --host 0.0.0.0 --port 9001

5. Arayüz:

   http://127.0.0.1:9001/

## Notlar
- `.env` dosyasını repoya koymayın. `.env.example` şablon olarak kullanın.
- Görseller `storage/generated/` ve `media/` içinde tutulur; prod ortamında uzak upload tercih edin.
- Instagram tokenları süresi dolabilir — yenileme gerektiğinde yenileyin.
- Zamanlama için servis sürekli çalışmalı veya düzenli olarak `/api/scheduled/check` çağrılmalı.

