# pipeline/orchestrator.py
"""
Master pipeline orchestrator — updated with:
  - TEST_MODE: dry-run pipeline with no YouTube quota consumption
  - Dedup: never re-discover videos with banked clips
  - Sentence-boundary snapping for narrative coherence
  - Manual queue entry failure marking fix
  - Auto model discovery
"""
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from engine.config_manager import config_manager
from engine.database import db
from engine.discord_notifier import notifier
from engine.quota_manager import quota_manager
from engine.model_discovery import get_effective_models
from pipeline import clip_selector
from pipeline import fetcher
from pipeline import quality_checker
from pipeline import renderer
from pipeline import scheduler
from pipeline import seo_generator
from pipeline import transcriber
from pipeline import uploader
from pipeline import voiceover
from pipeline import video_guardian
from pipeline import trend_researcher
from pipeline import channel_scorer

ROOT = Path(__file__).parent.parent
TEMP_DIR = ROOT / "temp"
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"


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
        self._trending_context = None  # set during run(), shared across pipeline

    # ── Entry point ───────────────────────────────────────────────────────

    def run(self):
        print("=" * 60)
        mode_tag = "🧪 [TEST MODE] " if TEST_MODE else ""
        print(f"{mode_tag}🚀 ClipBot starting — {datetime.now(timezone.utc).isoformat()}")
        if TEST_MODE:
            print("   No YouTube API calls, no quota consumed, simulated uploads.")
        print("=" * 60)
        TEMP_DIR.mkdir(exist_ok=True)

        # ── Log discovered models if enabled ────────────────────────────────
        if not TEST_MODE:
            try:
                models = get_effective_models()
                for m in models:
                    disc = "🔬" if m.get("discovered") else "   "
                    print(f"   {disc} Model: {m['name']} (tier {m['tier']})")
            except Exception:
                pass

        try:
            if TEST_MODE:
                # TEST_MODE: no YouTube services needed
                youtube_service = None
                sub_count = 100
                publish_times = scheduler.get_best_publish_times(None, sub_count)
            else:
                youtube_service, _ = fetcher.get_youtube_service()
                sub_count = scheduler.get_channel_subscriber_count(youtube_service)
                publish_times = scheduler.get_best_publish_times(youtube_service, sub_count)

            print(f"📊 Subscribers: {sub_count:,} | "
                  f"Publish windows (UTC): {publish_times}")

            cfg = config_manager.pipeline
            max_uploads = cfg.get("max_clips_per_day", 6)
            bank_threshold = cfg.get("clip_bank_low_threshold", 12)

            # ── Step 0: Video Guardian ─────────────────────────────────────
            # Check all recent uploads for removals/rejections BEFORE doing
            # anything else. Catches policy issues from previous run.
            if not TEST_MODE and cfg.get("run_video_guardian", True):
                guardian_report = video_guardian.monitor_uploaded_videos(youtube_service)
                self.stats["guardian_removed"] = guardian_report.deleted
                self.stats["guardian_rejected"] = guardian_report.rejected
            else:
                print("ℹ️  Video guardian skipped (TEST_MODE or disabled)")

            # ── Step 1: Trend Research ─────────────────────────────────────
            # Fetch trending context once per run and reuse across all SEO calls.
            self._trending_context = trend_researcher.get_trending_context(
                youtube_service if not TEST_MODE else None
            )

            # ── Step 2: Manual queue ──────────────────────────────────────
            fetcher.sync_manual_queue()
            self._process_manual_queue(youtube_service)

            # ── Step 3: Check bank ────────────────────────────────────────
            bank_count = db.get_bank_count("pending")
            self.stats["bank_count_start"] = bank_count
            print(f"🏦 Clip bank: {bank_count} pending clips")

            # ── Step 4: Discovery if bank is low ─────────────────────────
            if bank_count < bank_threshold:
                print(f"📉 Bank below threshold ({bank_threshold}) — running discovery")
                self._run_discovery(youtube_service, bank_threshold)
            else:
                print(f"✅ Bank has enough clips — skipping discovery today")

            # ── Step 5: Check bank again after discovery ──────────────────
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
                # ── Step 6: Upload from bank ──────────────────────────────
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
                # BUG FIX: entry was NOT marked as failed when resolve returned None
                # (e.g. quota exhausted, video not found). Now mark it.
                db.mark_queue_entry_failed(entry["id"])
                continue
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

        # Dynamically score creators and allocate the discovery video budget
        discovery_budget = config_manager.pipeline.get("discovery_video_budget", 8)
        creators = channel_scorer.score_and_allocate(creators,
                                                     total_budget=discovery_budget)
        print(f"🔍 Discovering from: "
              + ", ".join(f"{c['name']}({c['max_videos_per_run']}v)"
                         for c in creators))

        new_clips = 0
        for creator in creators:
            videos = fetcher.fetch_viral_videos(creator, youtube_service,
                                                extend_backlog=False)
            for video in videos:
                new_clips += self._process_video_to_bank(video, youtube_service)

        if db.get_bank_count("pending") < bank_threshold:
            print(f"📦 Still low after normal discovery — extending to backlog window")
            notifier.send_info(
                "Backlog Mode Active",
                "Bank is low — pulling from extended backlog. "
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
        Get transcript → select ALL clips → save to bank.

        Transcript strategy:
          1. Try youtube-transcript-api (instant, no download, no CDN)
          2. If unavailable → yt-dlp full download + Whisper (old path)

        Does NOT upload anything — that happens separately in _upload_from_bank.
        Returns number of clips saved to bank.
        """
        vid_id = video["id"]
        title = video.get("title", "Unknown")[:60]
        creator_name = video.get("creator_name", "Unknown")
        duration_sec = video.get("duration_sec", 0)

        print(f"\n{'─' * 50}")
        print(f"🎬 Processing: {title}")
        print(f"   Creator: {creator_name} | "
              f"Duration: {duration_sec/60:.1f}m | "
              f"Views: {video.get('views', 0):,}")

        self.stats["videos_checked"] += 1
        source_path: Optional[Path] = None
        audio_path: Optional[Path] = None
        clips_banked = 0

        try:
            # ── Step 1: Get transcript ────────────────────────────────
            cfg = config_manager.pipeline
            prefer_captions = cfg.get("prefer_captions", True)
            transcript_result = None

            if prefer_captions:
                print(f"📝 Trying YouTube caption API...")
                transcript_result = transcriber.get_transcript_via_api(
                    vid_id, duration_sec
                )

            if transcript_result is None:
                # Caption API failed/disabled → try Groq cloud Whisper (audio-only
                # download, no local model, fast). Fall back to local Whisper last.
                print(f"⬇️  Captions unavailable — trying Groq Whisper "
                      f"(audio-only download)")
                audio_path = fetcher.download_audio_only(video)
                if audio_path is not None:
                    transcript_result = transcriber.get_transcript_via_groq(
                        audio_path, duration_sec
                    )
                if transcript_result is None:
                    # Last resort: full video + local faster-whisper
                    if prefer_captions:
                        print(f"⬇️  Groq transcription unavailable — falling back to "
                              f"yt-dlp + Whisper (this will take ~{duration_sec/60:.0f} min)")
                    source_path = fetcher.download_video(video)
                    if source_path is None:
                        db.mark_video_processed(vid_id, creator_name, title,
                                                "download_failed")
                        return 0

                    transcript_result = transcriber.transcribe(source_path)
                    if transcript_result is None:
                        db.mark_video_processed(vid_id, creator_name, title,
                                                "transcription_failed")
                        return 0

            # ── Step 2: Select clips ──────────────────────────────────
            # Pass early_stop_at so _select_chunked stops processing chunks
            # once we have enough clips to fill the bank — saves LLM calls.
            cfg = config_manager.pipeline
            bank_threshold = cfg.get("clip_bank_low_threshold", 3)
            current_bank = db.get_bank_count("pending")
            clips_needed = max(1, bank_threshold - current_bank + 1)

            clips = clip_selector.select_clips(
                video, transcript_result,
                override_count=override_count,
                early_stop_at=clips_needed if override_count == 0 else 0,
            )
            if not clips:
                db.mark_video_processed(vid_id, creator_name, title, "no_clips")
                return 0

            # ── Step 3: Save ALL clips to bank, skip duplicates ────────
            source_url = video.get("url",
                f"https://www.youtube.com/watch?v={vid_id}")

            for clip in clips:
                # ── NEW: Skip if this exact clip range is already banked ──
                if db.has_banked_clip(vid_id, clip["start_seconds"],
                                       clip["end_seconds"]):
                    print(f"   ⏭️  Skipping duplicate clip [{clip['start_seconds']:.1f}s→"
                          f"{clip['end_seconds']:.1f}s] — already in bank")
                    continue

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
            db.mark_video_processed(vid_id, creator_name, title,
                                    "banked", clips_banked)
            print(f"🏦 Banked {clips_banked} clips from: {title}")

        except Exception as e:
            self.stats["errors"] += 1
            tb = traceback.format_exc()
            db.log_failure("orchestrator.process_video", str(e), tb)
            db.mark_video_processed(vid_id, creator_name, title, "error")
            print(f"❌ Error processing {title}: {e}")

        finally:
            # Clean up any downloaded full video AND audio-only file
            fetcher.cleanup_video(source_path)
            fetcher.cleanup_video(audio_path)

        return clips_banked

    # ── Upload from bank ──────────────────────────────────────────────────

    def _upload_from_bank(self, max_clips: int, youtube_service,
                           publish_times: List[str]):
        """
        Pull up to max_clips pending clips from the bank.
        For each: download the specific clip segment (not full video)
        → render → upload.

        Using segment downloads instead of full video downloads:
        - ~50-60s file vs ~300MB full video
        - Much less likely to hit CDN IP blocks on Azure
        - No grouping by source needed since each segment is different timestamps
        """
        # Quick empty-bank check before entering the diversity loop
        if db.get_bank_count("pending") == 0:
            return

        print(f"\n📤 Uploading up to {max_clips} clips from bank (content-diverse)")

        cfg = config_manager.pipeline
        buffer_sec = float(cfg.get("transcript_buffer_seconds", 6))

        uploads_done = 0
        last_source_id = None
        # Loop until we've uploaded max_clips. Each iteration asks the bank for
        # a clip from a DIFFERENT source video than the previous one (diversity),
        # falling back if every pending clip is from the excluded source.
        while uploads_done < max_clips:
            # Exclude the source video we just uploaded from, if any
            exclude = [last_source_id] if last_source_id else None
            bank_clip = db.get_pending_bank_clips(
                limit=1, exclude_source_ids=exclude
            )
            if not bank_clip:
                break  # bank exhausted
            bank_clip = bank_clip[0]

            src_id = bank_clip["source_video_id"]
            clip_start = bank_clip["start_seconds"]
            clip_end = bank_clip["end_seconds"]

            segment_path: Optional[Path] = None
            try:
                # Download only the clip segment + lead-in buffer
                segment_path, segment_start = fetcher.download_clip_segment(
                    video_id=src_id,
                    clip_start=clip_start,
                    clip_end=clip_end,
                    buffer_sec=buffer_sec,
                )

                if segment_path is None:
                    print(f"  ❌ Segment download failed for clip "
                          f"{clip_start}s→{clip_end}s from {src_id}")
                    db.mark_bank_clip_failed(bank_clip["id"])
                    last_source_id = None
                    continue

                clip_spec = {
                    "start_seconds": clip_start,
                    "end_seconds": clip_end,
                    "clip_type": bank_clip["clip_type"],
                    "hook_text": bank_clip["hook_text"],
                    "confidence": bank_clip["confidence"],
                    "reason": bank_clip.get("reason", ""),
                }

                success = self._render_and_upload(
                    bank_clip_id=bank_clip["id"],
                    clip=clip_spec,
                    source_path=segment_path,
                    segment_start=segment_start,
                    transcript_words=bank_clip["transcript_words"],
                    creator_name=bank_clip["creator_name"],
                    source_video_id=src_id,
                    youtube_service=youtube_service,
                    publish_times=publish_times,
                )
                if success:
                    uploads_done += 1
                    self.stats["uploaded"] += 1
                    # Next iteration: avoid another clip from this same source video
                    last_source_id = src_id

            except Exception as e:
                self.stats["errors"] += 1
                db.log_failure("orchestrator.upload_from_bank", str(e),
                               traceback.format_exc()[-500:])
                print(f"❌ Bank upload error for {src_id}: {e}")
            finally:
                fetcher.cleanup_video(segment_path)

    def _render_and_upload(self, bank_clip_id: int, clip: Dict,
                            source_path: Path, segment_start: float,
                            transcript_words: List[Dict],
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
                segment_start=segment_start,   # ← tells renderer where file starts
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

            fake_transcript = {"words": transcript_words,
                                "duration": clip["end_seconds"]}
            seo = seo_generator.generate_seo(
                clip, fake_transcript, creator_name,
                trending_context=self._trending_context,
            )

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
        if TEST_MODE:
            print(f"🧪 [TEST MODE] Pipeline completed — no real YouTube data affected.")