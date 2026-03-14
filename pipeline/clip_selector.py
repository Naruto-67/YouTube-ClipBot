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
                 override_count: int = 0) -> List[Dict]:
    """
    Use AI to find the best clips in a video.
    For long videos, splits transcript into overlapping chunks and
    runs selection on each chunk, then merges and deduplicates results.

    override_count: if > 0, use this instead of dynamic count (for manual queue)
    """
    cfg = config_manager.pipeline
    video_duration = transcript.get("duration", 0)

    num_clips = override_count if override_count > 0 else get_dynamic_clip_count(video_duration)
    chunk_mins = cfg.get("chunk_duration_minutes", 15)
    chunk_sec = chunk_mins * 60

    print(f"🎯 Targeting {num_clips} clips from "
          f"{video_duration/60:.1f}m video")

    # Decide: single pass or chunked AI analysis
    if video_duration <= chunk_sec:
        raw_clips = _select_from_chunk(video, transcript, num_clips)
    else:
        raw_clips = _select_chunked(video, transcript, num_clips, chunk_sec)

    if not raw_clips:
        db.log_failure("clip_selector", "No clips from AI", video.get("id", ""))
        return []

    # Final dedup + sort
    all_clips = _remove_overlaps(raw_clips)
    all_clips.sort(key=lambda c: c["confidence"], reverse=True)
    result = all_clips[:num_clips]

    print(f"✅ Selected {len(result)} clip(s)")
    for c in result:
        print(f"   [{c['start_seconds']:.1f}s→{c['end_seconds']:.1f}s] "
              f"{c['clip_type']} conf={c['confidence']:.2f}")
    return result


def _select_chunked(video: Dict, transcript: Dict,
                    total_clips: int, chunk_sec: float) -> List[Dict]:
    """Run clip selection on each transcript chunk, merge results."""
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

    for i, (chunk_start, chunk_end) in enumerate(chunks):
        print(f"   AI chunk {i+1}/{len(chunks)}: "
              f"{chunk_start/60:.1f}m → {chunk_end/60:.1f}m")

        # Build chunk transcript
        chunk_words = [w for w in words
                       if w["start"] >= chunk_start and w["end"] <= chunk_end + 1]
        if not chunk_words:
            continue

        chunk_transcript = {
            "words": chunk_words,
            "text": " ".join(w["word"] for w in chunk_words),
            "duration": chunk_end,  # duration is absolute video time
        }

        chunk_clips = _select_from_chunk(video, chunk_transcript, clips_per_chunk)
        all_clips.extend(chunk_clips)

    return all_clips


def _select_from_chunk(video: Dict, transcript: Dict,
                        num_clips: int) -> List[Dict]:
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
            validated.append(v)

    return validated


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
    if duration > max_sec + 5:
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
