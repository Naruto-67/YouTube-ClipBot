# pipeline/clip_selector.py
import traceback
from typing import Dict, List, Optional

from engine.config_manager import config_manager
from engine.database import db
from engine.llm_client import llm_client
from pipeline.transcriber import format_transcript_for_ai

VALID_CLIP_TYPES = {
    "funny", "shocking", "emotional", "challenge", "reaction", "satisfying"
}

# Punctuation that marks a sentence boundary
_SENTENCE_ENDERS = {".", "!", "?", "…", "..."}


def get_dynamic_clip_count(duration_seconds: float) -> int:
    """
    Returns how many clips to extract based on video duration.
    Tiers defined in pipeline.yaml → clips_per_video_tiers.
    """
    cfg = config_manager.pipeline
    duration_minutes = duration_seconds / 60
    tiers = cfg.get("clips_per_video_tiers", [
        {"max_minutes": 10,  "clips": 2},
        {"max_minutes": 20,  "clips": 4},
        {"max_minutes": 35,  "clips": 6},
        {"max_minutes": 999, "clips": 10},
    ])
    for tier in tiers:
        if duration_minutes <= tier["max_minutes"]:
            return tier["clips"]
    return tiers[-1]["clips"]


def select_clips(video: Dict, transcript: Dict,
                 override_count: int = 0,
                 early_stop_at: int = 0) -> List[Dict]:
    """
    Use AI to find the best clips in a video.
    For long videos, splits transcript into overlapping chunks and
    runs selection on each chunk, then merges and deduplicates results.

    override_count: if > 0, use this instead of dynamic count (for manual queue)

    NEW: Excludes time ranges already banked for this video, so the same
    moments are never re-selected. Also snaps clip boundaries to sentence
    boundaries for narrative coherence.
    """
    cfg = config_manager.pipeline
    video_duration = transcript.get("duration", 0)
    video_id = video.get("id", "")

    num_clips = override_count if override_count > 0 else get_dynamic_clip_count(video_duration)
    chunk_mins = cfg.get("chunk_duration_minutes", 15)
    chunk_sec = chunk_mins * 60

    # ── NEW: Get already-banked time ranges for this video ────────────────
    # This prevents the same moments from being re-selected on re-runs.
    banked_ranges = db.get_banked_time_ranges(video_id) if video_id else []
    if banked_ranges:
        print(f"🔒 Excluding {len(banked_ranges)} already-banked time range(s) "
              f"for {video_id}")

    print(f"🎯 Targeting {num_clips} clips from "
          f"{video_duration/60:.1f}m video")

    # Decide: single pass or chunked AI analysis
    if video_duration <= chunk_sec:
        raw_clips = _select_from_chunk(video, transcript, num_clips,
                                       banked_ranges=banked_ranges)
    else:
        raw_clips = _select_chunked(video, transcript, num_clips, chunk_sec,
                                    early_stop_at=early_stop_at,
                                    banked_ranges=banked_ranges)

    if not raw_clips:
        db.log_failure("clip_selector", "No clips from AI", video_id)
        return []

    # ── NEW: Snap to sentence boundaries for narrative coherence ──────────
    # This ensures clips start at the beginning of a new thought and end at
    # a natural pause/punchline — not mid-sentence.
    words = transcript.get("words", [])
    snapped = []
    for clip in raw_clips:
        snapped_clip = _snap_to_sentence_boundaries(clip, words)
        if snapped_clip:
            snapped.append(snapped_clip)

    # Final dedup + sort
    all_clips = _remove_overlaps(snapped)
    all_clips.sort(key=lambda c: c["confidence"], reverse=True)
    result = all_clips[:num_clips]

    print(f"✅ Selected {len(result)} clip(s)")
    for c in result:
        print(f"   [{c['start_seconds']:.1f}s→{c['end_seconds']:.1f}s] "
              f"{c['clip_type']} conf={c['confidence']:.2f}")
    return result


def _snap_to_sentence_boundaries(clip: Dict, words: List[Dict]) -> Optional[Dict]:
    """
    Snap clip start/end to the nearest sentence boundary.

    - Start: move forward to the first word that begins a new sentence
      (i.e. the word after a sentence-ending punctuation, or the first word).
    - End: move backward to the last word that ends a sentence
      (i.e. a word ending with . ! ? …).

    If snapping would make the clip too short (< min_sec - 2), the clip is
    rejected. If it makes it too long, it's trimmed to max_sec.
    """
    cfg = config_manager.pipeline
    min_sec = cfg.get("min_clip_seconds", 30)
    max_sec = cfg.get("max_clip_seconds", 60)

    if not words:
        return clip

    start = clip["start_seconds"]
    end = clip["end_seconds"]

    # ── Snap start forward to a sentence boundary ─────────────────────────
    # Find the first word at/after start that begins a new sentence.
    # A word begins a new sentence if:
    #   - it's the first word in the transcript, OR
    #   - the previous word ends with sentence-ending punctuation
    snapped_start = None
    for i, w in enumerate(words):
        if w["start"] < start:
            continue
        if w["start"] > end:
            break
        prev = words[i - 1] if i > 0 else None
        is_sentence_start = (
            prev is None
            or (prev["word"].rstrip()[-1:] in _SENTENCE_ENDERS)
        )
        if is_sentence_start:
            snapped_start = w["start"]
            break

    if snapped_start is not None:
        start = snapped_start

    # ── Snap end backward to a sentence boundary ──────────────────────────
    # Find the last word at/before end that ends a sentence.
    snapped_end = None
    for w in reversed(words):
        if w["end"] > end:
            continue
        if w["end"] < start:
            break
        if w["word"].rstrip()[-1:] in _SENTENCE_ENDERS:
            snapped_end = w["end"]
            break

    if snapped_end is not None:
        end = snapped_end

    # ── Validate snapped clip ─────────────────────────────────────────────
    duration = end - start
    if duration < min_sec - 2:
        return None  # Too short after snapping — reject
    if duration > max_sec:
        end = start + max_sec

    return {
        **clip,
        "start_seconds": round(start, 2),
        "end_seconds": round(end, 2),
        "duration": round(end - start, 2),
    }


def _select_chunked(video: Dict, transcript: Dict,
                    total_clips: int, chunk_sec: float,
                    early_stop_at: int = 0,
                    banked_ranges: Optional[List[Dict]] = None) -> List[Dict]:
    """Run clip selection on each transcript chunk, merge results.

    early_stop_at: if > 0, stop scheduling chunks once we already collected
                   this many clips (saves LLM calls when bank is nearly full).
    banked_ranges: time ranges already banked — excluded from selection.

    Chunks are analysed CONCURRENTLY with a small thread pool (bounded by the
    provider RPM throttle inside llm_client.wait_for_rpm_if_needed), which
    cuts multi-chunk wall-clock time dramatically for long videos.
    """
    import concurrent.futures

    cfg = config_manager.pipeline
    overlap_sec = cfg.get("chunk_overlap_minutes", 2) * 60
    step_sec = chunk_sec - overlap_sec
    video_duration = transcript.get("duration", 0)
    words = transcript.get("words", [])

    chunks = []
    start = 0.0
    while start < video_duration:
        end = min(start + chunk_sec, video_duration)
        chunks.append((start, end))
        if end >= video_duration:
            break
        start += step_sec

    # Ask for ~2 clips per chunk so we have enough to pick from
    clips_per_chunk = max(2, total_clips // len(chunks) + 1)
    all_clips: List[Dict] = []

    # Build chunk transcripts up-front (cheap) so we can run LLM calls in parallel
    prepared = []
    for i, (chunk_start, chunk_end) in enumerate(chunks):
        chunk_words = [w for w in words
                       if w["start"] >= chunk_start and w["end"] <= chunk_end + 1]
        if not chunk_words:
            continue
        prepared.append({
            "idx": i,
            "chunk_start": chunk_start,
            "chunk_end": chunk_end,
            "transcript": {
                "words": chunk_words,
                "text": " ".join(w["word"] for w in chunk_words),
                "duration": chunk_end,  # duration is absolute video time
            },
        })

    def _run_one(item: Dict) -> List[Dict]:
        print(f"   AI chunk {item['idx'] + 1}/{len(chunks)}: "
              f"{item['chunk_start']/60:.1f}m → {item['chunk_end']/60:.1f}m")
        return _select_from_chunk(
            video, item["transcript"], clips_per_chunk,
            banked_ranges=banked_ranges,
        )

    # Concurrency bounded by RPM — run at most 3 concurrent LLM calls.
    # rpm throttling inside llm_client keeps us under per-minute limits.
    max_workers = min(len(prepared), 3)
    if max_workers <= 0:
        return []

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_run_one, item): item for item in prepared}
            for fut in concurrent.futures.as_completed(futures):
                try:
                    chunk_clips = fut.result()
                except Exception as e:
                    db.log_failure("clip_selector.chunk", str(e), video.get("id", ""))
                    chunk_clips = []
                all_clips.extend(chunk_clips)
                # Early stop: cancel remaining pending submits if we have enough
                if early_stop_at > 0 and len(all_clips) >= early_stop_at:
                    for f in futures:
                        f.cancel()
                    break
    except Exception as e:
        db.log_failure("clip_selector.parallel", str(e), video.get("id", ""))

    return all_clips


def _select_from_chunk(video: Dict, transcript: Dict,
                        num_clips: int,
                        banked_ranges: Optional[List[Dict]] = None) -> List[Dict]:
    """Run AI clip selection on a single transcript (chunk or full)."""
    cfg = config_manager.pipeline
    prompts_cfg = config_manager.prompts["clip_selector"]
    min_sec = cfg.get("min_clip_seconds", 30)
    max_sec = cfg.get("max_clip_seconds", 60)
    video_duration = transcript.get("duration", 0)

    transcript_text = format_transcript_for_ai(transcript)
    if not transcript_text.strip():
        return []

    prompt = prompts_cfg["user"].format(
        title=video.get("title", "Unknown"),
        creator=video.get("creator_name", "Unknown"),
        duration_seconds=int(video_duration),
        transcript=transcript_text,
        num_clips=num_clips,
        min_seconds=min_sec,
        max_seconds=max_sec,
    )

    result = llm_client.generate(
        prompt=prompt,
        system_prompt=prompts_cfg["system"],
        call_type="clip_selection",
    )
    if result is None:
        return []

    raw_clips = result.get("clips", [])
    if not isinstance(raw_clips, list):
        return []

    validated = []
    for clip in raw_clips:
        v = _validate_clip(clip, video_duration, min_sec, max_sec)
        if v:
            # ── NEW: Skip clips that overlap already-banked ranges ────────
            if banked_ranges and _overlaps_any_banked(v, banked_ranges):
                print(f"   ⏭️  Skipping clip [{v['start_seconds']:.1f}s→"
                      f"{v['end_seconds']:.1f}s] — overlaps already-banked range")
                continue
            validated.append(v)

    return validated


def _overlaps_any_banked(clip: Dict, banked_ranges: List[Dict]) -> bool:
    """Check if a clip overlaps any already-banked time range."""
    for r in banked_ranges:
        if (clip["start_seconds"] < r["end"] and
                clip["end_seconds"] > r["start"]):
            return True
    return False


def _validate_clip(clip: Dict, video_duration: float,
                   min_sec: float, max_sec: float) -> Optional[Dict]:
    cfg = config_manager.pipeline
    confidence_floor = cfg.get("ai_confidence_floor", 0.30)
    try:
        start = float(clip.get("start_seconds", -1))
        end = float(clip.get("end_seconds", -1))
    except (TypeError, ValueError):
        return None

    if start < 0 or end <= 0:
        return None
    if video_duration > 0 and start >= video_duration:
        return None
    if video_duration > 0 and end > video_duration:
        end = video_duration
    if end <= start:
        return None

    duration = end - start
    if duration < min_sec - 2:
        return None
    if duration > max_sec:
        end = start + max_sec

    clip_type = clip.get("clip_type", "engaging")
    if clip_type not in VALID_CLIP_TYPES:
        clip_type = "engaging"

    try:
        confidence = max(0.0, min(1.0, float(clip.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5

    if confidence < confidence_floor:
        return None

    hook_text = str(clip.get("hook_text", "")).strip()
    hook_words = hook_text.split()
    if len(hook_words) > 10:
        hook_text = " ".join(hook_words[:10])

    return {
        "start_seconds": round(start, 2),
        "end_seconds": round(end, 2),
        "duration": round(end - start, 2),
        "clip_type": clip_type,
        "hook_text": hook_text,
        "confidence": round(confidence, 3),
        "reason": str(clip.get("reason", ""))[:200],
    }


def _remove_overlaps(clips: List[Dict]) -> List[Dict]:
    sorted_clips = sorted(clips, key=lambda c: c["confidence"], reverse=True)
    kept: List[Dict] = []
    for clip in sorted_clips:
        if not any(_clips_overlap(clip, k) for k in kept):
            kept.append(clip)
    return kept


def _clips_overlap(a: Dict, b: Dict) -> bool:
    return (a["start_seconds"] < b["end_seconds"] and
            a["end_seconds"] > b["start_seconds"])
