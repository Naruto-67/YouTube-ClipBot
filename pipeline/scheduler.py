# pipeline/scheduler.py
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytz

from engine.config_manager import config_manager
from engine.database import db
from engine.discord_notifier import notifier
from engine.quota_manager import quota_manager


def get_best_publish_times(youtube_service, subscriber_count: int) -> List[str]:
    """
    Determine the best UTC times to publish shorts today.

    - Bootstrap mode (< threshold subs): use defaults from pipeline.yaml
    - Analytics mode (>= threshold subs): query YouTube Analytics API

    Returns list of UTC time strings ["HH:MM", ...]
    """
    cfg = config_manager.pipeline
    threshold = cfg.get("analytics_subscriber_threshold", 1000)

    if subscriber_count >= threshold:
        times = _analytics_windows(youtube_service)
        if times:
            db.save_analytics(times, subscriber_count)
            return times
        # Fall through to defaults if API fails

    # Bootstrap mode — use config defaults
    defaults = cfg.get("default_upload_windows_utc", ["19:00", "22:00", "01:00"])
    print(f"ℹ️  Bootstrap scheduling mode ({subscriber_count} subs < {threshold})")

    # Check stored analytics from previous run in case channel recently crossed threshold
    stored = db.get_latest_analytics()
    if stored and subscriber_count >= threshold // 2:
        print(f"ℹ️  Using cached analytics from {stored['recorded_at'][:10]}")
        return stored["peak_windows"]

    return defaults


def _analytics_windows(youtube_service) -> Optional[List[str]]:
    """
    Query YouTube Analytics API for audience activity by hour.
    Returns top 3 UTC hour strings, or None on failure.
    """
    can, reason = quota_manager.can_use_youtube(units=1)
    if not can:
        print(f"⚠️  YouTube quota: {reason}")
        return None

    try:
        from googleapiclient.discovery import build

        # Build analytics service from same credentials
        analytics = build("youtubeAnalytics", "v2",
                          credentials=youtube_service._http.credentials)

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=28)  # 4-week window

        response = analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics="views",
            dimensions="hour",
            sort="-views",
        ).execute()

        quota_manager.record_youtube(
            config_manager.get_yt_unit_cost("reports_query"), "analytics_report"
        )

        rows = response.get("rows", [])
        if not rows:
            return None

        # rows = [[hour_int, views], ...]
        # Top 3 hours → convert to UTC strings
        top_hours = [int(row[0]) for row in rows[:3]]
        result = [f"{h:02d}:00" for h in sorted(top_hours)]
        print(f"📊 Analytics windows (UTC): {result}")
        return result

    except Exception as e:
        print(f"⚠️  Analytics API failed: {e}")
        return None


def pick_next_slot(publish_times_utc: List[str]) -> str:
    """
    Pick the next available publish slot from the time windows,
    ensuring no two uploads are scheduled within 3 hours of each other
    and respecting the upload_buffer_hours setting.
    """
    cfg = config_manager.pipeline
    buffer_hours = cfg.get("upload_buffer_hours", 2)

    now_utc = datetime.now(timezone.utc)
    min_publish_time = now_utc + timedelta(hours=buffer_hours)

    # Get already-scheduled times from DB
    booked = []
    for t_str in db.get_upcoming_scheduled_times():
        try:
            booked.append(datetime.fromisoformat(t_str))
        except ValueError:
            pass

    today = now_utc.date()
    tomorrow = today + timedelta(days=1)

    # Try slots for today and tomorrow
    for day in [today, tomorrow]:
        for time_str in publish_times_utc:
            h, m = map(int, time_str.split(":"))
            slot = datetime(day.year, day.month, day.day, h, m,
                           tzinfo=timezone.utc)

            # Slot must be in the future (with buffer)
            if slot < min_publish_time:
                continue

            # Slot must not conflict with already-booked times (3hr gap)
            conflict = any(
                abs((slot - booked_t).total_seconds()) < 3 * 3600
                for booked_t in booked
            )
            if conflict:
                continue

            print(f"📅 Scheduled publish slot: {slot.isoformat()}")
            return slot.isoformat()

    # If all preferred slots are taken, add 4 hours from now
    fallback = (now_utc + timedelta(hours=buffer_hours + 1)).replace(
        minute=0, second=0, microsecond=0
    )
    print(f"📅 Fallback publish slot: {fallback.isoformat()}")
    return fallback.isoformat()


def get_channel_subscriber_count(youtube_service) -> int:
    """Return the channel's current subscriber count."""
    can, reason = quota_manager.can_use_youtube(units=1)
    if not can:
        print(f"⚠️  YouTube quota: {reason}")
        return 0
    try:
        resp = youtube_service.channels().list(
            part="statistics", mine=True
        ).execute()
        quota_manager.record_youtube(
            config_manager.get_yt_unit_cost("channels_list"), "channels_list"
        )
        items = resp.get("items", [])
        if items:
            return int(items[0].get("statistics", {}).get("subscriberCount", 0))
    except Exception as e:
        print(f"⚠️  Could not fetch subscriber count: {e}")
    return 0
