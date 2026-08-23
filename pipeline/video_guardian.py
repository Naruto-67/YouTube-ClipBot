# pipeline/video_guardian.py
"""
Video Guardian — monitors all uploaded Shorts for post-upload issues.

Runs at the start of each daily pipeline execution. Uses videos.list()
to batch-check video statuses (1 unit per 50 videos — essentially free).

Detects:
- Videos deleted by YouTube (Content ID takedown, community guidelines)
- Videos rejected during processing
- Videos with failure reason

Actions:
- Updates DB health_status
- Sends Discord alert
- Optionally makes video private via videos.update (50 units)
"""
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from engine.config_manager import config_manager
from engine.database import db
from engine.discord_notifier import notifier
from engine.quota_manager import quota_manager

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"


@dataclass
class GuardianReport:
    checked: int = 0
    deleted: int = 0
    rejected: int = 0
    issues: List[str] = field(default_factory=list)

    def add_issue(self, msg: str):
        self.issues.append(msg)
        print(f"  🛡️  Guardian: {msg}")


def monitor_uploaded_videos(youtube_service) -> GuardianReport:
    """
    Check all recently-uploaded Shorts for health issues.
    Runs at the start of the daily pipeline. Returns a report of findings.
    """
    report = GuardianReport()

    if TEST_MODE:
        print("🧪 [TEST MODE] Skipping video guardian (no YouTube API calls)")
        return report

    cfg = config_manager.pipeline
    if not cfg.get("run_video_guardian", True):
        print("ℹ️  Video guardian disabled in pipeline.yaml")
        return report

    lookback_days = cfg.get("video_guardian_lookback_days", 30)
    auto_remove_on_rejection = cfg.get("auto_remove_on_rejection", True)

    # age_hours = lookback window in hours
    age_hours = lookback_days * 24
    videos_to_check = db.get_recent_uploads_for_health_check(age_hours=age_hours)

    if not videos_to_check:
        print("🛡️  Video Guardian: No videos to check")
        return report

    print(f"🛡️  Video Guardian: Checking {len(videos_to_check)} uploaded Shorts...")

    youtube_ids = [v["youtube_id"] for v in videos_to_check]
    id_to_record = {v["youtube_id"]: v for v in videos_to_check}
    report.checked = len(youtube_ids)

    statuses = _batch_check_video_statuses(youtube_service, youtube_ids)
    checked_at = datetime.now(timezone.utc).isoformat()

    for yt_id in youtube_ids:
        record = id_to_record[yt_id]
        status = statuses.get(yt_id)

        if status is None:
            # Video not found in API -> deleted/removed by YouTube
            if record.get("health_status") != "removed":
                report.deleted += 1
                issue = (f"Short removed by YouTube: "
                         f"'{record.get('title', yt_id)[:50]}' (ID: {yt_id})")
                report.add_issue(issue)
                db.update_short_health(yt_id, "removed", "not_found_in_api", checked_at)
                db.update_short_status(yt_id, "removed")
        else:
            upload_status = status.get("upload_status", "processed")
            rejection_reason = status.get("rejection_reason")
            failure_reason = status.get("failure_reason")

            if upload_status == "rejected" and rejection_reason:
                report.rejected += 1
                issue = (f"Short rejected (reason: {rejection_reason}): "
                         f"'{record.get('title', yt_id)[:50]}'")
                report.add_issue(issue)
                db.update_short_health(yt_id, "rejected", rejection_reason, checked_at)
                db.update_short_status(yt_id, "rejected")
                if auto_remove_on_rejection:
                    _make_video_private(youtube_service, yt_id)

            elif upload_status == "failed" and failure_reason:
                report.rejected += 1
                issue = (f"Short processing failed (reason: {failure_reason}): "
                         f"'{record.get('title', yt_id)[:50]}'")
                report.add_issue(issue)
                db.update_short_health(yt_id, "failed", failure_reason, checked_at)
                db.update_short_status(yt_id, "failed")

            else:
                # Healthy — just update the check timestamp
                db.update_short_health(yt_id, "ok", None, checked_at)

    if report.issues:
        notifier.send_post_monitor_report(report.checked, report.issues)
        print(f"🛡️  Guardian: {report.deleted} removed, {report.rejected} rejected")
    else:
        print(f"🛡️  Video Guardian: All {report.checked} Shorts healthy ✅")

    return report


def _batch_check_video_statuses(youtube_service,
                                 youtube_ids: List[str]) -> Dict[str, Dict]:
    """
    Batch-check video statuses via videos.list().
    Returns dict of {youtube_id -> status_dict}.
    Videos absent from the response have been deleted/removed.
    Cost: 1 unit per 50 videos (guardian_check).
    """
    statuses: Dict[str, Dict] = {}
    batch_size = 50

    for i in range(0, len(youtube_ids), batch_size):
        batch = youtube_ids[i:i + batch_size]
        can, reason = quota_manager.can_use_youtube(units=1)
        if not can:
            print(f"⚠️  Guardian: YouTube quota exhausted — {reason}")
            break
        try:
            response = youtube_service.videos().list(
                part="status",
                id=",".join(batch),
            ).execute()
            quota_manager.record_youtube(
                config_manager.get_yt_unit_cost("guardian_check"), "guardian_check"
            )
            for item in response.get("items", []):
                vid_id = item["id"]
                s = item.get("status", {})
                statuses[vid_id] = {
                    "upload_status": s.get("uploadStatus", "processed"),
                    "privacy_status": s.get("privacyStatus", "private"),
                    "rejection_reason": s.get("rejectionReason"),
                    "failure_reason": s.get("failureReason"),
                }
        except Exception as e:
            print(f"⚠️  Guardian: API error for batch {i // batch_size + 1}: {e}")

    return statuses


def _make_video_private(youtube_service, youtube_id: str) -> bool:
    """
    Make a rejected/flagged video private via videos.update() (50 units).
    Proactively hides content before the user notices a policy violation.
    """
    can, reason = quota_manager.can_use_youtube(units=50)
    if not can:
        print(f"⚠️  Guardian: Cannot make video private — {reason}")
        return False
    try:
        youtube_service.videos().update(
            part="status",
            body={"id": youtube_id, "status": {"privacyStatus": "private"}},
        ).execute()
        quota_manager.record_youtube(
            config_manager.get_yt_unit_cost("videos_update"), "guardian_make_private"
        )
        print(f"  🔒 Made {youtube_id} private (policy violation detected)")
        return True
    except Exception as e:
        print(f"⚠️  Guardian: Could not make {youtube_id} private: {e}")
        return False
