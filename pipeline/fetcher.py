# pipeline/fetcher.py
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    except subprocess.CalledProcessError:
        print("⚠️  yt-dlp update failed (continuing with current version)")


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


# ── Full video download (Whisper fallback only) ───────────────────────────

def download_video(video: Dict) -> Optional[Path]:
    """
    Download the full video — only used as fallback when YouTube captions
    are unavailable and Whisper transcription is needed.
    """
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

    if cookie_args:
        print(f"🍪 Using cookies from: {cookies_path}")
    else:
        print(f"⚠️  No cookie file found at '{cookies_path}' — downloading without auth")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        f"https://www.youtube.com/watch?v={vid_id}",
        "--format",
        f"bestvideo[height<={quality}][ext=mp4][vcodec!*=av01]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={quality}][vcodec!*=av01]+bestaudio"
        f"/best[height<={quality}][ext=mp4]/best",
        "--output", out_template,
        "--no-playlist",
        "--merge-output-format", "mp4",
        "--js-runtimes", "node",
    ] + cookie_args

    for attempt in range(2):
        try:
            subprocess.run(
                cmd, check=True, capture_output=True, timeout=600, text=True
            )
            matches = list(TEMP_DIR.glob(f"{vid_id}.*"))
            mp4_files = [f for f in matches if f.suffix == ".mp4"]
            if mp4_files:
                print(f"✅ Downloaded: {video.get('title', vid_id)[:60]}")
                return mp4_files[0]
            other = [f for f in matches if f.suffix in (".mkv", ".webm")]
            if other:
                return other[0]
        except subprocess.CalledProcessError as e:
            stderr_out = (e.stderr or "").strip()
            stdout_out = (e.stdout or "").strip()
            error_detail = stderr_out or stdout_out or "no output captured"
            if attempt == 0:
                print(f"⚠️  yt-dlp failed (attempt 1) — error: {error_detail[:800]}")
                print("   Updating yt-dlp and retrying...")
                update_ytdlp()
            else:
                print(f"❌ yt-dlp failed (attempt 2) — error: {error_detail[:800]}")
                db.log_failure(
                    "fetcher.download",
                    f"yt-dlp failed after update: {error_detail[:500]}",
                    vid_id
                )
                notifier.send_warning(
                    "Download Failed",
                    f"Could not download `{video.get('title', vid_id)[:60]}`\n"
                    f"Error: {error_detail[:200]}"
                )
                return None
        except subprocess.TimeoutExpired:
            print(f"❌ yt-dlp timed out after 600s for {vid_id}")
            db.log_failure("fetcher.download", "Timeout after 600s", vid_id)
            return None
    return None


# ── Segment download (used at render time) ────────────────────────────────

def download_clip_segment(video_id: str,
                           clip_start: float,
                           clip_end: float,
                           buffer_sec: float = 6.0) -> Tuple[Optional[Path], float]:
    """
    Download only the clip segment + a buffer of lead-in context.

    This is used instead of re-downloading the full video at render time.
    A ~50-60 second file download vs a ~300MB full video — much less likely
    to hit CDN IP blocks on Azure-hosted runners.

    Args:
        video_id:   YouTube video ID
        clip_start: Absolute start time of clip in original video (seconds)
        clip_end:   Absolute end time of clip in original video (seconds)
        buffer_sec: Lead-in buffer before clip_start for natural context

    Returns:
        (path_to_segment, segment_start_seconds)
        segment_start_seconds tells the renderer where the file begins
        in absolute video time so it can offset its ffmpeg timestamps.
        Returns (None, 0.0) on failure.
    """
    if not check_disk_space():
        return None, 0.0

    TEMP_DIR.mkdir(exist_ok=True)

    # Calculate segment bounds
    seg_start = max(0.0, clip_start - buffer_sec)
    seg_end = clip_end  # no end buffer needed

    vid_url = f"https://www.youtube.com/watch?v={video_id}"
    # Unique filename includes timestamps to avoid collisions between clips
    seg_filename = f"{video_id}_{int(seg_start)}_{int(seg_end)}"
    out_template = str(TEMP_DIR / f"{seg_filename}.%(ext)s")

    cfg = config_manager.pipeline
    quality = cfg.get("source_video_quality", "720")

    cookies_path = os.environ.get("YT_COOKIES_PATH", "")
    cookie_args = (
        ["--cookies", cookies_path]
        if cookies_path and Path(cookies_path).exists()
        else []
    )

    # --download-sections tells yt-dlp to only fetch the specified time range
    # Format: "*START-END" where times are in seconds
    section_spec = f"*{seg_start}-{seg_end}"

    cmd = [
        sys.executable, "-m", "yt_dlp",
        vid_url,
        "--format",
        f"bestvideo[height<={quality}][ext=mp4][vcodec!*=av01]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={quality}][vcodec!*=av01]+bestaudio"
        f"/best[height<={quality}][ext=mp4]/best",
        "--output", out_template,
        "--no-playlist",
        "--merge-output-format", "mp4",
        "--download-sections", section_spec,
        "--js-runtimes", "node",
    ] + cookie_args

    seg_duration = seg_end - seg_start
    print(f"⬇️  Downloading clip segment: "
          f"{seg_start:.1f}s → {seg_end:.1f}s ({seg_duration:.0f}s)")

    for attempt in range(2):
        try:
            subprocess.run(
                cmd, check=True, capture_output=True, timeout=120, text=True
            )
            matches = list(TEMP_DIR.glob(f"{seg_filename}.*"))
            mp4_files = [f for f in matches if f.suffix == ".mp4"]
            if mp4_files:
                print(f"✅ Segment downloaded: {mp4_files[0].name}")
                return mp4_files[0], seg_start
            other = [f for f in matches if f.suffix in (".mkv", ".webm")]
            if other:
                return other[0], seg_start

        except subprocess.CalledProcessError as e:
            stderr_out = (e.stderr or "").strip()
            error_detail = stderr_out or "no output captured"
            if attempt == 0:
                print(f"⚠️  Segment download failed (attempt 1): {error_detail[:400]}")
                print("   Updating yt-dlp and retrying...")
                update_ytdlp()
            else:
                print(f"❌ Segment download failed (attempt 2): {error_detail[:400]}")
                db.log_failure(
                    "fetcher.download_segment",
                    f"Segment download failed: {error_detail[:300]}",
                    video_id
                )
                return None, 0.0

        except subprocess.TimeoutExpired:
            print(f"❌ Segment download timed out after 120s for {video_id}")
            db.log_failure("fetcher.download_segment", "Timeout after 120s", video_id)
            return None, 0.0

    return None, 0.0


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
