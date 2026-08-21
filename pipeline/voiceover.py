# pipeline/voiceover.py
import asyncio
import subprocess
import traceback
from pathlib import Path
from typing import Dict, Optional

from engine.config_manager import config_manager
from engine.database import db

ROOT = Path(__file__).parent.parent
TEMP_DIR = ROOT / "temp"


async def _generate_async(text: str, voice: str, output_path: str):
    """edge-tts generation (primary — free, no local model)."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def _generate_piper(text: str, output_path: Path) -> bool:
    """
    Piper TTS fallback (runs locally on CPU — no network, no Azure CDN block).

    Uses the `piper` CLI with a bundled en_US voice model. Voice model path is
    configurable in pipeline.yaml (hook_piper_model). If piper isn't installed
    or the model is missing, fails gracefully (returns False).
    """
    cfg = config_manager.pipeline
    model = cfg.get("hook_piper_model", "en_US-amy-medium")
    piper_bin = cfg.get("piper_bin", "piper")

    try:
        result = subprocess.run(
            [piper_bin, "--model", model, "--output_file", str(output_path)],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
            return True
        # Some piper builds write .wav — if the pipe produced raw PCM we won't
        # get an mp3; piper outputs .wav directly by default here.
        return False
    except Exception as e:
        print(f"⚠️  Piper TTS failed (clip will upload without hook): {e}")
        return False


def generate_hook(clip: Dict, clip_id: str) -> Optional[Path]:
    """
    Generate a short voiceover hook for the start of the clip.
    Uses the AI-suggested hook_text from clip selection.

    Strategy:
      1. edge-tts (primary — free, no local model). Fails on Azure IPs.
      2. Piper TTS (fallback — local CPU, offline).

    Returns path to audio file, or None if disabled or both providers fail.
    """
    cfg = config_manager.pipeline

    if not cfg.get("add_voiceover_hook", True):
        return None

    hook_text = clip.get("hook_text", "").strip()
    if not hook_text:
        return None

    # Enforce word limit
    max_words = cfg.get("hook_max_words", 10)
    words = hook_text.split()
    if len(words) > max_words:
        hook_text = " ".join(words[:max_words])

    voice = cfg.get("hook_voice", "en-US-GuyNeural")
    tts_provider = cfg.get("hook_tts_provider", "auto")  # auto | edge | piper

    TEMP_DIR.mkdir(exist_ok=True)
    out_path = TEMP_DIR / f"{clip_id}_hook.mp3"

    used_provider = "none"

    # ── Primary: edge-tts ─────────────────────────────────────────
    if tts_provider in ("auto", "edge"):
        try:
            asyncio.run(_generate_async(hook_text, voice, str(out_path)))
            if out_path.exists() and out_path.stat().st_size > 1000:
                print(f"🎤 Hook generated (edge-tts): \"{hook_text}\"")
                return out_path
            print("⚠️  edge-tts produced empty/missing file — trying Piper")
            if out_path.exists():
                out_path.unlink()
        except Exception as e:
            print(f"⚠️  edge-tts voiceover failed ({e}) — trying Piper")
            if out_path.exists():
                out_path.unlink()
        used_provider = "edge-failed"

    # ── Fallback: Piper TTS ───────────────────────────────────────
    if tts_provider in ("auto", "piper"):
        wav_path = TEMP_DIR / f"{clip_id}_hook.wav"
        if _generate_piper(hook_text, wav_path):
            # Convert wav → mp3 with ffmpeg (keeps renderer audio handling consistent)
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", "192k",
                     str(out_path)],
                    capture_output=True, timeout=60,
                )
                wav_path.unlink(missing_ok=True)
                if out_path.exists() and out_path.stat().st_size > 1000:
                    print(f"🎤 Hook generated (Piper): \"{hook_text}\"")
                    return out_path
            except Exception as e:
                print(f"⚠️  Piper wav→mp3 conversion failed: {e}")
            finally:
                wav_path.unlink(missing_ok=True)
        used_provider = "piper-failed"

    # ── All providers failed ──────────────────────────────────────
    if used_provider != "none":
        db.log_failure("voiceover", "All TTS providers failed", clip_id)
    return None


def cleanup_hook(path: Optional[Path]):
    if path and path.exists():
        try:
            path.unlink()
        except Exception:
            pass
