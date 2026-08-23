# pipeline/channel_scorer.py
"""
Channel Scorer — dynamically adjusts source creator priority based on
historical productivity and content risk profile.

Replaces the static max_videos_per_run config with adaptive allocation.
Uses only data already in the local DB — zero extra API units.
"""
from typing import Dict, List

from engine.database import db


def score_and_allocate(creators: List[Dict],
                       total_budget: int = 8) -> List[Dict]:
    """
    Score creators and allocate discovery video slots dynamically.

    Args:
        creators: active creator configs from channels.yaml
        total_budget: total videos to discover across all creators this run

    Returns:
        creators list with dynamically adjusted max_videos_per_run.
        The returned value is capped to each creator's configured maximum.
    """
    if not creators:
        return creators

    scored = [(_score_creator(c), c) for c in creators]
    scored.sort(key=lambda x: x[0], reverse=True)

    total_score = sum(max(s, 1.0) for s, _ in scored)
    result = []
    budget_left = total_budget

    for i, (score, creator) in enumerate(scored):
        config_max = creator.get("max_videos_per_run", 2)
        is_last = i == len(scored) - 1

        if is_last:
            alloc = max(1, min(budget_left, config_max))
        else:
            proportion = max(score, 1.0) / total_score
            alloc = max(1, min(round(total_budget * proportion), config_max))
            budget_left -= alloc

        if budget_left <= 0 and not is_last:
            alloc = 0

        result.append({**creator, "max_videos_per_run": alloc})

    return result


def _score_creator(creator: Dict) -> float:
    """
    Score a creator (higher = more allocation priority).

    Factors:
    - Content ID risk: low=1.3x, medium=1.0x, high=0.6x
    - Historical bank contribution: +5 pts per clip (capped at +60)
    - Niche bonuses: podcast/interview niches tend to produce more clips per video
    """
    score = 100.0

    # Content ID risk multiplier
    risk_map = {"low": 1.3, "medium": 1.0, "high": 0.6}
    score *= risk_map.get(creator.get("content_id_risk", "medium"), 1.0)

    # Niche bonus: long-form = more clip opportunities per video
    niche_bonus = {
        "podcast_interview": 25,
        "comedy_podcast": 20,
        "business_interview": 18,
        "science_tech": 15,
        "stunts_challenge": 10,
        "gaming_variety": 5,
        "commentary_gaming": 5,
    }
    score += niche_bonus.get(creator.get("niche", ""), 0)

    # Historical productivity
    clips_banked = db.get_creator_bank_contribution(creator.get("name", ""))
    score += min(clips_banked * 5, 60)

    return score
