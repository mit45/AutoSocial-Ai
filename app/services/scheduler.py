from datetime import datetime, timedelta, timezone
from app.services.trend_radar import get_trending_topics
from app.services.content_ai import generate_caption, generate_hashtags, generate_image_prompt
from app.services.image_backend import generate_image_url, generate_image_bytes, render_from_bytes
from app.services.monetization import attach_affiliate
from worker.tasks import publish_post
from app.database import SessionLocal
from app.models import AutomationSetting, Account, Post, PostStatus
from app.services.storage_service import save_png_bytes_to_generated, upload_to_remote_server
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import json, os


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
                daily_times = json.loads(s.daily_times) if s.daily_times else []
            except Exception:
                daily_times = []

            weekly_times = []
            try:
                weekly_times = json.loads(s.weekly_times) if s.weekly_times else []
            except Exception:
                weekly_times = []

            try:
                print(f"[AUTOMATION] daily_times={daily_times} weekly_times={weekly_times} last_run_at={s.last_run_at}")
            except Exception:
                pass

            start_minutes = parse_time_str(s.start_time) if s.start_time else (s.start_hour * 60 if s.start_hour is not None else 0)
            end_minutes = parse_time_str(s.end_time) if s.end_time else (s.end_hour * 60 if s.end_hour is not None else 23*60+59)
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
                daily_times = json.loads(s.daily_times) if s.daily_times else []
            except Exception:
                daily_times = []

            weekly_times = []
            try:
                weekly_times = json.loads(s.weekly_times) if s.weekly_times else []
            except Exception:
                weekly_times = []
            try:
                print(f"[AUTOMATION] daily_times={daily_times} weekly_times={weekly_times} last_run_at={s.last_run_at}")
            except Exception:
                pass

            def generate_draft_for_setting(auto_approve: bool = False, auto_publish_post: bool = False, auto_publish_story: bool = False):
                topic = get_trending_topics()[0]
                # Dedup check: avoid creating multiple drafts in short time for same account/topic
                try:
                    # Increase recent threshold to avoid rapid duplicate generation (race conditions).
                    recent_threshold_minutes = 10
                    cutoff = datetime.utcnow() - timedelta(minutes=recent_threshold_minutes)
                    recent_cnt = db.query(Post).filter(Post.account_id == s.account_id, Post.created_at >= cutoff).count()
                    if recent_cnt > 0:
                        try:
                            print(f"[AUTOMATION] Skipping draft generation for setting id={s.id} - recent drafts found ({recent_cnt}) within last {recent_threshold_minutes} minutes.")
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
                    caption = generate_caption(topic)
                except Exception:
                    caption = f"Auto draft: {topic}"
                try:
                    hashtags = generate_hashtags(topic, caption=caption, count=10)
                except Exception:
                    hashtags = []
                try:
                    image_prompt = generate_image_prompt(topic)
                    png_bytes = generate_image_bytes(image_prompt)
                    # Do not persist the text-less background to storage/R2.
                    # Render from bytes (temporary file handled by render_from_bytes).
                    rel_bg = None
                    public_bg = None
                except Exception:
                    public_bg = "https://images.pexels.com/photos/1032650/pexels-photo-1032650.jpeg"
                    rel_bg = None
                # render final image (best effort)
                public_url = public_bg
                # If we have a temporary background file, render text on it and upload final only
                # If we have background bytes, render final image and upload final only
                try:
                    rel_final, abs_final = render_from_bytes(png_bytes, caption, "ince düşlerim", "minimal_dark")
                    with open(abs_final, "rb") as f:
                        final_bytes = f.read()
                    filename = os.path.basename(abs_final)
                    public_url = upload_to_remote_server(final_bytes, filename, prefix="ig/post")
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
                    created_at=datetime.utcnow(),
                )
                # Second safety check (re-query just before commit to reduce race windows).
                try:
                    cutoff2 = datetime.utcnow() - timedelta(minutes=recent_threshold_minutes)
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
                # If auto publish requested, dispatch publish tasks
                try:
                    from worker.tasks import publish_post, publish_story_task
                    acct = db.query(Account).filter(Account.id == s.account_id).first()
                    if acct:
                        ig_user_id = acct.ig_user_id
                        access_token = acct.access_token
                        # schedule publishing tasks with 60s delay to allow any backend processing to settle
                        if auto_publish_post:
                            payload = {
                                "image": public_url,
                                "caption": caption,
                                "ig_user_id": ig_user_id,
                                "access_token": access_token,
                                "post_id": post.id,
                                "account_id": s.account_id,
                            }
                            try:
                                # schedule 60s later
                                publish_post.apply_async(args=(payload,), countdown=60)
                                # Clear any scheduled_at fields to avoid duplicate scheduled_publisher runs
                                try:
                                    db_inner = SessionLocal()
                                    p2 = db_inner.query(Post).filter(Post.id == post.id).first()
                                    if p2:
                                        p2.scheduled_at = None
                                        p2.scheduled_at_post = None
                                        p2.scheduled_at_story = None
                                        db_inner.add(p2)
                                        db_inner.commit()
                                    db_inner.close()
                                except Exception:
                                    pass
                                print(f"[AUTOMATION] Scheduled publish_post task (in 60s) for draft id={post.id}")
                            except Exception as e:
                                print(f"[AUTOMATION] Failed to schedule publish_post task: {e}")
                        if auto_publish_story:
                            payload_s = {
                                "image_url": public_url,
                                "ig_user_id": ig_user_id,
                                "access_token": access_token,
                                "post_id": post.id,
                                "account_id": s.account_id,
                            }
                            try:
                                publish_story_task.apply_async(args=(payload_s,), countdown=60)
                                # Clear scheduled fields to avoid duplicate scheduling
                                try:
                                    db_inner = SessionLocal()
                                    p2 = db_inner.query(Post).filter(Post.id == post.id).first()
                                    if p2:
                                        p2.scheduled_at = None
                                        p2.scheduled_at_post = None
                                        p2.scheduled_at_story = None
                                        db_inner.add(p2)
                                        db_inner.commit()
                                    db_inner.close()
                                except Exception:
                                    pass
                                print(f"[AUTOMATION] Scheduled publish_story task (in 60s) for draft id={post.id}")
                            except Exception as e:
                                print(f"[AUTOMATION] Failed to schedule publish_story task: {e}")
                except Exception:
                    pass

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
                                generate_draft_for_setting(auto_approve=auto_approve, auto_publish_post=auto_publish_post, auto_publish_story=auto_publish_story)
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
                                generate_draft_for_setting(auto_approve=auto_approve, auto_publish_post=auto_publish_post, auto_publish_story=auto_publish_story)
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
