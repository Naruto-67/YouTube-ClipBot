# pipeline/transcriber.py
import traceback
from pathlib import Path
from typing import Dict, List, Optional

from engine.database import db
from engine.discord_notifier import notifier

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        print("⏳ Loading Whisper medium.en model...")
        _model = WhisperModel("medium.en", device="cpu", compute_type="int8",
                              cpu_threads=4)
        print("✅ Whisper model loaded")
    return _model


def transcribe(video_path: Path) -> Optional[Dict]:
    """
    Transcribe video — auto-selects chunked or single-pass based on duration.
    Returns unified transcript dict regardless of method used.
    """
    from engine.config_manager import config_manager
    cfg = config_manager.pipeline
    chunk_mins = cfg.get("chunk_duration_minutes", 15)
    overlap_mins = cfg.get("chunk_overlap_minutes", 2)

    # Quick duration probe
    duration = _probe_duration(video_path)
    if duration is None:
        duration = 0

    if duration > chunk_mins * 60:
        print(f"📼 Video is {duration/60:.1f}m — using chunked transcription")
        return _transcribe_chunked(video_path, duration, chunk_mins, overlap_mins)
    else:
        return _transcribe_single(video_path)


def _probe_duration(video_path: Path) -> Optional[float]:
    """Use ffprobe to get video duration in seconds."""
    import subprocess, json
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return None


def _transcribe_single(video_path: Path) -> Optional[Dict]:
    """Standard single-pass transcription."""
    try:
        model = _get_model()
        print(f"🎙️  Transcribing {video_path.name}...")
        segments, info = model.transcribe(
            str(video_path), language="en", word_timestamps=True,
            beam_size=5, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        words, text_parts = [], []
        for seg in segments:
            for w in (seg.words or []):
                words.append({"word": w.word.strip(), "start": round(w.start, 3),
                               "end": round(w.end, 3), "confidence": round(w.probability, 3)})
            text_parts.append(seg.text.strip())

        if not words:
            return None
        print(f"✅ Transcribed {len(words)} words, {info.duration:.0f}s")
        return {"words": words, "text": " ".join(text_parts),
                "language": info.language, "duration": info.duration}
    except Exception as e:
        db.log_failure("transcriber", str(e), traceback.format_exc())
        notifier.send_warning("Transcription Failed", str(e)[:200])
        return None


def _transcribe_chunked(video_path: Path, total_duration: float,
                         chunk_mins: int, overlap_mins: int) -> Optional[Dict]:
    """
    Chunk a long video into overlapping segments, transcribe each,
    then merge — deduplicating words at chunk boundaries.
    """
    import subprocess, tempfile

    chunk_sec = chunk_mins * 60
    overlap_sec = overlap_mins * 60
    step_sec = chunk_sec - overlap_sec

    # Build chunk time ranges
    chunks = []
    start = 0.0
    while start < total_duration:
        end = min(start + chunk_sec, total_duration)
        chunks.append((start, end))
        if end >= total_duration:
            break
        start += step_sec

    print(f"📦 {len(chunks)} chunks × {chunk_mins}m "
          f"(overlap={overlap_mins}m) for {total_duration/60:.1f}m video")

    all_words: List[Dict] = []
    last_end_time = 0.0

    for i, (chunk_start, chunk_end) in enumerate(chunks):
        print(f"   Chunk {i+1}/{len(chunks)}: {chunk_start/60:.1f}m → {chunk_end/60:.1f}m")
        try:
            # Extract chunk to temp file
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name

            subprocess.run([
                "ffmpeg", "-y", "-ss", str(chunk_start),
                "-to", str(chunk_end), "-i", str(video_path),
                "-q:a", "0", "-map", "a", tmp_path,
            ], check=True, capture_output=True, timeout=120)

            model = _get_model()
            segments, _ = model.transcribe(
                tmp_path, language="en", word_timestamps=True, beam_size=5,
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
            )

            chunk_words = []
            for seg in segments:
                for w in (seg.words or []):
                    # Convert chunk-relative timestamps to absolute
                    abs_start = round(chunk_start + w.start, 3)
                    abs_end = round(chunk_start + w.end, 3)
                    chunk_words.append({
                        "word": w.word.strip(),
                        "start": abs_start,
                        "end": abs_end,
                        "confidence": round(w.probability, 3),
                    })

            # Deduplicate: only keep words that start after last_end_time
            # (prevents overlap region words from appearing twice)
            new_words = [w for w in chunk_words if w["start"] >= last_end_time - 0.5]
            all_words.extend(new_words)
            if new_words:
                last_end_time = new_words[-1]["end"]

        except Exception as e:
            print(f"⚠️  Chunk {i+1} failed: {e} — continuing with other chunks")
            db.log_failure("transcriber.chunk", str(e), f"chunk {i+1}")
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    if not all_words:
        db.log_failure("transcriber", "All chunks returned no words", str(video_path))
        return None

    # Sort by timestamp (should already be sorted, but defensive)
    all_words.sort(key=lambda w: w["start"])
    full_text = " ".join(w["word"] for w in all_words)

    print(f"✅ Chunked transcription: {len(all_words)} words total")
    return {"words": all_words, "text": full_text,
            "language": "en", "duration": total_duration}


def format_transcript_for_ai(transcript: Dict, max_chars: int = 12000) -> str:
    """Format word timestamps into compact lines for the AI prompt."""
    words = transcript.get("words", [])
    if not words:
        return ""
    lines, current_words, line_start = [], [], words[0]["start"]
    for i, w in enumerate(words):
        current_words.append(w["word"])
        is_last = i == len(words) - 1
        next_start = words[i + 1]["start"] if not is_last else w["end"]
        if next_start - line_start >= 10 or len(current_words) >= 20 or is_last:
            lines.append(f"[{line_start:.1f}] {' '.join(current_words)}")
            current_words = []
            if not is_last:
                line_start = words[i + 1]["start"]
    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n... [transcript truncated]"
    return result


def get_words_in_range(transcript: Dict, start: float, end: float,
                        min_confidence: float = 0.0) -> List[Dict]:
    return [
        w for w in transcript.get("words", [])
        if w["start"] >= start and w["end"] <= end + 0.5
        and w["confidence"] >= min_confidence
    ]
