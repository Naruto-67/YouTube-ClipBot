# pipeline/orchestrator.py
"""
Master pipeline orchestrator — updated with:
  - Manual queue (processed first, highest priority)
  - Clip bank (bank all clips from a video, drip-feed daily)
  - Dynamic clip count per video based on duration
  - Backlog extension when bank is low
  - Empty bank alert with no source videos found

Run order each day:
  1. Sync manual_queue.yaml into DB
  2. Process any pending manual queue entries → bank all their clips
  3. Check bank count:
     - If bank >= max_clips_per_day → skip discovery, just upload from bank
     - If bank < threshold          → run discovery to refill
     - If bank empty and no new videos → alert Discord
  4. Discovery (if needed):
     - Normal window first (30 days)
     - If still low → backlog window (90 days)
  5. For each discovered video: download → transcribe → select ALL clips → save to bank
  6. Upload max_clips_per_day from bank
  7. Send daily report
"""
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

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
            "clips_banked": 0,
            "uploaded": 0,
            "errors": 0,
            "bank_count_start": 0,
            "bank_count_end": 0,
        }

    # ── Entry point ───────────────────────────────────────────────────────

    def run(self):
        print("=" * 60)
        print(f"🚀 ClipBot starting — {datetime.now(timezone.utc).isoformat()}")
        print("=" * 60)
        TEMP_DIR.mkdir(exist_ok=True)

        try:
            fetcher.update_ytdlp()
            youtube_service, _ = fetcher.get_youtube_service()
            sub_count = scheduler.get_channel_subscriber_count(youtube_service)
            publish_times = scheduler.get_best_publish_times(youtube_service, sub_count)
            print(f"📊 Subscribers: {sub_count:,} | "
                  f"Publish windows (UTC): {publish_times}")

            cfg = config_manager.pipeline
            max_uploads = cfg.get("max_clips_per_day", 3)
            bank_threshold = cfg.get("clip_bank_low_threshold", 3)

            # ── Step 1: Manual queue ──────────────────────────────────────
            fetcher.sync_manual_queue()
            self._process_manual_queue(youtube_service)

            # ── Step 2: Check bank ────────────────────────────────────────
            bank_count = db.get_bank_count("pending")
            self.stats["bank_count_start"] = bank_count
            print(f"🏦 Clip bank: {bank_count} pending clips")

            # ── Step 3: Discovery if bank is low ─────────────────────────
            if bank_count < bank_threshold:
                print(f"📉 Bank below threshold ({bank_threshold}) — running discovery")
                self._run_discovery(youtube_service, bank_threshold)
            else:
                print(f"✅ Bank has enough clips — skipping discovery today")

            # ── Step 4: Check bank again after discovery ──────────────────
            bank_count = db.get_bank_count("pending")
            if bank_count == 0:
                notifier.send_warning(
                    "Clip Bank Empty",
                    "No clips available to upload today and no new videos found.\n"
                    "**Actions:** Add more source creators in `config/channels.yaml`, "
                    "or add a specific video to `config/manual_queue.yaml`."
                )
                print("⚠️  Clip bank empty — nothing to upload today.")
            else:
                # ── Step 5: Upload from bank ──────────────────────────────
                self._upload_from_bank(
                    max_clips=max_uploads,
                    youtube_service=youtube_service,
                    publish_times=publish_times,
                )

            self.stats["bank_count_end"] = db.get_bank_count("pending")

        except Exception as e:
            self.stats["errors"] += 1
            tb = traceback.format_exc()
            db.log_failure("orchestrator.run", str(e), tb)
            notifier.send_error("Fatal Pipeline Error", str(e), tb)

        finally:
            self._send_daily_report()

    # ── Manual queue processing ───────────────────────────────────────────

    def _process_manual_queue(self, youtube_service):
        pending = db.get_pending_manual_queue()
        if not pending:
            return
        print(f"\n📋 Manual queue: {len(pending)} pending entr(ies)")
        for entry in pending:
            print(f"   Processing: {entry.get('url', '')[:60]} "
                  f"[{entry.get('source', 'Manual')}]")
            video = fetcher.resolve_manual_queue_entry(entry, youtube_service)
            if video is None:
                continue
            # override_count from manual entry (0 = use dynamic)
            override = entry.get("max_clips", 0)
            clips_banked = self._process_video_to_bank(
                video, youtube_service, override_count=override
            )
            if clips_banked > 0:
                db.mark_queue_entry_done(entry["id"], video["id"])
            else:
                db.mark_queue_entry_failed(entry["id"])

    # ── Discovery ─────────────────────────────────────────────────────────

    def _run_discovery(self, youtube_service, bank_threshold: int):
        creators = config_manager.get_active_source_creators()
        print(f"🔍 Discovering from: {[c['name'] for c in creators]}")

        # First pass — normal window
        new_clips = 0
        for creator in creators:
            videos = fetcher.fetch_viral_videos(creator, youtube_service,
                                                extend_backlog=False)
            for video in videos:
                new_clips += self._process_video_to_bank(video, youtube_service)

        # Second pass — backlog extension if still low
        if db.get_bank_count("pending") < bank_threshold:
            print(f"📦 Still low after normal discovery — extending to backlog window")
            notifier.send_info(
                "Backlog Mode Active",
                "Bank is low — pulling from extended backlog (90 days). "
                "Consider adding more source creators."
            )
            for creator in creators:
                videos = fetcher.fetch_viral_videos(creator, youtube_service,
                                                    extend_backlog=True)
                for video in videos:
                    new_clips += self._process_video_to_bank(video, youtube_service)

        print(f"🏦 Discovery complete — {new_clips} new clips added to bank")

    # ── Process one video → save all clips to bank ────────────────────────

    def _process_video_to_bank(self, video: Dict, youtube_service,
                                override_count: int = 0) -> int:
        """
        Download → transcribe → select ALL clips → save to bank.
        Does NOT upload anything — that happens separately.
        Returns number of clips saved to bank.
        """
        vid_id = video["id"]
        title = video.get("title", "Unknown")[:60]
        creator_name = video.get("creator_name", "Unknown")

        print(f"\n{'─' * 50}")
        print(f"🎬 Processing: {title}")
        print(f"   Creator: {creator_name} | "
              f"Duration: {video.get('duration_sec', 0)/60:.1f}m | "
              f"Views: {video.get('views', 0):,}")

        self.stats["videos_checked"] += 1
        source_path: Optional[Path] = None
        clips_banked = 0

        try:
            source_path = fetcher.download_video(video)
            if source_path is None:
                db.mark_video_processed(vid_id, creator_name, title, "download_failed")
                return 0

            transcript_result = transcriber.transcribe(source_path)
            if transcript_result is None:
                db.mark_video_processed(vid_id, creator_name, title, "transcription_failed")
                return 0

            clips = clip_selector.select_clips(
                video, transcript_result, override_count=override_count
            )
            if not clips:
                db.mark_video_processed(vid_id, creator_name, title, "no_clips")
                return 0

            # Save ALL clips to bank (with their transcript words)
            source_url = video.get("url",
                f"https://www.youtube.com/watch?v={vid_id}")

            for clip in clips:
                clip_words = transcriber.get_words_in_range(
                    transcript_result,
                    clip["start_seconds"],
                    clip["end_seconds"],
                )
                db.save_clip_to_bank(
                    source_video_id=vid_id,
                    source_video_url=source_url,
                    creator_name=creator_name,
                    title=title,
                    clip=clip,
                    transcript_words=clip_words,
                )
                clips_banked += 1

            self.stats["clips_banked"] += clips_banked
            db.mark_video_processed(vid_id, creator_name, title, "banked", clips_banked)
            print(f"🏦 Banked {clips_banked} clips from: {title}")

        except Exception as e:
            self.stats["errors"] += 1
            tb = traceback.format_exc()
            db.log_failure("orchestrator.process_video", str(e), tb)
            db.mark_video_processed(vid_id, creator_name, title, "error")
            print(f"❌ Error processing {title}: {e}")

        finally:
            fetcher.cleanup_video(source_path)

        return clips_banked

    # ── Upload from bank ──────────────────────────────────────────────────

    def _upload_from_bank(self, max_clips: int, youtube_service, publish_times: List[str]):
        """
        Pull up to max_clips pending clips from the bank.
        For each: re-download source if needed → render → upload.
        Groups by source_video_id so we download each source video at most once.
        """
        pending_clips = db.get_pending_bank_clips(limit=max_clips)
        if not pending_clips:
            return

        print(f"\n📤 Uploading {len(pending_clips)} clips from bank")

        # Group clips by source video to minimise re-downloads
        by_source: Dict[str, List[Dict]] = {}
        for clip in pending_clips:
            src_id = clip["source_video_id"]
            by_source.setdefault(src_id, []).append(clip)

        uploads_done = 0
        for src_id, clips in by_source.items():
            if uploads_done >= max_clips:
                break

            source_path: Optional[Path] = None
            try:
                # Re-download source video
                video_stub = {
                    "id": src_id,
                    "title": clips[0].get("title", ""),
                    "creator_name": clips[0]["creator_name"],
                    "url": clips[0].get("source_video_url",
                           f"https://www.youtube.com/watch?v={src_id}"),
                }
                source_path = fetcher.download_video(video_stub)
                if source_path is None:
                    for c in clips:
                        db.mark_bank_clip_failed(c["id"])
                    continue

                for bank_clip in clips:
                    if uploads_done >= max_clips:
                        break

                    clip_spec = {
                        "start_seconds": bank_clip["start_seconds"],
                        "end_seconds": bank_clip["end_seconds"],
                        "clip_type": bank_clip["clip_type"],
                        "hook_text": bank_clip["hook_text"],
                        "confidence": bank_clip["confidence"],
                        "reason": bank_clip.get("reason", ""),
                    }

                    success = self._render_and_upload(
                        bank_clip_id=bank_clip["id"],
                        clip=clip_spec,
                        source_path=source_path,
                        transcript_words=bank_clip["transcript_words"],
                        creator_name=bank_clip["creator_name"],
                        source_video_id=src_id,
                        youtube_service=youtube_service,
                        publish_times=publish_times,
                    )
                    if success:
                        uploads_done += 1
                        self.stats["uploaded"] += 1

            except Exception as e:
                self.stats["errors"] += 1
                db.log_failure("orchestrator.upload_from_bank", str(e),
                               traceback.format_exc()[-500:])
                print(f"❌ Bank upload error for {src_id}: {e}")
            finally:
                fetcher.cleanup_video(source_path)

    def _render_and_upload(self, bank_clip_id: int, clip: Dict,
                            source_path: Path, transcript_words: List[Dict],
                            creator_name: str, source_video_id: str,
                            youtube_service, publish_times: List[str]) -> bool:
        clip_id = f"{source_video_id}_{int(clip['start_seconds'])}"
        short_path = None
        hook_path = None

        try:
            hook_path = voiceover.generate_hook(clip, clip_id)

            short_path = renderer.render_short(
                source_path=source_path,
                clip=clip,
                transcript_words=transcript_words,
                hook_audio_path=hook_path,
            )
            if short_path is None:
                db.mark_bank_clip_failed(bank_clip_id)
                return False

            passed, reason = quality_checker.check_video(short_path)
            if not passed:
                print(f"  ❌ Video QC failed: {reason}")
                db.log_failure("quality_checker", reason, clip_id)
                db.mark_bank_clip_failed(bank_clip_id)
                return False
            print(f"  ✅ Video QC: {reason}")

            # Build minimal transcript dict for SEO
            fake_transcript = {"words": transcript_words, "duration": clip["end_seconds"]}
            seo = seo_generator.generate_seo(clip, fake_transcript, creator_name)

            transcript_excerpt = " ".join(w["word"] for w in transcript_words[:80])
            qc_result = quality_checker.check_metadata(seo, transcript_excerpt)
            seo = qc_result["seo"]

            publish_slot = scheduler.pick_next_slot(publish_times)

            yt_id = uploader.upload_short(
                video_path=short_path,
                seo=seo,
                scheduled_at=publish_slot,
                source_video_id=source_video_id,
                creator_name=creator_name,
                youtube_service=youtube_service,
            )

            if yt_id:
                db.mark_bank_clip_uploaded(bank_clip_id)
                return True
            else:
                db.mark_bank_clip_failed(bank_clip_id)
                return False

        except Exception as e:
            self.stats["errors"] += 1
            db.log_failure("orchestrator.render_upload", str(e),
                           traceback.format_exc()[-500:])
            db.mark_bank_clip_failed(bank_clip_id)
            print(f"  ❌ Render/upload error: {e}")
            return False

        finally:
            voiceover.cleanup_hook(hook_path)
            renderer.cleanup_short(short_path)

    # ── Reporting ─────────────────────────────────────────────────────────

    def _send_daily_report(self):
        quota_report = quota_manager.get_status_report()
        ai_report = db.get_ai_reliability_today()
        self.stats["bank_count_end"] = db.get_bank_count("pending")
        notifier.send_daily_report(self.stats, quota_report, ai_report)
        print(f"\n📋 Daily report sent to Discord.")
        print(f"   Uploaded: {self.stats['uploaded']} | "
              f"Banked: {self.stats['clips_banked']} | "
              f"Bank remaining: {self.stats['bank_count_end']}")
