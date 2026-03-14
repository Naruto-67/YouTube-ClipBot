# pipeline/fetcher.py
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from engine.config_manager import config_manager
from engine.database import db
from engine.discord_notifier import notifier
from engine.quota_manager import quota_manager

ROOT = Path(__file__).parent.parent
TEMP_DIR = ROOT / "temp"


def _build_youtube_service():
    """Build YouTube Data API service from stored credentials."""
    import json
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    raw = os.environ.get("YOUTUBE_CREDENTIALS", "")
    if not raw:
        raise RuntimeError("YOUTUBE_CREDENTIALS secret is not set.")

    creds_data = json.loads(raw)
    creds = Credentials(
        token=None,
        refresh_token=creds_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
    )
    return build("youtube", "v3", credentials=creds), creds


def get_youtube_service():
    """Return (youtube_service, credentials) tuple."""
    return _build_youtube_service()


# ── Disk check ────────────────────────────────────────────────────────────

def check_disk_space() -> bool:
    cfg = config_manager.pipeline
    min_gb = cfg.get("min_disk_free_gb", 3)
    stat = shutil.disk_usage(ROOT)
    free_gb = stat.free / (1024 ** 3)
    if free_gb < min_gb:
        notifier.send_warning(
            "Low Disk Space",
            f"Only {free_gb:.1f} GB free. Minimum required: {min_gb} GB. "
            "Skipping this download."
        )
        return False
    return True


# ── yt-dlp self-update ────────────────────────────────────────────────────

def update_ytdlp():
    """Auto-update yt-dlp before every run to stay ahead of YouTube bot detection."""
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp", "-q"],
            check=True, capture_output=True
        )
        print("✅ yt-dlp updated")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  yt-dlp update failed (continuing with current version): {e}")


# ── Viral video discovery ─────────────────────────────────────────────────

def fetch_viral_videos(creator: Dict, youtube_service) -> List[Dict]:
    """
    Fetch recently viral videos from a creator using their uploads playlist.
    Cost-efficient: uses playlistItems.list (1 unit) + videos.list (1 unit)
    instead of search.list (100 units).
    """
    cfg = config_manager.pipeline
    max_age_days = cfg.get("max_video_age_days", 30)
    max_length_min = cfg.get("max_video_length_minutes", 30)
    max_results = creator.get("max_videos_per_run", 2)
    channel_id = creator["channel_id"]
    creator_name = creator["name"]

    can, reason = quota_manager.can_use_youtube(units=4)
    if not can:
        print(f"⚠️  YouTube quota: {reason}")
        return []

    try:
        # Step 1 — get uploads playlist ID (1 unit)
        ch_resp = youtube_service.channels().list(
            part="contentDetails", id=channel_id
        ).execute()
        quota_manager.record_youtube(
            config_manager.get_yt_unit_cost("channels_list"), "channels_list"
        )

        if not ch_resp.get("items"):
            print(f"⚠️  Channel not found: {creator_name} ({channel_id})")
            return []

        uploads_id = (
            ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        )

        # Step 2 — get recent uploads (1 unit)
        pl_resp = youtube_service.playlistItems().list(
            part="snippet",
            playlistId=uploads_id,
            maxResults=50,
        ).execute()
        quota_manager.record_youtube(
            config_manager.get_yt_unit_cost("playlist_items_list"), "playlist_items_list"
        )

        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        candidates = []

        for item in pl_resp.get("items", []):
            snippet = item["snippet"]
            vid_id = snippet["resourceId"]["videoId"]
            title = snippet.get("title", "")
            published_str = snippet.get("publishedAt", "")

            # Already processed?
            if db.is_video_processed(vid_id):
                continue

            # Age check
            if published_str:
                pub_dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                if pub_dt < cutoff:
                    continue

            candidates.append({"id": vid_id, "title": title,
                                "published": published_str})

        if not candidates:
            print(f"ℹ️  No new videos for {creator_name}")
            return []

        # Step 3 — get view counts + duration (1 unit per 50 videos)
        vid_ids = [v["id"] for v in candidates[:50]]
        stats_resp = youtube_service.videos().list(
            part="statistics,contentDetails",
            id=",".join(vid_ids),
        ).execute()
        quota_manager.record_youtube(
            config_manager.get_yt_unit_cost("videos_list"), "videos_list"
        )

        stats_map = {}
        for item in stats_resp.get("items", []):
            vid_id = item["id"]
            views = int(item.get("statistics", {}).get("viewCount", 0))
            duration_iso = item.get("contentDetails", {}).get("duration", "PT0S")
            duration_sec = _parse_iso_duration(duration_iso)
            stats_map[vid_id] = {"views": views, "duration_sec": duration_sec}

        # Enrich + filter by length
        enriched = []
        for v in candidates:
            s = stats_map.get(v["id"], {})
            duration_sec = s.get("duration_sec", 0)
            if duration_sec > max_length_min * 60:
                print(f"⏭️  Skipping {v['title'][:50]}: too long "
                      f"({duration_sec // 60}m)")
                continue
            v["views"] = s.get("views", 0)
            v["duration_sec"] = duration_sec
            v["creator_name"] = creator_name
            enriched.append(v)

        # Sort by view count (most viral first)
        enriched.sort(key=lambda x: x["views"], reverse=True)
        result = enriched[:max_results]

        print(f"✅ Found {len(result)} candidate video(s) from {creator_name}")
        return result

    except Exception as e:
        db.log_failure("fetcher.fetch_viral_videos", str(e),
                       traceback.format_exc())
        notifier.send_error("Video Fetch Failed", str(e))
        return []


# ── Video download ────────────────────────────────────────────────────────

def download_video(video: Dict) -> Optional[Path]:
    """
    Download a YouTube video with yt-dlp.
    Returns path to downloaded file, or None on failure.
    Includes auto-retry with yt-dlp update on first failure.
    """
    if not check_disk_space():
        return None

    TEMP_DIR.mkdir(exist_ok=True)
    cfg = config_manager.pipeline
    quality = cfg.get("source_video_quality", "720")
    vid_id = video["id"]
    out_template = str(TEMP_DIR / f"{vid_id}.%(ext)s")

    cookies_path = os.environ.get("YT_COOKIES_PATH", "")
    cookie_args = ["--cookies", cookies_path] if cookies_path and Path(cookies_path).exists() else []

    cmd = [
        sys.executable, "-m", "yt_dlp",
        f"https://www.youtube.com/watch?v={vid_id}",
        "--format", f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}][ext=mp4]/best",
        "--output", out_template,
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        "--merge-output-format", "mp4",
        # Force English audio/subtitles
        "--match-filter", "language='en' | !language",
    ] + cookie_args

    for attempt in range(2):
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            # Find the output file
            matches = list(TEMP_DIR.glob(f"{vid_id}.*"))
            mp4_files = [f for f in matches if f.suffix == ".mp4"]
            if mp4_files:
                print(f"✅ Downloaded: {video['title'][:60]}")
                return mp4_files[0]
            # Sometimes yt-dlp merges to mkv
            mkv_files = [f for f in matches if f.suffix in (".mkv", ".webm")]
            if mkv_files:
                return mkv_files[0]
        except subprocess.CalledProcessError as e:
            if attempt == 0:
                print("⚠️  yt-dlp failed — updating and retrying...")
                update_ytdlp()
            else:
                db.log_failure("fetcher.download", str(e), vid_id)
                notifier.send_warning("Download Failed",
                                      f"Could not download `{video['title'][:60]}`")
                return None
        except subprocess.TimeoutExpired:
            db.log_failure("fetcher.download", "Timeout after 600s", vid_id)
            return None

    return None


def cleanup_video(path: Optional[Path]):
    """Delete a temp video file immediately after use."""
    if path and path.exists():
        try:
            path.unlink()
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────

def _parse_iso_duration(duration: str) -> int:
    """Convert ISO 8601 duration (PT1H2M3S) to seconds."""
    import re
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration
    )
    if not match:
        return 0
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return h * 3600 + m * 60 + s
