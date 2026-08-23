# pipeline/uploader.py
import os
import random
import re
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

from engine.config_manager import config_manager
from engine.database import db
from engine.discord_notifier import notifier
from engine.quota_manager import quota_manager

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"


class AuthFatalError(Exception):
    """Raised when YouTube OAuth credentials are invalid/expired — halts the run."""


# ── Anti-spam / policy guard ─────────────────────────────────────────────────

def check_upload_allowed(title: str) -> Tuple[bool, str]:
    """
    Run all pre-upload safety checks. Returns (allowed, reason).

    Checks:
    1. Weekly upload cap — prevents algorithm spam flags
    2. Minimum hours between uploads — avoids mechanical upload pattern detection
    3. Title similarity — blocks near-duplicate shorts within recent history
    """
    cfg = config_manager.pipeline

    # 1. Weekly cap
    weekly_cap = cfg.get("max_clips_per_week", 30)
    uploads_this_week = db.get_uploads_this_week_count()
    if uploads_this_week >= weekly_cap:
        return False, (f"Weekly upload cap reached ({uploads_this_week}/{weekly_cap}). "
                       "Wait for next week's quota to reset.")

    # 2. Minimum hours between uploads
    min_hours = cfg.get("min_hours_between_uploads", 3)
    last_upload = db.get_last_upload_time()
    if last_upload:
        try:
            last_dt = datetime.fromisoformat(last_upload.replace("Z", "+00:00"))
            elapsed_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if elapsed_hours < min_hours:
                wait_mins = int((min_hours - elapsed_hours) * 60)
                return False, (f"Must wait {wait_mins}m more before next upload "
                               f"(min gap: {min_hours}h between uploads).")
        except Exception:
            pass

    # 3. Title similarity check
    max_similarity = cfg.get("max_title_similarity", 0.80)
    recent_titles = db.get_recent_upload_titles(days=7)
    for past_title in recent_titles:
        similarity = _title_similarity(title, past_title)
        if similarity >= max_similarity:
            return False, (f"Title too similar to recent upload "
                           f"(similarity {similarity:.0%}): '{past_title[:50]}'")

    return True, "ok"


def _title_similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity ratio between two titles."""
    a_words = set(re.sub(r"[^a-z0-9 ]", "", a.lower()).split())
    b_words = set(re.sub(r"[^a-z0-9 ]", "", b.lower()).split())
    # Remove Shorts-specific words that are always present
    stopwords = {"shorts", "short", "best", "moment", "moments", "the", "a", "of"}
    a_words -= stopwords
    b_words -= stopwords
    if not a_words or not b_words:
        return 0.0
    overlap = len(a_words & b_words)
    return overlap / max(len(a_words), len(b_words))


def upload_short(
    video_path: Path,
    seo: Dict,
    scheduled_at: str,
    source_video_id: str,
    creator_name: str,
    youtube_service,
) -> Optional[str]:
    """
    Upload a rendered short to YouTube as a private scheduled video.

    TEST_MODE: no actual upload — simulates success and returns a dummy ID.

    Returns the YouTube video ID on success, None on failure.
    """
    cfg = config_manager.pipeline
    max_retries = cfg.get("max_upload_retries", 3)

    # ── TEST_MODE: simulate upload, don't touch YouTube ──────────────────
    if TEST_MODE:
        import time
        dummy_id = f"test_{source_video_id}_{int(time.time())}"
        print(f"🧪 [TEST MODE] Simulating upload: {seo['title']}")
        print(f"   (no YouTube quota consumed, no actual upload)")
        db.record_upload(
            youtube_id=dummy_id,
            source_video_id=source_video_id,
            creator_name=creator_name,
            title=seo["title"],
            scheduled_at=scheduled_at,
        )
        notifier.send_upload(seo["title"],
                             f"https://youtube.com/shorts/{dummy_id}",
                             creator_name, scheduled_at)
        return dummy_id

    # ── Pre-upload spam/policy guard ─────────────────────────────────────
    allowed, guard_reason = check_upload_allowed(seo.get("title", ""))
    if not allowed:
        print(f"🛑 Upload blocked by safety guard: {guard_reason}")
        notifier.send_warning("Upload Blocked — Safety Guard", guard_reason)
        return None

    # Check quota before attempting (upload costs 1600 units)
    can, reason = quota_manager.can_use_youtube(units=1600)
    if not can:
        print(f"❌ Cannot upload — {reason}")
        notifier.send_warning("Upload Skipped — Quota", reason)
        return None

    # Category ID: prefer seo dict value (set by seo_generator per clip_type),
    # fall back to channel config default.
    try:
        upload_channel_cfg = config_manager.get_upload_channel()
        category_id = str(seo.get("category_id") or
                          upload_channel_cfg.get("category_id", "22"))

    except Exception:
        category_id = "22"

    body = {
        "snippet": {
            "title": seo["title"],
            "description": seo["description"],
            "tags": seo["tags"],
            "categoryId": category_id,
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",   # Private until scheduled time
            "publishAt": scheduled_at,    # ISO 8601 UTC
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        },
    }

    for attempt in range(max_retries):
        try:
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(
                str(video_path),
                mimetype="video/mp4",
                resumable=True,
                chunksize=5 * 1024 * 1024,  # 5 MB chunks
            )

            request = youtube_service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    print(f"   Upload progress: {pct}%")

            youtube_id = response["id"]
            quota_manager.record_youtube(
                config_manager.get_yt_unit_cost("videos_insert"), "videos_insert"
            )

            youtube_url = f"https://youtube.com/shorts/{youtube_id}"
            db.record_upload(
                youtube_id=youtube_id,
                source_video_id=source_video_id,
                creator_name=creator_name,
                title=seo["title"],
                scheduled_at=scheduled_at,
            )

            print(f"✅ Uploaded: {seo['title']} → {youtube_url}")
            print(f"   Scheduled publish: {scheduled_at}")
            notifier.send_upload(seo["title"], youtube_url, creator_name, scheduled_at)
            return youtube_id

        except Exception as e:
            err_str = str(e)
            print(f"⚠️  Upload attempt {attempt + 1} failed: {err_str[:150]}")
            db.log_failure("uploader", err_str, traceback.format_exc()[-500:])

            is_auth = any(x in err_str.lower() for x in ["401", "unauthorized", "invalid_grant"])
            if is_auth:
                notifier.send_error(
                    "YouTube Auth Error",
                    "OAuth token is invalid. Re-authenticate via setup script.",
                )
                # FATAL: raise so the orchestrator halts the upload loop and
                # surfaces the auth failure instead of continuing to burn
                # upload attempts / waste quota on dead credentials.
                raise AuthFatalError("YouTube OAuth token is invalid/expired")

            if attempt < max_retries - 1:
                import time
                time.sleep(5 * (attempt + 1))

    notifier.send_warning("Upload Failed",
                          f"Could not upload `{seo['title']}` after {max_retries} attempts")
    return None
