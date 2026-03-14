# pipeline/clip_selector.py
import traceback
from typing import Dict, List, Optional

from engine.config_manager import config_manager
from engine.database import db
from engine.llm_client import llm_client
from pipeline.transcriber import format_transcript_for_ai

VALID_CLIP_TYPES = {"funny", "shocking", "emotional", "challenge", "reaction", "satisfying"}


def select_clips(video: Dict, transcript: Dict) -> List[Dict]:
    """
    Use AI to identify the best clip moments in a video.

    Returns a list of validated clip dicts:
        {start_seconds, end_seconds, clip_type, hook_text, confidence, reason}

    Hallucination defenses:
    - Strict JSON schema
    - Timestamp bounds validation
    - Duration validation
    - Overlap removal
    - Progressive confidence threshold fallback
    """
    cfg = config_manager.pipeline
    prompts_cfg = config_manager.prompts["clip_selector"]

    min_sec = cfg.get("min_clip_seconds", 30)
    max_sec = cfg.get("max_clip_seconds", 60)
    num_clips = cfg.get("clips_per_video", 2)
    confidence_threshold = cfg.get("ai_confidence_threshold", 0.60)
    confidence_floor = cfg.get("ai_confidence_floor", 0.30)
    video_duration = transcript.get("duration", 0)

    transcript_text = format_transcript_for_ai(transcript)

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
        db.log_failure("clip_selector", "AI returned None", video.get("id", ""))
        return []

    raw_clips = result.get("clips", [])
    if not isinstance(raw_clips, list):
        db.log_failure("clip_selector", "AI clips field is not a list", str(result)[:200])
        return []

    # Validate each clip
    validated: List[Dict] = []
    for clip in raw_clips:
        v = _validate_clip(clip, video_duration, min_sec, max_sec)
        if v:
            validated.append(v)

    if not validated:
        db.log_failure("clip_selector", "No clips survived validation",
                       f"Raw clips: {raw_clips}")
        return []

    # Remove overlapping clips (keep highest confidence)
    validated = _remove_overlaps(validated)

    # Sort by confidence descending
    validated.sort(key=lambda c: c["confidence"], reverse=True)

    # Apply confidence threshold with progressive fallback
    threshold = confidence_threshold
    filtered = [c for c in validated if c["confidence"] >= threshold]

    if not filtered and validated:
        # Progressive fallback: lower threshold to floor
        threshold = confidence_floor
        filtered = [c for c in validated if c["confidence"] >= threshold]
        if filtered:
            db.log_failure(
                "clip_selector",
                f"Used fallback confidence threshold {threshold}",
                f"Best available: {filtered[0]['confidence']:.2f}"
            )

    if not filtered and validated:
        # Absolute last resort: take whatever the AI gave us
        filtered = [validated[0]]
        db.log_failure(
            "clip_selector",
            "All clips below confidence floor — using best available",
            f"confidence={validated[0]['confidence']:.2f}"
        )

    result_clips = filtered[:num_clips]
    print(f"✅ Selected {len(result_clips)} clip(s) from {video.get('title', '')[:50]}")
    for c in result_clips:
        print(f"   [{c['start_seconds']:.1f}s → {c['end_seconds']:.1f}s] "
              f"{c['clip_type']} (confidence={c['confidence']:.2f})")

    return result_clips


def _validate_clip(clip: Dict, video_duration: float,
                   min_sec: float, max_sec: float) -> Optional[Dict]:
    """
    Validate a single clip dict from AI output.
    Returns corrected clip or None if unfixable.
    """
    try:
        start = float(clip.get("start_seconds", -1))
        end = float(clip.get("end_seconds", -1))
    except (TypeError, ValueError):
        return None

    # Bounds check
    if start < 0 or end <= 0:
        return None
    if video_duration > 0 and start >= video_duration:
        return None
    if video_duration > 0 and end > video_duration:
        end = video_duration  # Clamp to video end

    if end <= start:
        return None

    # Duration check
    duration = end - start
    if duration < min_sec - 2:  # 2s tolerance
        return None
    if duration > max_sec + 5:  # 5s tolerance, then hard trim
        end = start + max_sec

    # Clip type
    clip_type = clip.get("clip_type", "engaging")
    if clip_type not in VALID_CLIP_TYPES:
        clip_type = "engaging"

    # Confidence
    try:
        confidence = float(clip.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.5

    # Hook text
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
    """Remove clips that overlap with a higher-confidence clip."""
    # Sort by confidence descending — keep the better one when overlap found
    sorted_clips = sorted(clips, key=lambda c: c["confidence"], reverse=True)
    kept: List[Dict] = []
    for clip in sorted_clips:
        overlaps = any(
            _clips_overlap(clip, k) for k in kept
        )
        if not overlaps:
            kept.append(clip)
    return kept


def _clips_overlap(a: Dict, b: Dict) -> bool:
    """Return True if clips share any time range."""
    return a["start_seconds"] < b["end_seconds"] and a["end_seconds"] > b["start_seconds"]
