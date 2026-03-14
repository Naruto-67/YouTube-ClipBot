# pipeline/seo_generator.py
import traceback
from typing import Dict, List, Optional

from engine.config_manager import config_manager
from engine.database import db
from engine.llm_client import llm_client
from pipeline.transcriber import get_words_in_range

# Words that trigger demonetization — auto-stripped from SEO metadata
_BANNED_WORDS = {
    "death", "kill", "murder", "suicide", "shooting", "bomb",
    "drug", "cocaine", "weed", "porn", "sex", "nsfw", "nude",
    "hate", "slur", "racist",
}

# Fallback tag pool when AI fails
_FALLBACK_TAGS = [
    "shorts", "viral", "funny", "reaction", "challenge",
    "bestmoments", "youtube", "trending", "entertainment", "satisfying",
]


def generate_seo(clip: Dict, transcript: Dict, creator_name: str) -> Dict:
    """
    Generate SEO metadata for a clip using AI.

    Returns:
        {title: str, description: str, tags: List[str]}

    Falls back to safe defaults if AI fails. Never returns None.
    """
    prompts_cfg = config_manager.prompts["seo_generator"]

    # Build a short transcript excerpt for context
    clip_words = get_words_in_range(
        transcript,
        clip["start_seconds"],
        clip["end_seconds"],
        min_confidence=0.7,
    )
    excerpt = " ".join(w["word"] for w in clip_words[:60])  # ~10 seconds of text

    prompt = prompts_cfg["user"].format(
        creator=creator_name,
        clip_type=clip.get("clip_type", "engaging"),
        clip_reason=clip.get("reason", ""),
        hook_text=clip.get("hook_text", ""),
        transcript_excerpt=excerpt,
    )

    result = llm_client.generate(
        prompt=prompt,
        system_prompt=prompts_cfg["system"],
        call_type="seo_generation",
    )

    if result is None:
        return _fallback_seo(clip, creator_name)

    seo = _validate_and_fix_seo(result, clip, creator_name)
    return seo


def _validate_and_fix_seo(raw: Dict, clip: Dict, creator_name: str) -> Dict:
    """Validate and auto-fix SEO metadata. Never fails."""
    # Title
    title = str(raw.get("title", "")).strip()
    if not title or len(title) < 5:
        title = _fallback_title(clip, creator_name)
    if "#shorts" not in title.lower():
        title = title.rstrip() + " #shorts"
    if len(title) > 60:
        # Trim while keeping #shorts
        base = title.replace(" #shorts", "").replace(" #Shorts", "")
        title = base[:54] + " #shorts"

    # Description
    description = str(raw.get("description", "")).strip()
    if not description or len(description) < 10:
        description = (
            f"Best moments from {creator_name}. "
            "Like and subscribe for more! 🔥 #shorts"
        )
    if len(description) > 500:
        description = description[:497] + "..."

    # Tags
    tags = raw.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    cleaned_tags = _clean_tags(tags)
    if len(cleaned_tags) < 5:
        cleaned_tags = list(
            dict.fromkeys(cleaned_tags + _FALLBACK_TAGS)
        )[:15]

    return {
        "title": title,
        "description": description,
        "tags": cleaned_tags[:15],
    }


def _clean_tags(tags: List) -> List[str]:
    """Remove # symbols, banned words, duplicates, and empty tags."""
    seen = set()
    result = []
    for tag in tags:
        tag = str(tag).strip().lstrip("#").lower()
        if not tag or tag in seen:
            continue
        if any(b in tag for b in _BANNED_WORDS):
            continue
        seen.add(tag)
        result.append(tag)
    return result


def _fallback_title(clip: Dict, creator_name: str) -> str:
    clip_type_map = {
        "funny": "😂 Funniest Moment",
        "shocking": "😱 Most Shocking Moment",
        "emotional": "😢 Most Emotional Moment",
        "challenge": "🏆 Best Challenge Moment",
        "reaction": "🤯 Best Reaction",
        "satisfying": "✅ Most Satisfying Moment",
    }
    label = clip_type_map.get(clip.get("clip_type", ""), "Best Moment")
    return f"{creator_name} {label} #shorts"


def _fallback_seo(clip: Dict, creator_name: str) -> Dict:
    """Return fully safe default SEO when AI is unavailable."""
    return {
        "title": _fallback_title(clip, creator_name),
        "description": (
            f"Best moments from {creator_name}. "
            "Like and subscribe for more viral content! 🔥 #shorts"
        ),
        "tags": [
            creator_name.lower().replace(" ", ""),
            "shorts", "viral", "funny", "reaction",
            "bestmoments", "youtube", "trending",
            "entertainment", clip.get("clip_type", "viral"),
            "clips", "moments", "highlights",
        ],
    }
