# pipeline/uploader.py
import os
import traceback
from pathlib import Path
from typing import Dict, Optional

from engine.config_manager import config_manager
from engine.database import db
from engine.discord_notifier import notifier
from engine.quota_manager import quota_manager


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

    Returns the YouTube video ID on success, None on failure.
    """
    cfg = config_manager.pipeline
    max_retries = cfg.get("max_upload_retries", 3)

    # Check quota before attempting (upload costs 1600 units)
    can, reason = quota_manager.can_use_youtube(units=1600)
    if not can:
        print(f"❌ Cannot upload — {reason}")
        notifier.send_warning("Upload Skipped — Quota", reason)
        return None

    body = {
        "snippet": {
            "title": seo["title"],
            "description": seo["description"],
            "tags": seo["tags"],
            "categoryId": "22",  # People & Blogs (good for clip channels)
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
                return None  # No point retrying auth errors

            if attempt < max_retries - 1:
                import time
                time.sleep(5 * (attempt + 1))

    notifier.send_warning("Upload Failed",
                          f"Could not upload `{seo['title']}` after {max_retries} attempts")
    return None
