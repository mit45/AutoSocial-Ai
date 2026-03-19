import random
import re
from datetime import datetime, timedelta, timezone
from typing import cast

from app.services.trend_radar import get_trending_topics, get_next_topic_and_type
from app.services.content_ai import (
    generate_caption,
    generate_hashtags,
    generate_image_prompt,
    format_post_text,
    shorten_caption_for_image,
)
from app.services.image_backend import generate_image_url, generate_image_bytes, render_from_bytes
from app.services.monetization import attach_affiliate
from app.services.instagram import publish_image as ig_publish_image, publish_story as ig_publish_story
from app.database import SessionLocal
from app.models import AutomationSetting, Account, Post, PostStatus, PostType
from app.services.storage_service import save_png_bytes_to_generated, upload_to_remote_server
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app.config import BASE_URL
import json, os
from app.services.reels_engine import generate_reel_structure, generate_and_publish_reel
from app.services.feedback_loop_engine import load_learning_state


def next_post_time():
    return datetime.utcnow() + timedelta(minutes=30)


def daily_post_cycle(accounts):
    # Deprecated publishing path: do not publish directly from startup.
    # Keep function for backward compatibility but do nothing — use run_automation_check instead.
    for acc in accounts:
        try:
            print(f"[AUTOMATION][daily_post_cycle] Skipping direct publish for account {acc.id} ({acc.ig_user_id}). Use automation settings to generate drafts instead.")
        except Exception:
            pass


def run_automation_check():
    """
    Check automation settings and generate drafts when needed.
    """
    db = SessionLocal()
    try:
        settings = db.query(AutomationSetting).filter(AutomationSetting.enabled == 1).all()
        if not settings:
            return
        # Use naive UTC "now" for comparisons (DB stores naive UTC datetimes).
        now = datetime.utcnow()
        # detect local timezone for interpreting user-entered HH:MM values (they come from UI local time)
        local_tz = datetime.now().astimezone().tzinfo
        # local_now is the current time in local timezone (used to build scheduled_local correctly)
        local_now = datetime.now().astimezone(local_tz)
        print(f"[AUTOMATION] run_automation_check start: now={now.isoformat()}")
        for s in settings:
            try:
                print(f"[AUTOMATION] Checking setting id={s.id} account_id={s.account_id} enabled={s.enabled} frequency={s.frequency}")
            except Exception:
                pass
            # hour window: use start_time/end_time (HH:MM) if present, else start_hour/end_hour
            def parse_time_str(t):
                if not t:
                    return None
                try:
                    parts = t.split(":")
                    h = int(parts[0])
                    m = int(parts[1]) if len(parts) > 1 else 0
                    return h * 60 + m
                except Exception:
                    return None

            # Parse explicit daily/weekly time lists first
            daily_times = []
            try:
                daily_times = json.loads(str(s.daily_times)) if s.daily_times else []
            except Exception:
                daily_times = []

            weekly_times = []
            try:
                weekly_times = json.loads(str(s.weekly_times)) if s.weekly_times else []
            except Exception:
                weekly_times = []

            try:
                print(f"[AUTOMATION] daily_times={daily_times} weekly_times={weekly_times} last_run_at={s.last_run_at}")
            except Exception:
                pass

            _start = parse_time_str(s.start_time) if s.start_time else ((cast(int, s.start_hour) * 60) if s.start_hour is not None else 0)
            _end = parse_time_str(s.end_time) if s.end_time else ((cast(int, s.end_hour) * 60) if s.end_hour is not None else 23 * 60 + 59)
            start_minutes = _start if _start is not None else 0
            end_minutes = _end if _end is not None else (23 * 60 + 59)
            try:
                print(f"[AUTOMATION] Window minutes: start={start_minutes} end={end_minutes}")
            except Exception:
                pass
            now_minutes = now.hour*60 + now.minute
            # If explicit daily/weekly times are provided, skip this broad window check
            if not (daily_times or weekly_times):
                if not (start_minutes <= now_minutes <= end_minutes):
                    print(f"[AUTOMATION] Now ({now_minutes}) outside window for setting id={s.id}, skipping")
                    continue
            # determine counts already generated today (drafts created_at)
            acct = db.query(Account).filter(Account.id == s.account_id).first()
            if not acct:
                continue
            # If specific daily_times are defined, honor them (generate at exact times)
            daily_times = []
            try:
                daily_times = json.loads(str(s.daily_times)) if s.daily_times else []
            except Exception:
                daily_times = []

            weekly_times = []
            try:
                weekly_times = json.loads(str(s.weekly_times)) if s.weekly_times else []
            except Exception:
                weekly_times = []
            try:
                print(f"[AUTOMATION] daily_times={daily_times} weekly_times={weekly_times} last_run_at={s.last_run_at}")
            except Exception:
                pass

            def generate_draft_for_setting(
                auto_approve: bool = False,
                auto_publish_post: bool = False,
                auto_publish_story: bool = False,
                auto_publish_reels: bool = False,
                recent_threshold_minutes: int | None = None,
            ):
                def build_reel_visual_prompts(topic_text: str, base_prompt: str, count: int = 3) -> list[str]:
                    """
                    Build topic-grounded prompts to avoid irrelevant abstract visuals.
                    """
                    t = (topic_text or "").strip()
                    # light keyword extraction from topic
                    kws = [w for w in re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9]+", t.lower()) if len(w) >= 3]
                    kw_text = ", ".join(kws[:6]) if kws else t

                    tl = t.lower()
                    is_space = any(k in tl for k in ["uzay", "mars", "galaksi", "astronot", "roket", "yıldız", "evren"])
                    is_tech = any(k in tl for k in ["teknoloji", "yapay", "zeka", "kod", "yazılım", "robot", "otomasyon"])
                    is_science = any(k in tl for k in ["bilim", "fizik", "kimya", "biyoloji", "nörobilim"])

                    subject_rules = (
                        f"Subject must clearly represent this topic: '{t}'. "
                        f"Visual cues and elements related to: {kw_text}. "
                        "Do not generate unrelated generic abstract wallpaper."
                    )
                    # Global hard negatives (most common failure patterns)
                    negatives = (
                        "NEGATIVE: no flowers, no petals, no botanical ornaments, "
                        "no decorative swirls, no vintage frame, no abstract poster card, "
                        "no central blank rectangle, no typography, no watermark."
                    )

                    domain_directive = ""
                    if is_space:
                        domain_directive = (
                            "SPACE/MARS DIRECTIVE: include realistic space elements such as Mars surface, "
                            "planet horizon, stars, nebula, astronaut suit, rocket or spacecraft details. "
                            "Color palette should be cosmic (deep navy, black, red-orange Mars dust). "
                            "Absolutely avoid floral or wedding-like decorative style."
                        )
                    elif is_tech:
                        domain_directive = (
                            "TECH DIRECTIVE: include concrete technology cues (circuit patterns, data streams, "
                            "servers, robotic elements, modern UI-like light structures), clean futuristic look."
                        )
                    elif is_science:
                        domain_directive = (
                            "SCIENCE DIRECTIVE: include laboratory/science visual cues (equations, particles, "
                            "experiment setups, scientific diagrams) in a realistic modern style."
                        )
                    else:
                        domain_directive = (
                            "GENERAL DIRECTIVE: include concrete objects/scenes directly tied to the topic, "
                            "avoid purely ornamental abstraction."
                        )

                    style = (
                        "Vertical 9:16, cinematic, high detail, clean composition, "
                        "no text, no letters, no frame/border, no poster mockup, no watermark."
                    )
                    prompts: list[str] = []
                    for i in range(max(1, int(count))):
                        variant = (
                            f"Variant {i+1}: different camera angle and composition, "
                            "keep same topic semantics and recognizable objects."
                        )
                        prompts.append(
                            f"{base_prompt}. {subject_rules} {domain_directive} {negatives} {variant} {style}"
                        )
                    return prompts

                # Farklı tür ve konu; son 8 gönderinin konuları hariç tutulur, güncel trendlerden seçilir
                if auto_publish_reels:
                    # Keep atomic generation: from this run, publish only reels.
                    auto_publish_post = False
                    auto_publish_story = False
                recent_posts = (
                    db.query(Post.topic)
                    .filter(Post.account_id == s.account_id)
                    .order_by(Post.created_at.desc())
                    .limit(8)
                    .all()
                )
                recent_topics = [str(p.topic) for p in recent_posts if p.topic]
                last_topic = recent_topics[0] if recent_topics else None
                topic, content_type = get_next_topic_and_type(
                    exclude_last_topic=last_topic,
                    exclude_recent_topics=recent_topics,
                )
                # Dedup check: avoid creating multiple drafts in short time for same account.
                # When called from explicit daily_times/weekly_times slot, use shorter window (2 min) so each slot can produce one draft.
                threshold_min = recent_threshold_minutes if recent_threshold_minutes is not None else 10
                try:
                    cutoff = datetime.utcnow() - timedelta(minutes=float(threshold_min))
                    recent_cnt = db.query(Post).filter(Post.account_id == s.account_id, Post.created_at >= cutoff).count()
                    if recent_cnt > 0:
                        try:
                            print(f"[AUTOMATION] Skipping draft generation for setting id={s.id} - recent drafts found ({recent_cnt}) within last {threshold_min} minutes.")
                        except Exception:
                            pass
                        return
                except Exception:
                    pass

                # Claim-run via automation_runs table to prevent concurrent generators across processes.
                try:
                    run_date = local_now.date().isoformat()
                    db_claim = SessionLocal()
                    try:
                        db_claim.execute(
                            text(
                                "INSERT INTO automation_runs (setting_id, run_date, created_at) VALUES (:sid, :rd, :now)"
                            ),
                            {"sid": s.id, "rd": run_date, "now": datetime.utcnow()},
                        )
                        db_claim.commit()
                    finally:
                        try:
                            db_claim.close()
                        except Exception:
                            pass
                except IntegrityError:
                    try:
                        print(f"[AUTOMATION] Another process already claimed run for setting id={s.id} date={run_date}; skipping.")
                    except Exception:
                        pass
                    return
                except Exception:
                    # If claim fails for any reason, continue but rely on other dedupe checks.
                    pass
                try:
                    caption = generate_caption(topic, content_type=content_type)
                except Exception:
                    caption = f"Auto draft: {topic}"
                try:
                    hashtags = generate_hashtags(topic, caption=caption, count=10)
                except Exception:
                    hashtags = []
                try:
                    image_prompt = generate_image_prompt(topic)
                    if auto_publish_reels:
                        reel_prompts = build_reel_visual_prompts(topic, image_prompt, count=3)
                        first_bytes = generate_image_bytes(reel_prompts[0])
                        png_bytes = first_bytes
                        reel_backgrounds = [first_bytes]
                        # Reels: at least 3 topic-grounded visuals for scene variety.
                        for rp in reel_prompts[1:]:
                            try:
                                reel_backgrounds.append(generate_image_bytes(rp))
                            except Exception:
                                reel_backgrounds.append(first_bytes)
                        # store first prompt as post prompt trace
                        image_prompt = reel_prompts[0]
                    else:
                        png_bytes = generate_image_bytes(image_prompt)
                        reel_backgrounds = [png_bytes]
                    # Do not persist the text-less background to storage/R2.
                    # Render from bytes (temporary file handled by render_from_bytes).
                    rel_bg = None
                    public_bg = None
                except Exception:
                    public_bg = "https://images.pexels.com/photos/1032650/pexels-photo-1032650.jpeg"
                    rel_bg = None
                    png_bytes = b""
                    reel_backgrounds = [png_bytes]
                # Reels plan used for cover text & video scenes
                reel_structure = None
                if auto_publish_reels:
                    try:
                        learning_state = load_learning_state()
                    except Exception:
                        learning_state = None
                    try:
                        reel_structure = generate_reel_structure(
                            topic=topic,
                            content_type=content_type,
                            caption=caption,
                            learning_state=learning_state,
                        )
                    except Exception as e:
                        reel_structure = None
                        print(f"[AUTOMATION][reels] generate_reel_structure failed: {e}")
                # render final image (best effort)
                public_url = public_bg
                # If we have a temporary background file, render text on it and upload final only
                # If we have background bytes, render final image and upload final only
                try:
                    cover_text_source = caption
                    if auto_publish_reels and isinstance(reel_structure, dict):
                        cover_text_source = reel_structure.get("hook") or ((reel_structure.get("scenes") or [{}])[0].get("text") or caption)
                    image_text = shorten_caption_for_image(str(cover_text_source), max_chars=220)
                    rel_final, abs_final = render_from_bytes(png_bytes, image_text, "ince düşlerim", "minimal_dark")
                    with open(abs_final, "rb") as f:
                        final_bytes = f.read()
                    filename = os.path.basename(abs_final)
                    public_url = upload_to_remote_server(
                        final_bytes,
                        filename,
                        prefix="ig/reels" if auto_publish_reels else "ig/post",
                    )
                except Exception:
                    public_url = public_bg
                post = Post(
                    account_id=s.account_id,
                    topic=topic,
                    caption=caption,
                    hashtags=json.dumps(hashtags),
                    image_prompt=image_prompt if "image_prompt" in locals() else None,
                    image_url=public_url,
                    status=PostStatus.APPROVED if auto_approve else PostStatus.DRAFT,
                    type=PostType.REELS if auto_publish_reels else PostType.POST,
                    created_at=datetime.utcnow(),
                )
                # Second safety check (re-query just before commit to reduce race windows).
                try:
                    cutoff2 = datetime.utcnow() - timedelta(minutes=float(threshold_min))
                    recent_cnt2 = db.query(Post).filter(Post.account_id == s.account_id, Post.created_at >= cutoff2).count()
                    if recent_cnt2 > 0:
                        try:
                            print(f"[AUTOMATION] Aborting commit for draft generation for setting id={s.id} - recent drafts found ({recent_cnt2}) just before commit.")
                        except Exception:
                            pass
                        return
                except Exception:
                    pass

                db.add(post)
                # store last_run_at in UTC
                s.last_run_at = datetime.utcnow()
                db.add(s)
                db.commit()
                try:
                    print(f"[AUTOMATION] Generated draft id={post.id} for setting id={s.id} topic={topic}")
                except Exception:
                    pass
                # Otomatik yayınla: Celery'e bağımlı olmadan senkron yayın (worker olmadan da çalışır)
                try:
                    acct = db.query(Account).filter(Account.id == s.account_id).first()
                    if not acct:
                        pass
                    else:
                        ig_user_id = acct.ig_user_id
                        access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN") or acct.access_token
                        image_url_abs = public_url
                        if image_url_abs and (image_url_abs.startswith("/static/") or image_url_abs.startswith("/media/")):
                            domain = (BASE_URL or "http://127.0.0.1:8000").rstrip("/")
                            image_url_abs = domain + image_url_abs

                        if auto_publish_post:
                            try:
                                formatted_caption = format_post_text(caption, hashtags) if hashtags else caption
                                result = ig_publish_image(
                                    image_url_abs,
                                    formatted_caption,
                                    ig_user_id,
                                    access_token,
                                )
                                db_inner = SessionLocal()
                                try:
                                    p2 = db_inner.query(Post).filter(Post.id == post.id).first()
                                    if p2:
                                        if isinstance(result, dict) and result.get("id"):
                                            p2.status = PostStatus.PUBLISHED  # type: ignore[assignment]
                                            p2.published_at = datetime.utcnow()  # type: ignore[assignment]
                                            p2.ig_post_id_post = str(result["id"])  # type: ignore[assignment]
                                            p2.scheduled_at = None
                                            p2.scheduled_at_post = None
                                            p2.scheduled_at_story = None
                                            print(f"[AUTOMATION] Auto-published POST for draft id={post.id} ig_id={result['id']}")
                                        elif isinstance(result, dict) and result.get("error"):
                                            p2.status = PostStatus.FAILED  # type: ignore[assignment]
                                            p2.error_message = str(result.get("error", {}).get("message", result.get("error")))
                                            print(f"[AUTOMATION] Auto-publish POST failed for draft id={post.id}: {p2.error_message}")
                                        db_inner.add(p2)
                                        db_inner.commit()
                                finally:
                                    db_inner.close()
                            except Exception as e:
                                print(f"[AUTOMATION] Auto-publish POST failed for draft id={post.id}: {e}")
                                try:
                                    db_inner = SessionLocal()
                                    p2 = db_inner.query(Post).filter(Post.id == post.id).first()
                                    if p2:
                                        p2.status = PostStatus.FAILED  # type: ignore[assignment]
                                        p2.error_message = str(e)
                                        db_inner.add(p2)
                                        db_inner.commit()
                                    db_inner.close()
                                except Exception:
                                    pass

                        if auto_publish_story:
                            try:
                                result = ig_publish_story(
                                    image_url_abs,
                                    ig_user_id,
                                    access_token,
                                )
                                db_inner = SessionLocal()
                                try:
                                    p2 = db_inner.query(Post).filter(Post.id == post.id).first()
                                    if p2:
                                        publish_id = None
                                        if isinstance(result, dict):
                                            publish_id = result.get("publish_id")
                                            if not publish_id and isinstance(result.get("publish_response"), dict):
                                                publish_id = result.get("publish_response", {}).get("id")
                                        if publish_id:
                                            p2.status = PostStatus.PUBLISHED  # type: ignore[assignment]
                                            p2.published_at = datetime.utcnow()  # type: ignore[assignment]
                                            p2.ig_post_id_story = str(publish_id)  # type: ignore[assignment]
                                            p2.scheduled_at = None
                                            p2.scheduled_at_post = None
                                            p2.scheduled_at_story = None
                                            print(f"[AUTOMATION] Auto-published STORY for draft id={post.id} ig_id={publish_id}")
                                        elif isinstance(result, dict) and result.get("error"):
                                            p2.error_message = str(result.get("error", {}).get("message", result.get("error")))
                                            if p2.status != PostStatus.PUBLISHED:
                                                p2.status = PostStatus.FAILED  # type: ignore[assignment]
                                            print(f"[AUTOMATION] Auto-publish STORY failed for draft id={post.id}: {p2.error_message}")
                                        db_inner.add(p2)
                                        db_inner.commit()
                                finally:
                                    db_inner.close()
                            except Exception as e:
                                print(f"[AUTOMATION] Auto-publish STORY failed for draft id={post.id}: {e}")
                                try:
                                    db_inner = SessionLocal()
                                    p2 = db_inner.query(Post).filter(Post.id == post.id).first()
                                    if p2:
                                        p2.status = PostStatus.FAILED  # type: ignore[assignment]
                                        p2.error_message = str(e)
                                        db_inner.add(p2)
                                        db_inner.commit()
                                    db_inner.close()
                                except Exception:
                                    pass
                        if auto_publish_reels:
                            try:
                                if not reel_structure:
                                    reel_structure = generate_reel_structure(
                                        topic=topic,
                                        content_type=content_type,
                                        caption=caption,
                                        learning_state=load_learning_state(),
                                    )
                                rp = generate_and_publish_reel(
                                    topic=topic,
                                    content_type=content_type,
                                    caption=caption,
                                    background_png_bytes=png_bytes,
                                    background_png_bytes_list=reel_backgrounds if auto_publish_reels else None,
                                    ig_user_id=ig_user_id,
                                    access_token=access_token,
                                    hashtags=hashtags,
                                    reel_structure=reel_structure,
                                )

                                db_inner = SessionLocal()
                                try:
                                    p2 = db_inner.query(Post).filter(Post.id == post.id).first()
                                    if p2:
                                        # publish_reel_graph success path typically returns publish_response.id
                                        publish_response = (rp or {}).get("publish_response") if isinstance(rp, dict) else None
                                        published_id = None
                                        if isinstance(publish_response, dict):
                                            published_id = publish_response.get("id")
                                        published_id = published_id or (rp or {}).get("publish_id")

                                        if published_id:
                                            p2.status = PostStatus.PUBLISHED  # type: ignore[assignment]
                                            p2.published_at = datetime.utcnow()  # type: ignore[assignment]
                                            p2.ig_post_id = str(published_id)  # type: ignore[assignment]
                                            p2.scheduled_at = None
                                            p2.scheduled_at_post = None
                                            p2.scheduled_at_story = None
                                            print(f"[AUTOMATION] Auto-published REELS for draft id={post.id} ig_id={published_id}")
                                        elif isinstance(rp, dict) and rp.get("error"):
                                            p2.status = PostStatus.FAILED  # type: ignore[assignment]
                                            err_obj = rp.get("error")
                                            if isinstance(err_obj, (dict, list)):
                                                p2.error_message = json.dumps(err_obj, ensure_ascii=False)
                                            else:
                                                p2.error_message = str(err_obj)
                                            print(f"[AUTOMATION] Auto-publish REELS failed for draft id={post.id}: {p2.error_message}")
                                        else:
                                            p2.status = PostStatus.FAILED  # type: ignore[assignment]
                                            p2.error_message = f"Unexpected reels publish response: {rp}"
                                            print(f"[AUTOMATION] Auto-publish REELS failed for draft id={post.id}: {p2.error_message}")
                                        db_inner.add(p2)
                                        db_inner.commit()
                                finally:
                                    db_inner.close()
                            except Exception as e:
                                print(f"[AUTOMATION] Auto-publish REELS failed for draft id={post.id}: {e}")
                                try:
                                    db_inner = SessionLocal()
                                    p2 = db_inner.query(Post).filter(Post.id == post.id).first()
                                    if p2:
                                        p2.status = PostStatus.FAILED  # type: ignore[assignment]
                                        p2.error_message = str(e)
                                        db_inner.add(p2)
                                        db_inner.commit()
                                finally:
                                    db_inner.close()
                except Exception as e:
                    print(f"[AUTOMATION] Auto-publish error: {e}")

            # If frequency == daily and explicit daily_times exist, check them
            if s.frequency == "daily" and daily_times:
                for t in daily_times:
                    try:
                        # t can be "HH:MM" or {time: "HH:MM", auto_approve: bool}
                        var_time = t.get("time") if isinstance(t, dict) else str(t)
                        auto_approve = bool(t.get("auto_approve")) if isinstance(t, dict) else False
                        parts = str(var_time).split(":")
                        hh = int(parts[0])
                        mm = int(parts[1]) if len(parts) > 1 else 0
                        # interpret user's time as local timezone (use local calendar day) then convert to UTC (naive) for comparison
                        scheduled_local = datetime(local_now.year, local_now.month, local_now.day, hh, mm, tzinfo=local_tz)
                        scheduled_dt = scheduled_local.astimezone(timezone.utc).replace(tzinfo=None)
                        # only act when scheduled time <= now (both naive UTC)
                        if scheduled_dt <= now:
                            # if last_run_at is None or earlier than scheduled_dt, generate
                            last_run = s.last_run_at
                            # Normalize comparison using local timezone to avoid UTC day-shift issues.
                            # scheduled_local is aware (local_tz). Convert last_run (naive UTC stored) to local tz.
                            last_run_local = None
                            if last_run:
                                try:
                                    last_run_utc = last_run.replace(tzinfo=timezone.utc)
                                    last_run_local = last_run_utc.astimezone(local_tz)
                                except Exception:
                                    last_run_local = None
                            # If we've never run (last_run_local is None) OR last run was before this scheduled_local time, generate.
                            if not last_run_local or last_run_local < scheduled_local:
                                auto_publish_post = bool(t.get("auto_publish_post")) if isinstance(t, dict) else False
                                auto_publish_story = bool(t.get("auto_publish_story")) if isinstance(t, dict) else False
                                auto_publish_reels = bool(t.get("auto_publish_reels")) if isinstance(t, dict) else False
                                # Use 2-min recent window so consecutive slots (e.g. 01:08 and 01:10) can each generate one draft with image
                                generate_draft_for_setting(
                                    auto_approve=auto_approve,
                                    auto_publish_post=auto_publish_post,
                                    auto_publish_story=auto_publish_story,
                                    auto_publish_reels=auto_publish_reels,
                                    recent_threshold_minutes=2,
                                )
                    except Exception:
                        continue
                # done with this setting
                continue

            # If frequency == weekly and weekly_times exist, check them
            if s.frequency == "weekly" and weekly_times:
                # weekly_times items expected: {"day":"Mon","time":"HH:MM"}
                weekday_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
                for item in weekly_times:
                    try:
                        # item can be {"day":"Mon","time":"HH:MM","auto_approve":bool} or simple value
                        day = item.get("day") if isinstance(item, dict) else None
                        time_str = item.get("time") if isinstance(item, dict) else str(item)
                        auto_approve = bool(item.get("auto_approve")) if isinstance(item, dict) else False
                        if not day or not time_str:
                            continue
                        target_wd = weekday_map.get(day, None)
                        if target_wd is None:
                            continue
                        # compute date for this week's target weekday
                        days_ahead = target_wd - now.weekday()
                        scheduled_date = now.date() + timedelta(days=days_ahead)
                        parts = str(time_str).split(":")
                        hh = int(parts[0])
                        mm = int(parts[1]) if len(parts) > 1 else 0
                        # interpret scheduled date/time in local timezone (use local date for week calculation)
                        # compute scheduled_date relative to local_now's date
                        local_date = local_now.date()
                        # adjust scheduled_date to this week's target weekday relative to local date
                        days_ahead = target_wd - local_date.weekday()
                        scheduled_date_local = local_date + timedelta(days=days_ahead)
                        scheduled_local = datetime(scheduled_date_local.year, scheduled_date_local.month, scheduled_date_local.day, hh, mm, tzinfo=local_tz)
                        scheduled_dt = scheduled_local.astimezone(timezone.utc).replace(tzinfo=None)
                        if scheduled_dt <= now:
                            last_run = s.last_run_at
                            # Convert stored naive-UTC last_run to local timezone for reliable comparison
                            last_run_local = None
                            if last_run:
                                try:
                                    last_run_utc = last_run.replace(tzinfo=timezone.utc)
                                    last_run_local = last_run_utc.astimezone(local_tz)
                                except Exception:
                                    last_run_local = None
                            if not last_run_local or last_run_local < scheduled_dt.astimezone(local_tz):
                                auto_publish_post = bool(item.get("auto_publish_post")) if isinstance(item, dict) else False
                                auto_publish_story = bool(item.get("auto_publish_story")) if isinstance(item, dict) else False
                                auto_publish_reels = bool(item.get("auto_publish_reels")) if isinstance(item, dict) else False
                                generate_draft_for_setting(
                                    auto_approve=auto_approve,
                                    auto_publish_post=auto_publish_post,
                                    auto_publish_story=auto_publish_story,
                                    auto_publish_reels=auto_publish_reels,
                                    recent_threshold_minutes=2,
                                )
                    except Exception:
                        continue
                continue

            # fallback: original daily_count-based generation when no explicit times provided
            if s.frequency == "daily":
                target = s.daily_count or 1
                # count drafts today for this account
                day_start = datetime(now.year, now.month, now.day)
                cnt = db.query(Post).filter(Post.account_id == s.account_id, Post.created_at >= day_start).count()
                if cnt < target:
                    generate_draft_for_setting()
    finally:
        db.close()
