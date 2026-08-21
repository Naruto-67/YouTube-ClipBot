# engine/model_discovery.py
"""
Auto model discovery — ported from Ghost Engine's LLMRouter concept.

Queries Gemini's model list at startup and automatically adds newer
free models (e.g. gemini-3.0-flash) at the top priority tier without
code changes. Falls back to the static config list if discovery fails.

This keeps ClipBot always using the newest free Gemini models even
when Google releases them after this code was written.
"""
import os
import re
import logging
from typing import Dict, List, Optional

from engine.config_manager import config_manager

logger = logging.getLogger(__name__)

# In TEST_MODE, skip all API calls (including free model listing) so the
# dry-run truly uses zero quota from any provider.
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

# Cache discovery results so we only call the provider APIs once per process.
# Key: discovered model names → merged configs. Re-computed on first use.
_DISCOVERY_CACHE: Optional[List[str]] = None
_GROQ_DISCOVERY_CACHE: Optional[List[str]] = None
_MERGE_CACHE: Optional[List[Dict]] = None


def _score_gemini_model(name: str) -> int:
    """
    Score Gemini models by version number automatically.
    Uses dynamic version parsing so any newer model (e.g. gemini-3.0-flash,
    gemini-4.5-flash-lite) is preferred over older ones without code changes.
    """
    n = name.lower()
    # Exclude non-text models — they break the text generation chain
    if any(x in n for x in ["vision", "audio", "tts", "embedding", "imagen"]):
        return -1

    # Extract the major.minor version number from the model name
    # e.g. "gemini-2.5-flash" → 2.5, "gemini-1.5-flash-8b" → 1.5
    m = re.search(r"gemini[-\s]?(\d+)\.(\d+)", n)
    if not m:
        return 0  # unknown format — rank lowest

    major = int(m.group(1))
    minor = int(m.group(2))

    # Score = (major * 100) + minor
    # This ensures: 3.0 > 2.5 > 2.0 > 1.5 > 1.0
    # So newer free models (e.g. 3.0-flash, 3.5-flash-lite) are always preferred.
    return (major * 100) + minor


# ── Groq model discovery ──────────────────────────────────────────────────
# Groq has no numeric version ladder but exposes a stable model list. We keep
# a preference ladder for known-good text models and append anything unknown so
# new Groq releases are picked up automatically without code changes.

_GROQ_PREFERENCE = [
    "llama-3.3-70b-versatile",   # Best quality free text model
    "llama-3.1-8b-instant",      # Fast / high volume
    "llama3-8b-8192",            # Older but reliable
    "llama3-70b-8192",           # Larger context fallback
    "mixtral-8x7b-32768",        # Mixtral fallback
    "gemma2-9b-it",              # Gemma fallback
]

# Groq transcription models usable via the Audio API (whisper).
_GROQ_WHISPER_MODELS = ["whisper-large-v3", "whisper-large-v3-turbo"]


def _score_groq_model(name: str) -> int:
    """Score Groq text models by a known preference ladder (unknown last)."""
    n = name.lower()
    if any(x in n for x in ["whisper", "tts", "playai"]):
        return -1  # not a text-generation model
    low = n
    for i, pref in enumerate(_GROQ_PREFERENCE):
        if low == pref:
            return 1000 - i
    return 0  # unknown — ranks lowest but still usable


def _discover_groq_models() -> List[str]:
    """Query Groq's model list. Returns sorted text-model names (best first)."""
    global _GROQ_DISCOVERY_CACHE
    if _GROQ_DISCOVERY_CACHE is not None:
        return _GROQ_DISCOVERY_CACHE

    if TEST_MODE:
        _GROQ_DISCOVERY_CACHE = []
        return []

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        _GROQ_DISCOVERY_CACHE = []
        return []

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        model_names = [m.id for m in client.models.list().data]
        scored = [(m, _score_groq_model(m)) for m in model_names]
        scored.sort(key=lambda x: x[1], reverse=True)
        _GROQ_DISCOVERY_CACHE = [m for m, s in scored if s >= 0]
        return _GROQ_DISCOVERY_CACHE
    except Exception as e:
        logger.warning(f"Groq model discovery failed: {e}")
        _GROQ_DISCOVERY_CACHE = []
        return []


def _discover_gemini_models() -> List[str]:
    """Query Gemini's model list. Returns sorted model names (best first).
    Results are cached so the API is only called once per process."""
    global _DISCOVERY_CACHE
    if _DISCOVERY_CACHE is not None:
        return _DISCOVERY_CACHE

    # TEST_MODE: never call the Gemini API — use static config only
    if TEST_MODE:
        _DISCOVERY_CACHE = []
        return []

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        _DISCOVERY_CACHE = []
        return []

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        all_models = list(client.models.list())
        model_names = [
            m.name.replace("models/", "")
            for m in all_models
            if hasattr(m, "name")
        ]
        # Sort by score descending (best first)
        model_names.sort(key=_score_gemini_model, reverse=True)
        _DISCOVERY_CACHE = model_names
        return model_names
    except Exception as e:
        logger.warning(f"Gemini model discovery failed: {e}")
        _DISCOVERY_CACHE = []
        return []


def _build_discovered_model_configs(
    discovered: List[str],
    max_stable: int,
    max_preview: int,
) -> List[Dict]:
    """
    Convert discovered model names into ClipBot model config dicts.
    Stable models get tier 1..N (highest priority). Preview/exp models
    get tier 5.. (after Groq, before last-resort pro).
    """
    stable = [m for m in discovered if "exp" not in m and "preview" not in m][:max_stable]
    preview = [m for m in discovered if "exp" in m or "preview" in m][:max_preview]

    configs: List[Dict] = []

    # Stable models — highest priority (tier 1, 2, 3...)
    for i, name in enumerate(stable):
        configs.append({
            "name": name,
            "provider": "gemini",
            "tier": i + 1,
            "rpm": 10,
            "rpd": 250,
            "tpm": 250000,
            "stable": True,
            "discovered": True,
        })

    # Preview/exp models — after Groq (tier 5+), before last-resort pro
    for i, name in enumerate(preview):
        configs.append({
            "name": name,
            "provider": "gemini",
            "tier": 5 + i,
            "rpm": 10,
            "rpd": 250,
            "tpm": 250000,
            "stable": False,
            "discovered": True,
        })

    return configs


def _merge_discovered_models_uncached(static_models: List[Dict]) -> List[Dict]:
    """
    Merge auto-discovered models with the static config list.
    (Internal — use merge_discovered_models, which caches.)

    Strategy:
    - If discovery is disabled or fails, return static list unchanged.
    - If discovery succeeds, discovered stable Gemini models REPLACE the static
      Gemini models (they're newer and preferred).
    - Discovered Groq models REPLACE the static Groq models when available.
    - Discovered Gemini preview models are appended after Groq.
    - The static 'gemini-2.5-pro' last-resort is always kept.
    """
    cfg = config_manager.providers
    discovery_cfg = cfg.get("auto_discovery", {})
    if not discovery_cfg.get("enabled", True):
        return static_models

    merged = list(static_models)

    # ── Gemini discovery (replaces static Gemini models) ──────────────
    discovered = _discover_gemini_models()
    if discovered:
        max_stable = discovery_cfg.get("max_stable_models", 4)
        max_preview = discovery_cfg.get("max_preview_models", 2)
        discovered_configs = _build_discovered_model_configs(
            discovered, max_stable, max_preview
        )
        # Remove static Gemini models (they're replaced by discovered newer ones)
        merged = [
            m for m in merged
            if not m.get("name", "").startswith("gemini")
            or "pro" in m.get("name", "").lower()  # keep last-resort pro
        ]
        merged = discovered_configs + merged

    # ── Groq discovery (replaces static Groq models when available) ───
    if discovery_cfg.get("discover_groq", True):
        groq_discovered = _discover_groq_models()
        if groq_discovered:
            merged = [
                m for m in merged
                if not m.get("name", "").startswith("llama-")
                and not m.get("name", "").startswith("llama3-")
                and not m.get("name", "").startswith("mixtral-")
                and not m.get("name", "").startswith("gemma")
            ]
            groq_configs = _build_groq_model_configs(groq_discovered)
            merged = merged + groq_configs

    # Sort by tier ascending
    merged.sort(key=lambda m: m.get("tier", 99))
    return merged


def _build_groq_model_configs(discovered: List[str]) -> List[Dict]:
    """
    Convert discovered Groq model names into ClipBot config dicts.
    Tier starts after Gemini tiers (5+) so Gemini remains primary.
    RPD mirrors the static Groq limits configured in providers.yaml.
    """
    cfg = config_manager.providers
    groq_cfg = cfg.get("groq", {})
    static_models = groq_cfg.get("models", [])
    # Pull rate limits from the static config for the same model name,
    # else fall back to sensible defaults.
    default_rpd = 14400
    source = {m.get("name"): m for m in static_models}

    configs: List[Dict] = []
    for i, name in enumerate(discovered):
        src = source.get(name, {})
        configs.append({
            "name": name,
            "provider": "groq",
            "tier": 5 + i,
            "rpm": src.get("rpm", 30),
            "rpd": src.get("rpd", default_rpd),
            "tpm": src.get("tpm", 250000),
            "stable": src.get("stable", True),
            "discovered": True,
        })
    return configs


def merge_discovered_models(static_models: List[Dict]) -> List[Dict]:
    """
    Cache-aware wrapper around _merge_discovered_models_uncached.
    The merged result is cached because static config rarely changes at runtime.
    """
    global _MERGE_CACHE, _DISCOVERY_CACHE
    # Invalidate cache if discovery hasn't run yet or static list changed size
    key = tuple(m.get("name") for m in static_models)
    cached_key = getattr(merge_discovered_models, "_cache_key", None)
    if _MERGE_CACHE is not None and cached_key == key:
        return list(_MERGE_CACHE)

    result = _merge_discovered_models_uncached(static_models)
    _MERGE_CACHE = list(result)
    merge_discovered_models._cache_key = key
    return list(result)


def get_effective_models() -> List[Dict]:
    """Return the effective model list (discovered + static fallback)."""
    static = config_manager.providers.get("gemini", {}).get("models", [])
    groq = config_manager.providers.get("groq", {}).get("models", [])
    # Annotate static models with their provider so provider detection in
    # quota_manager/llm_client never depends on name-prefix heuristics.
    for m in static:
        m.setdefault("provider", "gemini")
    for m in groq:
        m.setdefault("provider", "groq")
    all_static = static + groq
    return merge_discovered_models(all_static)


def get_discovered_groq_models() -> List[str]:
    """
    Return the raw discovered Groq model list (transcription models included).
    Used by transcriber.py to pick a Whisper model from Groq's API.
    """
    discovered = _discover_groq_models()
    if TEST_MODE or not discovered:
        # Fall back to known-good static transcription models
        return list(_GROQ_WHISPER_MODELS)
    # Whisper models score -1 in text-model discovery; query the raw list directly
    try:
        from groq import Groq
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            return list(_GROQ_WHISPER_MODELS)
        client = Groq(api_key=api_key)
        all_ids = [m.id for m in client.models.list().data]
        whisper = list(dict.fromkeys(
            [mid for mid in all_ids if "whisper" in mid.lower()]
        ))
        return whisper or list(_GROQ_WHISPER_MODELS)
    except Exception:
        return list(_GROQ_WHISPER_MODELS)
