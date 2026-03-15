# pipeline/renderer.py
import subprocess
import traceback
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from engine.config_manager import config_manager
from engine.database import db
from engine.discord_notifier import notifier

ROOT = Path(__file__).parent.parent
TEMP_DIR = ROOT / "temp"
FONT_PATH = ROOT / "assets" / "fonts" / "Anton-Regular.ttf"
SYSTEM_FONT_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# ── Font resolution ───────────────────────────────────────────────────────

def _get_font_path() -> Optional[str]:
    if FONT_PATH.exists():
        return str(FONT_PATH)
    if Path(SYSTEM_FONT_FALLBACK).exists():
        return SYSTEM_FONT_FALLBACK
    return None


# ── Smart crop (face detection) ───────────────────────────────────────────

def _detect_crop_x(video_path: Path, start_sec: float, end_sec: float,
                    frame_w: int, frame_h: int, crop_w: int) -> int:
    """
    Sample frames every 3 seconds, detect faces, return best crop x-offset.
    Falls back to center crop if no faces found.

    start_sec / end_sec are relative to the video file (not absolute video time).
    """
    try:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        face_centers_x: List[int] = []
        t = start_sec
        while t < end_sec:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if not ret:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4)

            if len(faces) > 0:
                largest = max(faces, key=lambda f: f[2] * f[3])
                x, _, w, _ = largest
                face_centers_x.append(x + w // 2)

            t += 3

        cap.release()

        if face_centers_x:
            center_x = int(np.median(face_centers_x))
        else:
            center_x = frame_w // 2

        half = crop_w // 2
        center_x = max(half, min(frame_w - half, center_x))
        return center_x - half

    except Exception:
        return (frame_w - crop_w) // 2


# ── ASS caption generation ────────────────────────────────────────────────

def _sec_to_ass(sec: float) -> str:
    """Convert float seconds to ASS time format H:MM:SS.cc"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _generate_ass(words: List[Dict], clip_start: float,
                  clip_duration: float, out_path: Path) -> bool:
    """
    Generate ASS subtitle file with word-by-word highlighting.
    Active word = yellow with glow. Spoken words = dim white. Upcoming = white.

    words: transcript words with ABSOLUTE timestamps (from original video).
    clip_start: absolute start of clip in original video.
    clip_duration: length of the rendered clip.
    """
    cfg = config_manager.pipeline

    # Shift words to clip-relative timestamps, filter to clip window
    clip_words = []
    for w in words:
        if w["start"] >= clip_start and w["start"] < clip_start + clip_duration:
            clip_words.append({
                "word": w["word"],
                "start": round(w["start"] - clip_start, 3),
                "end": round(w["end"] - clip_start, 3),
            })

    if not clip_words:
        return False

    words_per_line = cfg.get("caption_words_per_line", 4)
    font_name = cfg.get("caption_font", "Anton-Regular")
    font_size = cfg.get("caption_font_size", 85)
    text_color = cfg.get("caption_text_color", "&H00FFFFFF")
    highlight_color = cfg.get("caption_highlight_color", "&H0000FFFF")
    outline_color = cfg.get("caption_outline_color", "&H00000000")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{text_color},{text_color},{outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [
        clip_words[i: i + words_per_line]
        for i in range(0, len(clip_words), words_per_line)
    ]

    events: List[str] = []

    for line in lines:
        for i, active_word in enumerate(line):
            event_start = active_word["start"]
            event_end = (
                line[i + 1]["start"] if i + 1 < len(line)
                else line[-1]["end"]
            )
            if event_end <= event_start:
                event_end = event_start + 0.1

            parts = []
            for j, w in enumerate(line):
                word_text = w["word"]
                if j == i:
                    parts.append(
                        f"{{\\c{highlight_color}&\\3c&H00333333&\\blur4}}"
                        f"{word_text}"
                        f"{{\\c{text_color}&\\3c{outline_color}&\\blur0}}"
                    )
                elif j < i:
                    parts.append(
                        f"{{\\c&H00BBBBBB&}}{word_text}{{\\c{text_color}&}}"
                    )
                else:
                    parts.append(word_text)

            text = " ".join(parts)
            start_ass = _sec_to_ass(event_start)
            end_ass = _sec_to_ass(event_end)
            events.append(
                f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{text}"
            )

    ass_content = header + "\n".join(events) + "\n"
    out_path.write_text(ass_content, encoding="utf-8")
    return True


# ── FFmpeg validation ─────────────────────────────────────────────────────

def _validate_output(path: Path) -> bool:
    """Use ffprobe to verify the rendered file is valid."""
    if not path.exists() or path.stat().st_size < 50_000:
        return False
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,codec_name",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0 and '"codec_name"' in result.stdout
    except Exception:
        return False


# ── Main render function ──────────────────────────────────────────────────

def render_short(
    source_path: Path,
    clip: Dict,
    transcript_words: List[Dict],
    hook_audio_path: Optional[Path] = None,
    segment_start: float = 0.0,
) -> Optional[Path]:
    """
    Render a YouTube Short from a clip spec.

    Args:
        source_path:      Path to video file (full video OR downloaded segment)
        clip:             Clip spec with start_seconds/end_seconds (ABSOLUTE
                          timestamps in the original video — not relative to file)
        transcript_words: Word timestamps (ABSOLUTE — not relative to file)
        hook_audio_path:  Optional voiceover hook audio
        segment_start:    Where the source_path file starts in absolute video
                          time. Default 0.0 = full video (backwards compatible).
                          Set to seg_start from download_clip_segment() when
                          using a downloaded segment.

    The segment_start offset converts absolute clip timestamps to file-relative
    timestamps for FFmpeg and face detection, while caption generation continues
    to use absolute timestamps (it subtracts clip_start itself).

    Pipeline:
    1. Extract clip segment + force CFR 30fps
    2. Detect face for smart 9:16 crop
    3. Scale to 1080×1920
    4. Burn word-by-word captions
    5. Apply vignette
    6. Reduce original audio, mix in hook voiceover if present
    7. Validate output with ffprobe
    """
    TEMP_DIR.mkdir(exist_ok=True)
    cfg = config_manager.pipeline

    start = clip["start_seconds"]   # absolute
    end = clip["end_seconds"]       # absolute
    clip_id = f"{source_path.stem}_{int(start)}_{int(end)}"

    # Convert absolute timestamps → file-relative timestamps
    # When segment_start=0 (full video), these equal start/end unchanged.
    file_ss = start - segment_start
    file_to = end - segment_start

    ass_path = TEMP_DIR / f"{clip_id}.ass"
    out_path = TEMP_DIR / f"{clip_id}_short.mp4"

    max_retries = cfg.get("max_render_retries", 3)

    for attempt in range(max_retries):
        try:
            # ── 1. Get source dimensions ──────────────────────────────
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height",
                 "-of", "json", str(source_path)],
                capture_output=True, text=True, timeout=30,
            )
            import json as _json
            dims = _json.loads(probe.stdout)["streams"][0]
            frame_w = dims["width"]
            frame_h = dims["height"]

            # ── 2. Calculate smart crop ───────────────────────────────
            crop_w = int(frame_h * 9 / 16)
            # Use file-relative timestamps for frame sampling
            crop_x = _detect_crop_x(source_path, file_ss, file_to,
                                     frame_w, frame_h, crop_w)
            crop_x = max(0, min(frame_w - crop_w, crop_x))

            # ── 3. Generate captions ──────────────────────────────────
            # Uses absolute timestamps — _generate_ass subtracts clip_start
            has_captions = _generate_ass(
                transcript_words, start, end - start, ass_path
            )

            # ── 4. Build video filter chain ───────────────────────────
            font_path = _get_font_path()
            out_w = cfg.get("output_width", 1080)
            out_h = cfg.get("output_height", 1920)
            fps = cfg.get("output_fps", 30)
            crf = cfg.get("output_crf", 23)
            audio_db = cfg.get("original_audio_db", -20)
            apply_vignette = cfg.get("apply_vignette", True)
            vignette_angle = cfg.get("vignette_angle", 0.785)

            vf_parts = [
                f"fps={fps}",
                f"crop={crop_w}:{frame_h}:{crop_x}:0",
                f"scale={out_w}:{out_h}:flags=lanczos",
            ]

            if has_captions and ass_path.exists():
                ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")
                if font_path:
                    vf_parts.append(
                        f"subtitles='{ass_escaped}':fontsdir='{Path(font_path).parent}'"
                    )
                else:
                    vf_parts.append(f"subtitles='{ass_escaped}'")

            if apply_vignette:
                vf_parts.append(f"vignette=angle={vignette_angle}")

            vf = ",".join(vf_parts)

            # ── 5. Build FFmpeg command ───────────────────────────────
            # Use file-relative -ss / -to so FFmpeg seeks correctly
            # regardless of whether source_path is a full video or a segment.
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(file_ss),
                "-to", str(file_to),
                "-i", str(source_path),
            ]

            if hook_audio_path and hook_audio_path.exists():
                cmd += ["-i", str(hook_audio_path)]
                af = (
                    f"[0:a]volume={audio_db}dB[orig];"
                    "[1:a]adelay=0|0[hook];"
                    "[orig][hook]amix=inputs=2:duration=first:normalize=0[out]"
                )
                cmd += [
                    "-vf", vf,
                    "-filter_complex", af,
                    "-map", "0:v",
                    "-map", "[out]",
                ]
            else:
                cmd += [
                    "-vf", vf,
                    "-af", f"volume={audio_db}dB",
                ]

            cmd += [
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", str(crf),
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(out_path),
            ]

            subprocess.run(cmd, check=True, capture_output=True, timeout=300)

            # ── 6. Validate output ────────────────────────────────────
            if _validate_output(out_path):
                print(f"✅ Rendered: {out_path.name}")
                return out_path
            else:
                print(f"⚠️  Render attempt {attempt + 1} produced invalid file. Retrying...")
                if out_path.exists():
                    out_path.unlink()

        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace")[-300:] if e.stderr else ""
            print(f"⚠️  FFmpeg error (attempt {attempt + 1}): {stderr}")
            db.log_failure("renderer", stderr, clip_id)
        except Exception as e:
            print(f"⚠️  Renderer exception (attempt {attempt + 1}): {e}")
            db.log_failure("renderer", str(e), traceback.format_exc()[-500:])
        finally:
            if ass_path.exists():
                ass_path.unlink(missing_ok=True)

    notifier.send_warning("Render Failed",
                          f"Clip {clip_id} failed after {max_retries} attempts")
    return None


def cleanup_short(path: Optional[Path]):
    """Delete rendered short after successful upload."""
    if path and path.exists():
        try:
            path.unlink()
        except Exception:
            pass
