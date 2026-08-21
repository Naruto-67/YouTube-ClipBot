# scripts/api_monitor.py — weekly technical stack audit for ClipBot
"""
Queries the LLM for actionable deprecation / new-model / quota changes across
the providers ClipBot depends on, and posts a summary to Discord.

Triggered by a weekly GitHub Actions workflow (or manually).
Never throws — dispatches an error embed on failure.
"""
from datetime import datetime

from engine.discord_notifier import notifier
from engine.llm_client import llm_client

PROVIDERS = [
    "Google Gemini API",
    "YouTube Data API v3",
    "Groq Cloud",
]

_AUDIT_PROMPT = """\
Today is {date}. Perform a technical search for the following providers:
{providers}

Check for:
1. Models being DEPRECATED or shut down in the next 30 days.
2. New 'Flash' / 'Lite' models that are cheaper or faster on the free tier.
3. Any changes to the YouTube 10,000 unit daily quota.
4. Any new free tier changes on Gemini or Groq.

Output a concise list of ACTIONABLE items for a lead developer.
If no changes found, reply exactly: No critical updates detected
"""


class APIMonitor:
    def run_audit(self):
        print("🕵️ [MONITOR] Initiating Weekly Technical Audit...")
        prompt = _AUDIT_PROMPT.format(
            date=datetime.now().strftime("%Y-%m-%d"),
            providers=", ".join(PROVIDERS),
        )

        try:
            result = llm_client.generate_text(
                prompt=prompt,
                system_prompt=(
                    "You are a technical auditor who monitors AI/API provider "
                    "changes. Be precise and concise."
                ),
                call_type="api_audit",
            )
            report_text = (result or "").strip()
            if not report_text:
                report_text = "No critical updates detected"

            if "No critical updates" in report_text:
                print("✅ [MONITOR] Stack is stable. No action required.")
                return

            notifier.send_info(
                "Weekly Stack Audit Result",
                f"```\n{report_text[:1500]}\n```",
            )
            print("📡 [MONITOR] Audit report dispatched to Discord.")

        except Exception as e:
            notifier.send_error("API Monitor", "Audit Failed", str(e))
            print(f"❌ [MONITOR] Audit failed: {e}")


if __name__ == "__main__":
    APIMonitor().run_audit()