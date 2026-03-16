# pipeline/quality_checker.py
import subprocess
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

from engine.config_manager import config_manager
from engine.database import db
from engine.llm_client import llm_client


def check_video(path: Path) -> Tuple[bool, str]:
    """
    Technical video validation using ffprobe.
    Checks: resolution, duration, video stream, audio stream.
    Returns (passed, reason).
    """
    cfg = config_manager.pipeline
    expected_w = cfg.get("output_width", 1080)
    expected_h = cfg.get("output_height", 1920)
    min_sec = cfg.get("min_clip_seconds", 30)
    max_sec = cfg.get("max_clip_seconds", 60)  # hard cap — YouTube Shorts must be ≤60s

    if not path.exists():
        return False, "Output file does not exist"
    if path.stat().st_size < 100_000:
        return False, f"File too small ({path.stat().st_size} bytes) — likely corrupt"

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_streams", "-show_format",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False, f"ffprobe failed: {result.stderr[:200]}"

        probe = json.loads(result.stdout)
        streams = probe.get("streams", [])
        fmt = probe.get("format", {})

        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        if not video_streams:
            return False, "No video stream found"
        if not audio_streams:
            return False, "No audio stream found"

        vs = video_streams[0]
        width = vs.get("width", 0)
        height = vs.get("height", 0)

        if width != expected_w or height != expected_h:
            return False, f"Wrong resolution: {width}x{height} (expected {expected_w}x{expected_h})"

        duration = float(fmt.get("duration", 0))
        if duration < min_sec - 5:
            return False, f"Too short: {duration:.1f}s"
        if duration > max_sec:
            return False, f"Too long: {duration:.1f}s"

        return True, f"OK — {width}x{height}, {duration:.1f}s"

    except Exception as e:
        return False, f"ffprobe exception: {e}"


def check_metadata(seo: Dict, transcript_excerpt: str) -> Dict:
    """
    AI-powered metadata quality check.
    Validates: title length, description accuracy, tag cleanliness.
    Auto-fixes issues before returning.
    Falls back to original metadata if AI fails.
    """
    prompts_cfg = config_manager.prompts["quality_checker"]

    result = llm_client.generate(
        prompt=prompts_cfg["user"].format(
            title=seo.get("title", ""),
            description=seo.get("description", ""),
            tags=", ".join(seo.get("tags", [])),
            transcript_excerpt=transcript_excerpt[:500],
        ),
        system_prompt=prompts_cfg["system"],
        call_type="quality_check",
    )

    if result is None or not isinstance(result, dict):
        # AI unavailable — run rule-based checks only
        return _rule_based_check(seo)

    passed = result.get("passed", True)
    issues = result.get("issues", [])

    # Apply AI fixes if present, else keep originals
    fixed_seo = {
        "title": result.get("fixed_title") or seo["title"],
        "description": result.get("fixed_description") or seo["description"],
        "tags": result.get("fixed_tags") or seo["tags"],
    }

    if issues:
        print(f"⚠️  Metadata issues found and fixed: {issues}")

    return {
        "passed": passed,
        "issues": issues,
        "seo": fixed_seo,
    }


def _rule_based_check(seo: Dict) -> Dict:
    """Fallback metadata check using deterministic rules only."""
    issues = []
    title = seo.get("title", "")
    tags = seo.get("tags", [])

    if len(title) > 60:
        issues.append(f"Title too long: {len(title)} chars")
        title = title[:57] + "..."

    if "#shorts" not in title.lower():
        title = title.rstrip() + " #shorts"
        issues.append("Added missing #shorts to title")

    cleaned_tags = [t.lstrip("#") for t in tags]

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "seo": {**seo, "title": title, "tags": cleaned_tags},
    }
