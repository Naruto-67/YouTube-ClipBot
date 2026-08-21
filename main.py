#!/usr/bin/env python3
# main.py
"""
ClipBot entry point.

Checks kill switch → restores DB → runs pipeline → persists DB.

TEST_MODE: set TEST_MODE=true env var to run a dry-run pipeline that
produces no YouTube API calls, consumes no quota, and simulates uploads.
"""
import os
import sys
import traceback


def main():
    TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

    # ── Kill switch ───────────────────────────────────────────────────────
    # In TEST_MODE, the kill switch is ignored (always run).
    if not TEST_MODE:
        raw_enabled = os.environ.get("CLIPBOT_ENABLED", "true").strip().lower()
        enabled = raw_enabled if raw_enabled else "true"
        if enabled not in ("true", "1"):
            print(f"🔴 CLIPBOT_ENABLED={raw_enabled!r} — system halted.")
            try:
                from engine.discord_notifier import notifier
                notifier.send_info("Kill Switch Active",
                                   f"CLIPBOT_ENABLED={raw_enabled!r}. "
                                   "Set to `true` to resume.")
            except Exception:
                pass
            sys.exit(0)

    if TEST_MODE:
        print("🧪 [TEST MODE] Kill switch bypassed — running dry-run pipeline.")

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
