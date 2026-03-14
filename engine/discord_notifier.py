# engine/discord_notifier.py
import json
import os
import traceback
from datetime import datetime
from typing import Dict, List, Optional

import requests

# Discord embed colours
COLOR_SUCCESS = 0x2ECC71   # green
COLOR_WARNING = 0xF39C12   # orange
COLOR_ERROR   = 0xE74C3C   # red
COLOR_INFO    = 0x3498DB   # blue
COLOR_REPORT  = 0x9B59B6   # purple


class DiscordNotifier:
    """
    Sends structured embed notifications to Discord.
    Silently swallows all errors so a Discord failure never
    breaks the pipeline.
    """

    def __init__(self):
        self._webhook_url: Optional[str] = None

    def _url(self) -> Optional[str]:
        if self._webhook_url is None:
            from engine.config_manager import config_manager
            env_key = config_manager.get_upload_channel().get(
                "discord_webhook_env", "DISCORD_WEBHOOK"
            )
            self._webhook_url = os.environ.get(env_key, "")
        return self._webhook_url or None

    def _send(self, payload: Dict) -> bool:
        url = self._url()
        if not url:
            print("⚠️  Discord webhook not configured — skipping notification.")
            return False
        try:
            resp = requests.post(
                url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            return resp.status_code in (200, 204)
        except Exception:
            return False

    def _embed(self, title: str, description: str, color: int,
               fields: Optional[List[Dict]] = None) -> Dict:
        embed: Dict = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "ClipBot AI"},
        }
        if fields:
            embed["fields"] = fields
        return {"username": "ClipBot", "embeds": [embed]}

    # ── Public methods ────────────────────────────────────────────────────

    def send_upload(self, title: str, youtube_url: str, creator: str,
                    scheduled_at: str):
        """Notify when a short is successfully uploaded."""
        self._send(self._embed(
            title="✅ Short Uploaded",
            description=f"**[{title}]({youtube_url})**",
            color=COLOR_SUCCESS,
            fields=[
                {"name": "🎬 Source Creator", "value": creator, "inline": True},
                {"name": "📅 Scheduled", "value": scheduled_at, "inline": True},
            ],
        ))

    def send_warning(self, title: str, detail: str):
        self._send(self._embed(
            title=f"⚠️ {title}",
            description=detail,
            color=COLOR_WARNING,
        ))

    def send_error(self, title: str, error: str, tb: str = ""):
        truncated_tb = tb[-800:] if tb else ""
        self._send(self._embed(
            title=f"🔴 {title}",
            description=f"```{error[:300]}```",
            color=COLOR_ERROR,
            fields=[{"name": "Traceback (tail)", "value": f"```{truncated_tb}```",
                     "inline": False}] if truncated_tb else None,
        ))

    def send_info(self, title: str, detail: str):
        self._send(self._embed(
            title=f"ℹ️ {title}",
            description=detail,
            color=COLOR_INFO,
        ))

    def send_daily_report(self, stats: Dict, quota_report: Dict, ai_report: Dict):
        """Send end-of-day summary."""
        yt = quota_report.get("youtube", {})
        models_str = "\n".join(
            f"└ `{name}`: {m['rpd_used']}/{m['rpd_limit']} calls"
            for name, m in quota_report.get("models", {}).items()
            if m["rpd_used"] > 0
        ) or "No AI calls made"

        fields = [
            {"name": "📤 Uploads Today",
             "value": f"{stats.get('uploaded', 0)} shorts scheduled", "inline": True},
            {"name": "🎬 Videos Checked",
             "value": str(stats.get("videos_checked", 0)), "inline": True},
            {"name": "❌ Errors",
             "value": str(stats.get("errors", 0)), "inline": True},
            {"name": "📊 YouTube Quota",
             "value": f"{yt.get('used', 0):,} / {yt.get('limit', 10000):,} units "
                      f"({yt.get('pct_used', 0)}%)",
             "inline": False},
            {"name": "🤖 AI Usage",
             "value": models_str, "inline": False},
            {"name": "🤖 AI Reliability",
             "value": f"Success rate: {ai_report.get('success_rate', 100)}% "
                      f"({ai_report.get('total', 0)} calls)",
             "inline": False},
        ]

        self._send(self._embed(
            title="📋 ClipBot Daily Report",
            description=f"Run completed at {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            color=COLOR_REPORT,
            fields=fields,
        ))

    def send_storage_report(self, db_size_kb: int, pruned: int):
        self._send(self._embed(
            title="🧹 Weekly Maintenance Complete",
            description="Database pruned and vacuumed.",
            color=COLOR_INFO,
            fields=[
                {"name": "🗄️ DB Size", "value": f"{db_size_kb} KB", "inline": True},
                {"name": "✂️ Records Pruned", "value": str(pruned), "inline": True},
            ],
        ))

    def send_token_health(self, healthy: bool, detail: str):
        self._send(self._embed(
            title="🔑 Token Health Check",
            description=detail,
            color=COLOR_SUCCESS if healthy else COLOR_ERROR,
        ))

    def send_post_monitor_report(self, checked: int, issues: List[str]):
        desc = "\n".join(issues) if issues else "All shorts are live and healthy ✅"
        self._send(self._embed(
            title="🔍 Post-Upload Monitor",
            description=desc,
            color=COLOR_WARNING if issues else COLOR_SUCCESS,
            fields=[{"name": "Videos Checked", "value": str(checked), "inline": True}],
        ))


notifier = DiscordNotifier()
