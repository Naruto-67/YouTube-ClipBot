# pipeline/fetcher.py
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from engine.config_manager import config_manager
from engine.database import db
from engine.discord_notifier import notifier
from engine.quota_manager import quota_manager

ROOT = Path(__file__).parent.parent
TEMP_DIR = ROOT / "temp"


def _build_youtube_service():
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
    return _build_youtube_service()


def check_disk_space() -> bool:
    cfg = config_manager.pipeline
    min_gb = cfg.get("min_disk_free_gb", 3)
    stat = shutil.disk_usage(ROOT)
    free_gb = stat.free / (1024 ** 3)
    if free_gb < min_gb:
        notifier.send_warning(
            "Low Disk Space",
            f"Only {free_gb:.1f} GB free. Minimum: {min_gb} GB. Skipping download."
        )
        return False
    return True


def update_ytdlp():
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp", "-q"],
            check=True, capture_output=True
        )
        print("✅ yt-dlp updated")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  yt-dlp update failed (continuing with current version)")


# ── Manual queue ──────────────────────────────────────────────────────────

def sync_manual_queue():
    """Load manual_queue.yaml into DB. Returns count of pending entries."""
    cfg = config_manager.pipeline
    queue_file = ROOT / cfg.get("manual_queue_file", "config/manual_queue.yaml")
    if not queue_file.exists():
        return 0
    try:
        data = yaml.safe_load(queue_file.read_text())
        entries = data.get("videos", []) if data else []
        # Only sync pending entries from YAML
        pending = [e for e in entries if e.get("status", "pending") == "pending"]
        if pending:
            db.sync_manual_queue_from_yaml(pending)
        return db.get_bank_count("pending")
    except Exception as e:
        print(f"⚠️  Could not load manual_queue.yaml: {e}")
        return 0


def extract_video_id_from_url(url: str) -> Optional[str]:
    """Extract YouTube video ID from any YouTube URL format."""
    import re
    patterns = [
        r"(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def resolve_manual_queue_entry(entry: Dict, youtube_service) -> Optional[Dict]:
    """
    Convert a manual queue entry into the same video dict format
    used by fetch_viral_videos, so it flows through the same pipeline.
    """
    url = entry.get("url", "")
    video_id = extract_video_id_from_url(url)
    if not video_id:
        print(f"⚠️  Could not extract video ID from: {url}")
        db.mark_queue_entry_failed(entry["id"])
        return None

    if db.is_video_processed(video_id):
        print(f"ℹ️  Manual queue: {video_id} already processed — skipping")
        db.mark_queue_entry_done(entry["id"], video_id)
        return None

    # Fetch video metadata
    can, reason = quota_manager.can_use_youtube(units=1)
    if not can:
        print(f"⚠️  YouTube quota: {reason}")
        return None

    try:
        resp = youtube_service.videos().list(
            part="snippet,contentDetails,statistics", id=video_id
        ).execute()
        quota_manager.record_youtube(
            config_manager.get_yt_unit_cost("videos_list"), "videos_list"
        )
        if not resp.get("items"):
            print(f"⚠️  Video not found: {video_id}")
            db.mark_queue_entry_failed(entry["id"])
            return None

        item = resp["items"][0]
        duration_sec = _parse_iso_duration(
            item.get("contentDetails", {}).get("duration", "PT0S")
        )
        return {
            "id": video_id,
            "title": item["snippet"].get("title", "Unknown"),
            "views": int(item.get("statistics", {}).get("viewCount", 0)),
            "duration_sec": duration_sec,
            "creator_name": entry.get("creator_name", "Unknown"),
            "url": url,
            "manual_queue_id": entry["id"],
            "manual_max_clips": entry.get("max_clips", 0),
        }
    except Exception as e:
        db.log_failure("fetcher.resolve_manual", str(e), traceback.format_exc())
        return None


# ── Auto-discovery ────────────────────────────────────────────────────────

def fetch_viral_videos(creator: Dict, youtube_service,
                       extend_backlog: bool = False) -> List[Dict]:
    """
    Fetch recently viral videos from a creator's uploads playlist.
    If extend_backlog=True, uses the longer backlog window (90 days).
    Cost: ~3 YouTube API units total.
    """
    cfg = config_manager.pipeline
    if extend_backlog:
        max_age_days = cfg.get("backlog_max_age_days", 90)
        print(f"🔍 Extended backlog mode ({max_age_days} days) for {creator['name']}")
    else:
        max_age_days = cfg.get("max_video_age_days", 30)

    max_length_min = cfg.get("max_video_length_minutes", 90)
    max_results = creator.get("max_videos_per_run", 2)
    channel_id = creator["channel_id"]
    creator_name = creator["name"]

    can, reason = quota_manager.can_use_youtube(units=4)
    if not can:
        print(f"⚠️  YouTube quota: {reason}")
        return []

    try:
        # Get uploads playlist ID
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

        # Get recent uploads
        pl_resp = youtube_service.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=50
        ).execute()
        quota_manager.record_youtube(
            config_manager.get_yt_unit_cost("playlist_items_list"),
            "playlist_items_list"
        )

        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        candidates = []

        for item in pl_resp.get("items", []):
            snippet = item["snippet"]
            vid_id = snippet["resourceId"]["videoId"]
            title = snippet.get("title", "")
            published_str = snippet.get("publishedAt", "")

            if db.is_video_processed(vid_id):
                continue
            # Also skip if already in the clip bank (processed but clips still pending)
            if vid_id in db.get_pending_source_video_ids():
                continue

            if published_str:
                pub_dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                if pub_dt < cutoff:
                    continue

            candidates.append({"id": vid_id, "title": title,
                                "published": published_str})

        if not candidates:
            print(f"ℹ️  No new videos for {creator_name}")
            return []

        # Get view counts + duration
        vid_ids = [v["id"] for v in candidates[:50]]
        stats_resp = youtube_service.videos().list(
            part="statistics,contentDetails", id=",".join(vid_ids)
        ).execute()
        quota_manager.record_youtube(
            config_manager.get_yt_unit_cost("videos_list"), "videos_list"
        )

        stats_map = {}
        for item in stats_resp.get("items", []):
            vid_id = item["id"]
            views = int(item.get("statistics", {}).get("viewCount", 0))
            duration_sec = _parse_iso_duration(
                item.get("contentDetails", {}).get("duration", "PT0S")
            )
            stats_map[vid_id] = {"views": views, "duration_sec": duration_sec}

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
            v["url"] = f"https://www.youtube.com/watch?v={v['id']}"
            enriched.append(v)

        enriched.sort(key=lambda x: x["views"], reverse=True)
        result = enriched[:max_results]
        print(f"✅ Found {len(result)} candidate video(s) from {creator_name}")
        return result

    except Exception as e:
        db.log_failure("fetcher.fetch_viral_videos", str(e), traceback.format_exc())
        notifier.send_error("Video Fetch Failed", str(e))
        return []


# ── Download ─────────────────────────────────────────────────────────────

def download_video(video: Dict) -> Optional[Path]:
    if not check_disk_space():
        return None

    TEMP_DIR.mkdir(exist_ok=True)
    cfg = config_manager.pipeline
    quality = cfg.get("source_video_quality", "720")
    vid_id = video["id"]
    out_template = str(TEMP_DIR / f"{vid_id}.%(ext)s")

    cookies_path = os.environ.get("YT_COOKIES_PATH", "")
    cookie_args = (
        ["--cookies", cookies_path]
        if cookies_path and Path(cookies_path).exists()
        else []
    )

    cmd = [
        sys.executable, "-m", "yt_dlp",
        f"https://www.youtube.com/watch?v={vid_id}",
        "--format",
        f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]"
        f"/best[height<={quality}][ext=mp4]/best",
        "--output", out_template,
        "--no-playlist", "--no-warnings", "--quiet",
        "--merge-output-format", "mp4",
    ] + cookie_args

    for attempt in range(2):
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            matches = list(TEMP_DIR.glob(f"{vid_id}.*"))
            mp4_files = [f for f in matches if f.suffix == ".mp4"]
            if mp4_files:
                print(f"✅ Downloaded: {video.get('title', vid_id)[:60]}")
                return mp4_files[0]
            other = [f for f in matches if f.suffix in (".mkv", ".webm")]
            if other:
                return other[0]
        except subprocess.CalledProcessError:
            if attempt == 0:
                print("⚠️  yt-dlp failed — updating and retrying...")
                update_ytdlp()
            else:
                db.log_failure("fetcher.download", "yt-dlp failed after update", vid_id)
                notifier.send_warning(
                    "Download Failed",
                    f"Could not download `{video.get('title', vid_id)[:60]}`"
                )
                return None
        except subprocess.TimeoutExpired:
            db.log_failure("fetcher.download", "Timeout after 600s", vid_id)
            return None
    return None


def cleanup_video(path: Optional[Path]):
    if path and path.exists():
        try:
            path.unlink()
        except Exception:
            pass


def _parse_iso_duration(duration: str) -> int:
    import re
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return h * 3600 + m * 60 + s
