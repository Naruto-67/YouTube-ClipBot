# pipeline/seo_generator.py
import traceback
from typing import Dict, List, Optional

from engine.config_manager import config_manager
from engine.database import db
from engine.llm_client import llm_client
from pipeline.transcriber import get_words_in_range


def _load_safety_config() -> Dict:
    """Load safety rules from config/safety.yaml. Cached after first load."""
    if not hasattr(_load_safety_config, "_cache"):
        try:
            _load_safety_config._cache = config_manager._get("safety") or {}
        except Exception:
            _load_safety_config._cache = {}
    return _load_safety_config._cache


def _get_banned_words() -> set:
    """Return banned/demonetizing words from safety.yaml (dynamic, not hardcoded)."""
    safety = _load_safety_config()
    words = safety.get("demonetizing_words", [])
    if not words:
        # Absolute fallback if safety.yaml is missing or unreadable
        words = ["death", "kill", "murder", "suicide", "bomb",
                 "drug", "porn", "sex", "nsfw", "hate", "racist"]
    return {str(w).lower() for w in words}


def _get_fallback_tags() -> List[str]:
    """Return fallback tags from safety.yaml (dynamic)."""
    safety = _load_safety_config()
    tags = safety.get("fallback_tags", [])
    if not tags:
        tags = ["shorts", "viral", "funny", "trending", "bestmoments",
                "youtube", "entertainment", "satisfying", "reaction",
                "moments", "highlights", "clips", "foryou", "fyp"]
    return [str(t) for t in tags]


def _get_category_id(clip_type: str) -> str:
    """Map clip_type to YouTube category ID via safety.yaml (dynamic, not hardcoded)."""
    safety = _load_safety_config()
    routing = safety.get("clip_type_category_ids", {})
    return str(routing.get(clip_type, routing.get("default", "22")))


def generate_seo(clip: Dict, transcript: Dict, creator_name: str,
                 trending_context: Optional[Dict] = None) -> Dict:
    """
    Generate SEO metadata for a clip using AI + live trending data.

    Args:
        clip: clip dict from clip_bank (start_seconds, end_seconds, clip_type, etc.)
        transcript: full transcript dict with word timestamps
        creator_name: source creator name
        trending_context: optional trending context from trend_researcher

    Returns:
        {title: str, description: str, tags: List[str], category_id: str}
    Falls back to safe defaults if AI fails. Never returns None.
    """
    prompts_cfg = config_manager.prompts["seo_generator"]

    # Build transcript excerpt for context (~10 seconds of spoken text)
    clip_words = get_words_in_range(
        transcript,
        clip["start_seconds"],
        clip["end_seconds"],
        min_confidence=0.7,
    )
    excerpt = " ".join(w["word"] for w in clip_words[:80])

    # Build trending tags string for prompt injection
    from pipeline.trend_researcher import get_trending_tags_string
    trending_tags_str = get_trending_tags_string(trending_context)

    prompt = prompts_cfg["user"].format(
        creator=creator_name,
        clip_type=clip.get("clip_type", "engaging"),
        clip_reason=clip.get("reason", ""),
        hook_text=clip.get("hook_text", ""),
        transcript_excerpt=excerpt,
        trending_tags=trending_tags_str,
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
    banned = _get_banned_words()
    fallback_tags = _get_fallback_tags()

    # ── Title ────────────────────────────────────────────────────────────
    title = str(raw.get("title", "")).strip()
    if not title or len(title) < 5:
        title = _fallback_title(clip, creator_name)
    # Remove any banned words from title
    for bw in banned:
        import re
        title = re.sub(rf"\b{re.escape(bw)}\b", "", title, flags=re.IGNORECASE).strip()
    if not title or len(title) < 5:
        title = _fallback_title(clip, creator_name)
    # Ensure #shorts suffix
    if "#shorts" not in title.lower():
        title = title.rstrip() + " #shorts"
    # Cap at 100 chars (YouTube limit), keeping #shorts
    if len(title) > 100:
        base = title.replace(" #shorts", "").replace(" #Shorts", "")
        title = base[:93] + " #shorts"

    # ── Description ──────────────────────────────────────────────────────
    description = str(raw.get("description", "")).strip()
    if not description or len(description) < 10:
        description = (
            f"Best moments from {creator_name}. "
            "Like and subscribe for more! 🔥 #shorts"
        )
    if len(description) > 500:
        description = description[:497] + "..."

    # ── Tags ─────────────────────────────────────────────────────────────
    tags = raw.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    cleaned_tags = _clean_tags(tags, banned)
    # Pad with fallback tags if AI returned too few
    if len(cleaned_tags) < 8:
        cleaned_tags = list(dict.fromkeys(cleaned_tags + fallback_tags))[:15]

    # ── Category ID (dynamic from clip_type) ─────────────────────────────
    category_id = _get_category_id(clip.get("clip_type", ""))

    return {
        "title": title,
        "description": description,
        "tags": cleaned_tags[:15],
        "category_id": category_id,
    }


def _clean_tags(tags: List, banned: set) -> List[str]:
    """Remove # symbols, banned words, duplicates, and empty tags."""
    seen = set()
    result = []
    for tag in tags:
        tag = str(tag).strip().lstrip("#").lower()
        if not tag or tag in seen:
            continue
        if any(b in tag for b in banned):
            continue
        seen.add(tag)
        result.append(tag)
    return result


def _fallback_title(clip: Dict, creator_name: str) -> str:
    clip_type_map = {
        "funny":      "😂 Funniest Moment",
        "shocking":   "😱 Most Shocking Moment",
        "emotional":  "😢 Most Emotional Moment",
        "challenge":  "🏆 Best Challenge Moment",
        "reaction":   "🤯 Best Reaction",
        "satisfying": "✅ Most Satisfying Moment",
    }
    label = clip_type_map.get(clip.get("clip_type", ""), "Best Moment")
    return f"{creator_name} {label} #shorts"


def _fallback_seo(clip: Dict, creator_name: str) -> Dict:
    """Return fully safe default SEO when AI is unavailable."""
    fallback_tags = _get_fallback_tags()
    category_id = _get_category_id(clip.get("clip_type", ""))
    clip_type = clip.get("clip_type", "viral")
    return {
        "title": _fallback_title(clip, creator_name),
        "description": (
            f"Best moments from {creator_name}. "
            "Like and subscribe for more viral content! 🔥 #shorts"
        ),
        "tags": list(dict.fromkeys(
            [creator_name.lower().replace(" ", ""), clip_type] + fallback_tags
        ))[:15],
        "category_id": category_id,
    }

