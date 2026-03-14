# scripts/post_monitor.py
"""
Checks all uploaded shorts for status changes (removed, claimed, restricted).
Run via: python scripts/post_monitor.py
Triggered by weekly GitHub Actions workflow.
"""
import traceback
from engine.database import db
from engine.discord_notifier import notifier
from engine.quota_manager import quota_manager
from engine.config_manager import config_manager
from pipeline.fetcher import get_youtube_service


def run():
    print("🔍 Running post-upload monitor...")
    shorts = db.get_scheduled_shorts()
    if not shorts:
        print("ℹ️  No scheduled/published shorts to check.")
        notifier.send_post_monitor_report(0, [])
        return

    try:
        yt, _ = get_youtube_service()
    except Exception as e:
        notifier.send_error("Post Monitor Auth Error", str(e))
        return

    issues = []
    batch_size = 50  # YouTube API allows 50 IDs per videos.list call

    yt_ids = [s["youtube_id"] for s in shorts if s.get("youtube_id")]

    for i in range(0, len(yt_ids), batch_size):
        batch = yt_ids[i : i + batch_size]
        can, reason = quota_manager.can_use_youtube(units=1)
        if not can:
            print(f"⚠️  YouTube quota: {reason}")
            break

        try:
            resp = yt.videos().list(
                part="status,snippet",
                id=",".join(batch),
            ).execute()
            quota_manager.record_youtube(
                config_manager.get_yt_unit_cost("videos_list"), "videos_list"
            )

            found_ids = {item["id"] for item in resp.get("items", [])}

            for yt_id in batch:
                if yt_id not in found_ids:
                    # Video was removed
                    db.update_short_status(yt_id, "removed")
                    issues.append(f"🗑️ Video removed: `{yt_id}` — check source creator")
                    print(f"⚠️  Video removed: {yt_id}")
                    continue

                for item in resp.get("items", []):
                    if item["id"] != yt_id:
                        continue
                    privacy = item.get("status", {}).get("privacyStatus", "")
                    if privacy == "privacyStatusUnspecified":
                        issues.append(f"⚠️ Privacy issue on `{yt_id}`")
                    db.update_short_status(yt_id, privacy)

        except Exception as e:
            print(f"⚠️  Monitor batch failed: {e}")
            db.log_failure("post_monitor", str(e), traceback.format_exc()[-300:])

    notifier.send_post_monitor_report(len(yt_ids), issues)
    print(f"✅ Checked {len(yt_ids)} shorts — {len(issues)} issue(s) found")


if __name__ == "__main__":
    run()
