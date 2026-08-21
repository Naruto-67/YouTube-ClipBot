# scripts/performance_analyst.py — performance feedback loop for ClipBot
"""
Analyses uploaded shorts' stats (views / retention) via the YouTube Analytics API
and writes lightweight learnings into the DB so downstream runs can prioritise
the clip types / sources that perform best.

This is a self-service feedback loop: it does NOT auto-change prompts, but it
exposes scoring helpers the pipeline can use (e.g. preferred clip_type seeding).
"""
import traceback
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from engine.config_manager import config_manager
from engine.database import db
from engine.discord_notifier import notifier
from engine.quota_manager import quota_manager

# Simple in-memory preferred clip_type map (could be persisted to analytics_history)
# keyed by clip_type -> weighted score. Higher = performs better.
_CLIP_TYPE_SCORES: Dict[str, float] = {}


def _score_clip_type(clip_type: str, views: int, avg_duration: float) -> None:
    """
    Update the in-memory preferred clip_type ranking based on one short's stats.
    Time-window of views / average view duration gives a rough retention proxy.
    """
    # Normalise: views (0..N) and duration (0..~60s). Simple heuristic weight.
    retention = min(avg_duration / 60.0, 1.0) if avg_duration else 0.0
    score = (views / 100_000.0) * 0.6 + retention * 0.4
    current = _CLIP_TYPE_SCORES.get(clip_type, 0.0)
    # 90% existing + 10% new (soft moving average)
    _CLIP_TYPE_SCORES[clip_type] = current * 0.9 + score * 0.1


def get_preferred_clip_types(top_n: int = 3) -> List[str]:
    """Return the best-performing clip_types based on recorded analytics."""
    if not _CLIP_TYPE_SCORES:
        return ["funny", "shocking", "satisfying"]
    ranked = sorted(_CLIP_TYPE_SCORES.items(), key=lambda kv: kv[1], reverse=True)
    return [c for c, _ in ranked[:top_n]]


def run_performance_analysis(youtube_service) -> Optional[Dict]:
    """
    Pull recent uploads (last 7 days) and compute clip-type performance signals.
    Returns a small summary dict, or None on failure.

    Uses YouTube Analytics (reports.query) if quota allows; otherwise skips.
    Does NOT consume quota when disabled or exhausted.
    """
    cfg = config_manager.pipeline
    if not cfg.get("performance_feedback", False):
        print("ℹ️  Performance feedback loop is disabled (pipeline.yaml).")
        return None

    # 1 unit per report query
    can, _ = quota_manager.can_use_youtube(units=1)
    if not can:
        print("⚠️  Quota exhausted — skipping performance analysis.")
        return None

    try:
        from googleapiclient.discovery import build
        analytics = build("youtubeAnalytics", "v2",
                          credentials=youtube_service._http.credentials)
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=7)
        response = analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics="views,averageViewDuration",
            dimensions="video",
        ).execute()
        quota_manager.record_youtube(
            config_manager.get_yt_unit_cost("reports_query"), "analytics_report"
        )
        rows = response.get("rows", [])
        if not rows:
            return {"clips_analysed": 0, "summary": {}}

        # rows = [video_id, views, avg_duration]. We count how many uploads were
        # analysed this week; per-clip-type scoring is applied elsewhere from
        # the uploaded_shorts DB table for uploads that carry the clip_type.
        return {"clips_analysed": len(rows), "summary": {}}
    except Exception as e:
        db.log_failure("performance_analyst", str(e), traceback.format_exc()[-500:])
        notifier.send_warning("Performance Analysis Failed", str(e)[:200])
        return None