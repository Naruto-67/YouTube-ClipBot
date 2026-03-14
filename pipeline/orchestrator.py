# pipeline/orchestrator.py
"""
Main pipeline orchestrator.

Run order per video:
  1. Fetch viral videos from each active source creator
  2. Download source video
  3. Transcribe (Whisper)
  4. AI clip selection
  5. For each clip:
     a. Generate hook voiceover
     b. Render short (FFmpeg)
     c. Generate SEO
     d. Quality check
     e. Schedule
     f. Upload
  6. Cleanup temp files
  7. Send daily Discord report

Safety:
  - Exception in one video/clip never kills the whole run
  - Disk + quota checks before expensive operations
  - All state persisted to SQLite after each step
"""
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from engine.config_manager import config_manager
from engine.database import db
from engine.discord_notifier import notifier
from engine.quota_manager import quota_manager
from pipeline import clip_selector
from pipeline import fetcher
from pipeline import quality_checker
from pipeline import renderer
from pipeline import scheduler
from pipeline import seo_generator
from pipeline import transcriber
from pipeline import uploader
from pipeline import voiceover

ROOT = Path(__file__).parent.parent
TEMP_DIR = ROOT / "temp"


class Orchestrator:
    def __init__(self):
        self.stats = {
            "videos_checked": 0,
            "clips_attempted": 0,
            "uploaded": 0,
            "errors": 0,
        }

    # ── Entry point ───────────────────────────────────────────────────────

    def run(self):
        print("=" * 60)
        print(f"🚀 ClipBot starting — {datetime.now(timezone.utc).isoformat()}")
        print("=" * 60)

        TEMP_DIR.mkdir(exist_ok=True)

        try:
            # Update yt-dlp at the start of every run
            fetcher.update_ytdlp()

            youtube_service, _ = fetcher.get_youtube_service()
            sub_count = scheduler.get_channel_subscriber_count(youtube_service)
            print(f"📊 Channel subscribers: {sub_count:,}")

            publish_times = scheduler.get_best_publish_times(youtube_service, sub_count)
            print(f"📅 Publish windows (UTC): {publish_times}")

            creators = config_manager.get_active_source_creators()
            print(f"🎬 Active source creators: {[c['name'] for c in creators]}")

            cfg = config_manager.pipeline
            max_uploads = cfg.get("max_clips_per_day", 3)
            uploads_today = 0

            for creator in creators:
                if uploads_today >= max_uploads:
                    print(f"ℹ️  Daily upload cap ({max_uploads}) reached — stopping.")
                    break

                remaining = max_uploads - uploads_today
                videos = fetcher.fetch_viral_videos(creator, youtube_service)

                for video in videos:
                    if uploads_today >= max_uploads:
                        break

                    clips_made = self._process_video(
                        video, creator, youtube_service, publish_times,
                        max_clips=remaining,
                    )
                    uploads_today += clips_made

        except Exception as e:
            self.stats["errors"] += 1
            tb = traceback.format_exc()
            db.log_failure("orchestrator.run", str(e), tb)
            notifier.send_error("Fatal Pipeline Error", str(e), tb)

        finally:
            self._send_daily_report()

    # ── Per-video logic ───────────────────────────────────────────────────

    def _process_video(
        self,
        video: Dict,
        creator: Dict,
        youtube_service,
        publish_times: List[str],
        max_clips: int,
    ) -> int:
        """Process one source video. Returns number of clips uploaded."""
        vid_id = video["id"]
        title = video.get("title", "Unknown")[:60]
        creator_name = creator["name"]

        print(f"\n{'─' * 50}")
        print(f"🎬 Processing: {title}")
        print(f"   Creator: {creator_name} | Views: {video.get('views', 0):,}")

        self.stats["videos_checked"] += 1
        source_path: Path | None = None
        clips_uploaded = 0

        try:
            # Download
            source_path = fetcher.download_video(video)
            if source_path is None:
                db.mark_video_processed(vid_id, creator_name, title, "download_failed")
                return 0

            # Transcribe
            transcript = transcriber.transcribe(source_path)
            if transcript is None:
                db.mark_video_processed(vid_id, creator_name, title, "transcription_failed")
                return 0

            # Select clips
            clips = clip_selector.select_clips(video, transcript)
            if not clips:
                db.mark_video_processed(vid_id, creator_name, title, "no_clips")
                return 0

            clips = clips[:max_clips]

            for i, clip in enumerate(clips):
                print(f"\n  📎 Clip {i + 1}/{len(clips)}: "
                      f"[{clip['start_seconds']:.0f}s → {clip['end_seconds']:.0f}s] "
                      f"{clip['clip_type']}")
                self.stats["clips_attempted"] += 1

                success = self._process_clip(
                    clip=clip,
                    video=video,
                    source_path=source_path,
                    transcript=transcript,
                    creator_name=creator_name,
                    youtube_service=youtube_service,
                    publish_times=publish_times,
                )
                if success:
                    clips_uploaded += 1
                    self.stats["uploaded"] += 1

            db.mark_video_processed(
                vid_id, creator_name, title, "done", clips_uploaded
            )

        except Exception as e:
            self.stats["errors"] += 1
            tb = traceback.format_exc()
            db.log_failure("orchestrator.process_video", str(e), tb)
            db.mark_video_processed(vid_id, creator_name, title, "error")
            print(f"❌ Unexpected error on {title}: {e}")

        finally:
            # Always delete source video immediately after processing
            fetcher.cleanup_video(source_path)

        return clips_uploaded

    # ── Per-clip logic ────────────────────────────────────────────────────

    def _process_clip(
        self,
        clip: Dict,
        video: Dict,
        source_path: Path,
        transcript: Dict,
        creator_name: str,
        youtube_service,
        publish_times: List[str],
    ) -> bool:
        """
        Full pipeline for one clip.
        Returns True if uploaded successfully.
        """
        clip_id = f"{video['id']}_{int(clip['start_seconds'])}"
        short_path = None
        hook_path = None

        try:
            # Generate voiceover hook (non-fatal if it fails)
            hook_path = voiceover.generate_hook(clip, clip_id)

            # Get transcript words for this clip
            clip_words = transcriber.get_words_in_range(
                transcript,
                clip["start_seconds"],
                clip["end_seconds"],
            )

            # Render
            short_path = renderer.render_short(
                source_path=source_path,
                clip=clip,
                transcript_words=clip_words,
                hook_audio_path=hook_path,
            )
            if short_path is None:
                return False

            # Technical QC
            passed, reason = quality_checker.check_video(short_path)
            if not passed:
                print(f"  ❌ Video QC failed: {reason}")
                db.log_failure("quality_checker", reason, clip_id)
                return False
            print(f"  ✅ Video QC: {reason}")

            # Generate SEO
            seo = seo_generator.generate_seo(clip, transcript, creator_name)

            # Metadata QC + auto-fix
            transcript_excerpt = " ".join(
                w["word"] for w in clip_words[:80]
            )
            qc_result = quality_checker.check_metadata(seo, transcript_excerpt)
            seo = qc_result["seo"]  # Use potentially fixed version

            # Schedule
            publish_slot = scheduler.pick_next_slot(publish_times)

            # Upload
            yt_id = uploader.upload_short(
                video_path=short_path,
                seo=seo,
                scheduled_at=publish_slot,
                source_video_id=video["id"],
                creator_name=creator_name,
                youtube_service=youtube_service,
            )
            return yt_id is not None

        except Exception as e:
            self.stats["errors"] += 1
            db.log_failure("orchestrator.process_clip", str(e),
                           traceback.format_exc()[-500:])
            print(f"  ❌ Clip processing error: {e}")
            return False

        finally:
            # Clean up temp files regardless of outcome
            voiceover.cleanup_hook(hook_path)
            renderer.cleanup_short(short_path)

    # ── Reporting ─────────────────────────────────────────────────────────

    def _send_daily_report(self):
        quota_report = quota_manager.get_status_report()
        ai_report = db.get_ai_reliability_today()
        notifier.send_daily_report(self.stats, quota_report, ai_report)
        print("\n📋 Daily report sent to Discord.")
        print(f"   Uploaded: {self.stats['uploaded']} | "
              f"Errors: {self.stats['errors']}")
