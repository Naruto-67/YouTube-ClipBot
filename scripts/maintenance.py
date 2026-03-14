# scripts/maintenance.py
"""
Weekly maintenance script.
Run via: python scripts/maintenance.py
Triggered by GitHub Actions weekly_maintenance.yml
"""
import shutil
from pathlib import Path

from engine.config_manager import config_manager
from engine.database import db
from engine.discord_notifier import notifier

ROOT = Path(__file__).parent.parent
TEMP_DIR = ROOT / "temp"
MEMORY_DIR = ROOT / "memory"


def run():
    print("🧹 Starting weekly maintenance...")
    cfg = config_manager.pipeline

    # 1 — Prune old DB records
    pruned = db.prune_old_records(
        processed_videos_days=cfg.get("prune_processed_videos_days", 90),
        quota_log_days=cfg.get("prune_quota_log_days", 30),
        ai_reliability_days=cfg.get("prune_ai_reliability_days", 14),
        failures_days=cfg.get("prune_failures_days", 14),
        analytics_days=cfg.get("prune_analytics_days", 60),
        clip_bank_days=cfg.get("prune_clip_bank_days", 30),
    )
    print(f"✂️  Pruned {pruned} old records")

    # 2 — Trim error log
    _trim_error_log(max_mb=cfg.get("error_log_max_mb", 1.0))

    # 3 — Clean stale temp files (shouldn't exist, but defensive)
    _clean_temp()

    # 4 — Export DB to SQL dump for git commit
    db.save_to_dump()

    # 5 — Measure sizes
    db_size_kb = db.get_db_size_kb()

    # 6 — Report to Discord
    notifier.send_storage_report(db_size_kb, pruned)

    print(f"✅ Maintenance complete. DB: {db_size_kb} KB | Pruned: {pruned}")


def _trim_error_log(max_mb: float):
    log_path = MEMORY_DIR / "error_log.txt"
    if not log_path.exists():
        return
    size_mb = log_path.stat().st_size / (1024 * 1024)
    if size_mb > max_mb:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        # Keep newest half
        log_path.write_text(
            "\n".join(lines[len(lines) // 2 :]), encoding="utf-8"
        )
        print(f"✂️  Trimmed error_log.txt ({size_mb:.1f} MB → ~{max_mb / 2:.1f} MB)")


def _clean_temp():
    if TEMP_DIR.exists():
        for f in TEMP_DIR.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                    print(f"🗑️  Removed stale temp file: {f.name}")
                except Exception:
                    pass


if __name__ == "__main__":
    run()
