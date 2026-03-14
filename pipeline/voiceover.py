# pipeline/voiceover.py
import asyncio
import traceback
from pathlib import Path
from typing import Dict, Optional

from engine.config_manager import config_manager
from engine.database import db

ROOT = Path(__file__).parent.parent
TEMP_DIR = ROOT / "temp"


async def _generate_async(text: str, voice: str, output_path: str):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def generate_hook(clip: Dict, clip_id: str) -> Optional[Path]:
    """
    Generate a short voiceover hook for the start of the clip using edge-tts.
    Uses the AI-suggested hook_text from clip selection.
    Returns path to MP3 file, or None if disabled or failed.
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
    TEMP_DIR.mkdir(exist_ok=True)
    out_path = TEMP_DIR / f"{clip_id}_hook.mp3"

    try:
        asyncio.run(_generate_async(hook_text, voice, str(out_path)))

        if out_path.exists() and out_path.stat().st_size > 1000:
            print(f"🎤 Hook generated: \"{hook_text}\"")
            return out_path
        else:
            print("⚠️  Hook audio file is empty or missing")
            return None

    except Exception as e:
        # edge-tts failure is non-fatal — clip still uploads without hook
        print(f"⚠️  Voiceover generation failed (clip will upload without it): {e}")
        db.log_failure("voiceover", str(e), traceback.format_exc()[-300:])
        return None


def cleanup_hook(path: Optional[Path]):
    if path and path.exists():
        try:
            path.unlink()
        except Exception:
            pass
