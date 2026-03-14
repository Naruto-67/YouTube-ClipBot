# pipeline/transcriber.py
import traceback
from pathlib import Path
from typing import Dict, List, Optional

from engine.database import db
from engine.discord_notifier import notifier

_model = None  # Lazy-loaded once, reused for all clips


def _get_model():
    """Load Whisper model once and cache it for the run."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        print("⏳ Loading Whisper medium.en model (first run may be slow)...")
        _model = WhisperModel(
            "medium.en",
            device="cpu",
            compute_type="int8",    # Halves RAM, 4x faster on CPU
            cpu_threads=4,
        )
        print("✅ Whisper model loaded")
    return _model


def transcribe(video_path: Path) -> Optional[Dict]:
    """
    Transcribe a video file and return word-level timestamps.

    Returns:
        {
          "words": [{"word": str, "start": float, "end": float, "confidence": float}],
          "text": str,          full transcript
          "language": str,
          "duration": float,
        }
    Or None on failure.
    """
    try:
        model = _get_model()

        print(f"🎙️  Transcribing {video_path.name}...")
        segments, info = model.transcribe(
            str(video_path),
            language="en",              # Force English — skip language detection
            word_timestamps=True,
            beam_size=5,
            vad_filter=True,            # Filter silence — cleaner timestamps
            vad_parameters={"min_silence_duration_ms": 500},
        )

        words: List[Dict] = []
        full_text_parts: List[str] = []

        for segment in segments:
            for w in (segment.words or []):
                words.append({
                    "word": w.word.strip(),
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "confidence": round(w.probability, 3),
                })
            full_text_parts.append(segment.text.strip())

        if not words:
            print("⚠️  Transcription returned no words.")
            return None

        transcript = {
            "words": words,
            "text": " ".join(full_text_parts),
            "language": info.language,
            "duration": info.duration,
        }

        print(f"✅ Transcribed {len(words)} words, "
              f"{info.duration:.0f}s, language={info.language}")
        return transcript

    except Exception as e:
        db.log_failure("transcriber", str(e), traceback.format_exc())
        notifier.send_warning("Transcription Failed", str(e)[:200])
        return None


def format_transcript_for_ai(transcript: Dict, max_chars: int = 12000) -> str:
    """
    Format word timestamps into a compact string for the AI prompt.
    Format: [seconds] word word word...
    Groups words into ~10-second lines to stay readable.
    Truncates if transcript exceeds max_chars (30-min video safety).
    """
    words = transcript.get("words", [])
    if not words:
        return ""

    lines: List[str] = []
    current_line_words: List[str] = []
    line_start_sec: float = words[0]["start"]

    for i, w in enumerate(words):
        current_line_words.append(w["word"])
        # Break line every ~10 seconds or every 20 words
        is_last = i == len(words) - 1
        next_start = words[i + 1]["start"] if not is_last else w["end"]
        if next_start - line_start_sec >= 10 or len(current_line_words) >= 20 or is_last:
            ts = f"[{line_start_sec:.1f}]"
            lines.append(f"{ts} {' '.join(current_line_words)}")
            current_line_words = []
            if not is_last:
                line_start_sec = words[i + 1]["start"]

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n... [transcript truncated]"

    return result


def get_words_in_range(transcript: Dict, start: float, end: float,
                       min_confidence: float = 0.0) -> List[Dict]:
    """Return words that fall within [start, end] with confidence >= min_confidence."""
    return [
        w for w in transcript.get("words", [])
        if w["start"] >= start and w["end"] <= end + 0.5
        and w["confidence"] >= min_confidence
    ]
