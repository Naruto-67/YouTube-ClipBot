# pipeline/trend_researcher.py
"""
Trend Researcher — fetches live trending data from YouTube to power
dynamic SEO generation and channel prioritization.

Runs once per daily pipeline session. Results are cached in DB so the
system degrades gracefully when API quota is low or API is unavailable.

Cost: ~3 YouTube units per run (1 per category × 3 categories).
"""
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from engine.config_manager import config_manager
from engine.database import db
from engine.quota_manager import quota_manager

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

# YouTube video category IDs to sample for trends
# 20 = Gaming, 22 = People & Blogs, 24 = Entertainment
_TREND_CATEGORIES = [
    ("24", "Entertainment"),
    ("22", "People & Blogs"),
    ("20", "Gaming"),
]

# Keyword signals that map video titles to ClipBot clip_types
_CLIP_TYPE_SIGNALS: Dict[str, List[str]] = {
    "funny":      ["funny", "comedy", "lol", "hilarious", "prank", "fail", "roast"],
    "shocking":   ["shocking", "insane", "crazy", "unbelievable", "wild", "dark"],
    "emotional":  ["emotional", "inspiring", "tearful", "moving", "heartwarming", "story"],
    "challenge":  ["challenge", " vs ", "competition", "trying", "24 hours", "survive"],
    "reaction":   ["reaction", "reacts", "responding", "watching", "first time"],
    "satisfying": ["satisfying", "perfect", "relaxing", "asmr", "smooth"],
}

# Module-level session cache (reset when process restarts = once per run)
_SESSION_CACHE: Optional[Dict] = None


def get_trending_context(youtube_service=None) -> Dict:
    """
    Return trending context for this session.
    Priority: in-memory cache > live API > DB snapshot cache > empty defaults.

    Returns dict:
    {
        "top_tags": List[str],        # Top trending tags (deduped, ranked)
        "hot_clip_types": List[str],  # clip_types trending right now
        "trending_topics": List[str], # Sample trending video titles
        "source": str,               # "live" | "cached" | "empty"
        "recorded_at": str,
    }
    """
    global _SESSION_CACHE
    if _SESSION_CACHE is not None:
        return _SESSION_CACHE

    cfg = config_manager.pipeline
    if TEST_MODE or not cfg.get("run_trend_research", True) or youtube_service is None:
        _SESSION_CACHE = _get_cached_or_empty()
        return _SESSION_CACHE

    # Try live fetch from YouTube Trending API
    context = _fetch_trending(youtube_service,
                              region=cfg.get("trend_research_region", "US"))
    if context:
        db.save_trending_snapshot(
            tags=context["top_tags"],
            clip_types=context["hot_clip_types"],
            region=cfg.get("trend_research_region", "US"),
        )
        context["source"] = "live"
        _SESSION_CACHE = context
        print(f"📈 Trending context: {len(context['top_tags'])} tags | "
              f"hot types: {context['hot_clip_types'][:3]}")
        return _SESSION_CACHE

    # Fall back to DB snapshot
    _SESSION_CACHE = _get_cached_or_empty()
    if _SESSION_CACHE["source"] == "cached":
        print(f"📈 Trending context: using cached snapshot ({_SESSION_CACHE.get('recorded_at', '')[:10]})")
    return _SESSION_CACHE


def get_trending_tags_string(context: Optional[Dict] = None) -> str:
    """
    Return trending tags as a comma-separated string for prompt injection.
    Returns empty string if no trending data is available.
    """
    ctx = context or _SESSION_CACHE or {}
    tags = ctx.get("top_tags", [])
    if not tags:
        return "(no trending data available this session)"
    return ", ".join(tags[:15])


def _fetch_trending(youtube_service, region: str = "US") -> Optional[Dict]:
    """Fetch trending videos across key categories and extract tags + topics."""
    all_tags: List[str] = []
    all_titles: List[str] = []

    for cat_id, cat_name in _TREND_CATEGORIES:
        can, reason = quota_manager.can_use_youtube(units=1)
        if not can:
            print(f"⚠️  Trend researcher: quota limited ({reason}) — stopping early")
            break
        try:
            resp = youtube_service.videos().list(
                part="snippet",
                chart="mostPopular",
                regionCode=region,
                videoCategoryId=cat_id,
                maxResults=10,
            ).execute()
            quota_manager.record_youtube(1, f"trending_{cat_name.lower().replace(' ', '_')}")

            for item in resp.get("items", []):
                snippet = item.get("snippet", {})
                tags = snippet.get("tags", [])
                title = snippet.get("title", "")
                all_tags.extend(t.lower().strip() for t in tags[:5] if t)
                if title:
                    all_titles.append(title)

        except Exception as e:
            print(f"⚠️  Trend fetch failed for {cat_name}: {e}")

    if not all_tags and not all_titles:
        return None

    # Rank tags by frequency
    tag_counts: Dict[str, int] = {}
    for t in all_tags:
        if t:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    top_tags = [t for t, _ in sorted(tag_counts.items(),
                                      key=lambda x: x[1], reverse=True)][:20]

    return {
        "top_tags": top_tags,
        "hot_clip_types": _infer_hot_clip_types(all_titles),
        "trending_topics": all_titles[:5],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def _infer_hot_clip_types(titles: List[str]) -> List[str]:
    """Infer which ClipBot clip_types are currently trending from video titles."""
    scores: Dict[str, int] = {t: 0 for t in _CLIP_TYPE_SIGNALS}
    for title in titles:
        tl = title.lower()
        for clip_type, keywords in _CLIP_TYPE_SIGNALS.items():
            if any(k in tl for k in keywords):
                scores[clip_type] += 1
    hot = [t for t, s in sorted(scores.items(), key=lambda x: x[1], reverse=True) if s > 0]
    return hot or ["funny", "shocking"]  # safe default if no signal found


def _get_cached_or_empty() -> Dict:
    """Return the most recent DB snapshot or empty defaults."""
    cached = db.get_latest_trending_snapshot()
    if cached:
        return {**cached, "source": "cached"}
    return {
        "top_tags": [],
        "hot_clip_types": ["funny", "shocking", "emotional"],
        "trending_topics": [],
        "source": "empty",
        "recorded_at": "",
    }
