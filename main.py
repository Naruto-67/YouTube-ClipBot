#!/usr/bin/env python3
# main.py
"""
ClipBot entry point.

Checks kill switch → restores DB → runs pipeline → persists DB.
"""
import os
import sys
import traceback


def main():
    # ── Kill switch ───────────────────────────────────────────────────────
    # Treat only explicit "true" / "1" as enabled.
    # Empty string (GitHub Actions var not set), "false", or any other
    # value halts the pipeline. Default is "true" when env var is absent.
    raw_enabled = os.environ.get("CLIPBOT_ENABLED", "true").strip().lower()
    # Treat absent/empty as "true" (backwards compat when var not configured)
    enabled = raw_enabled if raw_enabled else "true"
    if enabled not in ("true", "1"):
        print(f"🔴 CLIPBOT_ENABLED={raw_enabled!r} — system halted.")
        # Still notify Discord so you know the kill switch is active
        try:
            from engine.discord_notifier import notifier
            notifier.send_info("Kill Switch Active",
                               f"CLIPBOT_ENABLED={raw_enabled!r}. "
                               "Set to `true` to resume.")
        except Exception:
            pass
        sys.exit(0)

    # ── Restore DB from SQL dump (GitHub Actions starts fresh each run) ───
    try:
        from engine.database import db
        db.restore_from_dump()
    except Exception as e:
        print(f"⚠️  DB restore warning: {e}")

    # ── Run pipeline ──────────────────────────────────────────────────────
    try:
        from pipeline.orchestrator import Orchestrator
        Orchestrator().run()
    except Exception as e:
        tb = traceback.format_exc()
        print(f"❌ FATAL: {e}\n{tb}")
        try:
            from engine.discord_notifier import notifier
            from engine.database import db
            db.log_failure("main", str(e), tb)
            notifier.send_error("ClipBot Fatal Crash", str(e), tb)
        except Exception:
            pass
        sys.exit(1)

    # ── Persist DB back to SQL dump for git commit ────────────────────────
    try:
        from engine.database import db
        db.save_to_dump()
    except Exception as e:
        print(f"⚠️  DB save warning: {e}")


if __name__ == "__main__":
    main()
