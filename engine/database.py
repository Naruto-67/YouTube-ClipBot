# engine/database.py
import sqlite3
import json
import contextlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

ROOT = Path(__file__).parent.parent
MEMORY_DIR = ROOT / "memory"
DB_PATH = MEMORY_DIR / "clipbot.db"
SQL_DUMP_PATH = MEMORY_DIR / "clipbot.sql"


class Database:
    """
    SQLite database with WAL mode for GitHub Actions safety.
    Persisted as plain SQL text dump for git-friendly diffs.
    """

    def __init__(self):
        MEMORY_DIR.mkdir(exist_ok=True)
        self.db_path = str(DB_PATH)
        self._init_tables()

    @contextlib.contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_tables(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS processed_videos (
                    video_id        TEXT PRIMARY KEY,
                    creator_name    TEXT NOT NULL,
                    title           TEXT,
                    status          TEXT NOT NULL,
                    clips_made      INTEGER DEFAULT 0,
                    processed_at    TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS clip_bank (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_video_id TEXT NOT NULL,
                    source_video_url TEXT,
                    creator_name    TEXT NOT NULL,
                    title           TEXT,
                    start_seconds   REAL NOT NULL,
                    end_seconds     REAL NOT NULL,
                    clip_type       TEXT,
                    hook_text       TEXT,
                    confidence      REAL DEFAULT 0.5,
                    reason          TEXT,
                    transcript_words_json TEXT,
                    status          TEXT DEFAULT 'pending',
                    created_at      TEXT NOT NULL,
                    uploaded_at     TEXT
                );

                CREATE TABLE IF NOT EXISTS manual_queue (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    url             TEXT NOT NULL UNIQUE,
                    video_id        TEXT,
                    creator_name    TEXT,
                    source          TEXT DEFAULT 'Manual',
                    note            TEXT,
                    max_clips       INTEGER DEFAULT 0,
                    status          TEXT DEFAULT 'pending',
                    added_at        TEXT NOT NULL,
                    processed_at    TEXT
                );

                CREATE TABLE IF NOT EXISTS uploaded_shorts (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_id      TEXT UNIQUE,
                    source_video_id TEXT,
                    creator_name    TEXT,
                    title           TEXT,
                    scheduled_at    TEXT,
                    uploaded_at     TEXT NOT NULL,
                    status          TEXT DEFAULT 'scheduled'
                );

                CREATE TABLE IF NOT EXISTS quota_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at       TEXT NOT NULL,
                    api_name        TEXT NOT NULL,
                    model_name      TEXT,
                    units_used      INTEGER DEFAULT 1,
                    operation       TEXT
                );

                CREATE TABLE IF NOT EXISTS analytics_history (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at     TEXT NOT NULL,
                    peak_windows    TEXT NOT NULL,
                    subscriber_count INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS failures (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    failed_at       TEXT NOT NULL,
                    module          TEXT NOT NULL,
                    error           TEXT NOT NULL,
                    context         TEXT
                );

                CREATE TABLE IF NOT EXISTS ai_reliability (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at       TEXT NOT NULL,
                    model_name      TEXT NOT NULL,
                    call_type       TEXT NOT NULL,
                    success         INTEGER NOT NULL,
                    parse_failed    INTEGER DEFAULT 0,
                    validation_failed INTEGER DEFAULT 0,
                    confidence      REAL DEFAULT 0.0
                );
            """)
            conn.commit()

    # ── Processed videos ─────────────────────────────────────────────────

    def is_video_processed(self, video_id: str) -> bool:
        """
        Returns True only for videos that completed successfully.
        Videos that failed at download or transcription are NOT considered
        processed — they will be retried on the next run.

        Statuses that block re-processing: 'banked', 'no_clips'
        Statuses that allow retry:         'download_failed', 'transcription_failed'
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM processed_videos
                   WHERE video_id = ?
                   AND status NOT IN ('download_failed', 'transcription_failed')""",
                (video_id,)
            ).fetchone()
            return row is not None

    def mark_video_processed(self, video_id: str, creator_name: str, title: str,
                              status: str, clips_made: int = 0):
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO processed_videos
                   (video_id, creator_name, title, status, clips_made, processed_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (video_id, creator_name, title, status, clips_made,
                 datetime.utcnow().isoformat()),
            )
            conn.commit()

    # ── Clip bank ────────────────────────────────────────────────────────

    def save_clip_to_bank(self, source_video_id: str, source_video_url: str,
                          creator_name: str, title: str, clip: Dict,
                          transcript_words: List[Dict]) -> int:
        """Save a clip spec to the bank. Returns the new bank entry id."""
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO clip_bank
                   (source_video_id, source_video_url, creator_name, title,
                    start_seconds, end_seconds, clip_type, hook_text,
                    confidence, reason, transcript_words_json, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    source_video_id, source_video_url, creator_name, title,
                    clip["start_seconds"], clip["end_seconds"],
                    clip.get("clip_type", "engaging"),
                    clip.get("hook_text", ""),
                    clip.get("confidence", 0.5),
                    clip.get("reason", ""),
                    json.dumps(transcript_words),
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_pending_bank_clips(self, limit: int = 10) -> List[Dict]:
        """Return pending clips from bank, highest confidence first."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM clip_bank WHERE status = 'pending'
                   ORDER BY confidence DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["transcript_words"] = json.loads(d.get("transcript_words_json") or "[]")
                result.append(d)
            return result

    def get_bank_count(self, status: str = "pending") -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM clip_bank WHERE status = ?", (status,)
            ).fetchone()
            return row[0] if row else 0

    def mark_bank_clip_uploaded(self, bank_id: int):
        with self._conn() as conn:
            conn.execute(
                """UPDATE clip_bank SET status='uploaded', uploaded_at=?
                   WHERE id=?""",
                (datetime.utcnow().isoformat(), bank_id),
            )
            conn.commit()

    def mark_bank_clip_failed(self, bank_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE clip_bank SET status='failed' WHERE id=?", (bank_id,)
            )
            conn.commit()

    def get_pending_source_video_ids(self) -> List[str]:
        """Return distinct source video IDs that still have pending clips in bank."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT source_video_id FROM clip_bank
                   WHERE status = 'pending'"""
            ).fetchall()
            return [r[0] for r in rows]

    # ── Manual queue ─────────────────────────────────────────────────────

    def sync_manual_queue_from_yaml(self, entries: List[Dict]):
        """
        Upsert manual queue entries from YAML.
        Only inserts new pending entries — never overwrites done/failed ones.
        """
        with self._conn() as conn:
            for e in entries:
                url = e.get("url", "").strip()
                if not url:
                    continue
                # Only insert if URL not already in table
                existing = conn.execute(
                    "SELECT status FROM manual_queue WHERE url=?", (url,)
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """INSERT INTO manual_queue
                           (url, creator_name, source, note, max_clips, status, added_at)
                           VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                        (
                            url,
                            e.get("creator_name", "Unknown"),
                            e.get("source", "Manual"),
                            e.get("note", ""),
                            e.get("max_clips", 0),
                            datetime.utcnow().isoformat(),
                        ),
                    )
            conn.commit()

    def get_pending_manual_queue(self) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM manual_queue WHERE status='pending'
                   ORDER BY added_at ASC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_queue_entry_done(self, entry_id: int, video_id: str = ""):
        with self._conn() as conn:
            conn.execute(
                """UPDATE manual_queue SET status='done', video_id=?,
                   processed_at=? WHERE id=?""",
                (video_id, datetime.utcnow().isoformat(), entry_id),
            )
            conn.commit()

    def mark_queue_entry_failed(self, entry_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE manual_queue SET status='failed' WHERE id=?", (entry_id,)
            )
            conn.commit()

    # ── Uploaded shorts ──────────────────────────────────────────────────

    def record_upload(self, youtube_id: str, source_video_id: str,
                      creator_name: str, title: str, scheduled_at: str):
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO uploaded_shorts
                   (youtube_id, source_video_id, creator_name, title,
                    scheduled_at, uploaded_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'scheduled')""",
                (youtube_id, source_video_id, creator_name, title,
                 scheduled_at, datetime.utcnow().isoformat()),
            )
            conn.commit()

    def get_scheduled_shorts(self) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM uploaded_shorts WHERE status='scheduled'"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_short_status(self, youtube_id: str, status: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE uploaded_shorts SET status=? WHERE youtube_id=?",
                (status, youtube_id),
            )
            conn.commit()

    def get_upcoming_scheduled_times(self) -> List[str]:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT scheduled_at FROM uploaded_shorts
                   WHERE status='scheduled' AND scheduled_at > ?
                   ORDER BY scheduled_at""",
                (now,),
            ).fetchall()
            return [r["scheduled_at"] for r in rows]

    # ── Quota log ────────────────────────────────────────────────────────

    def log_quota(self, api_name: str, units_used: int, operation: str,
                  model_name: Optional[str] = None):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO quota_log
                   (logged_at, api_name, model_name, units_used, operation)
                   VALUES (?, ?, ?, ?, ?)""",
                (datetime.utcnow().isoformat(), api_name, model_name,
                 units_used, operation),
            )
            conn.commit()

    def get_quota_used_today_utc(self, api_name: str) -> int:
        today = datetime.utcnow().date().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(units_used), 0) FROM quota_log
                   WHERE api_name=? AND logged_at LIKE ?""",
                (api_name, f"{today}%"),
            ).fetchone()
            return row[0] if row else 0

    # ── AI reliability ───────────────────────────────────────────────────

    def log_ai_call(self, model_name: str, call_type: str, success: bool,
                    parse_failed: bool = False, validation_failed: bool = False,
                    confidence: float = 0.0):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO ai_reliability
                   (logged_at, model_name, call_type, success,
                    parse_failed, validation_failed, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (datetime.utcnow().isoformat(), model_name, call_type,
                 int(success), int(parse_failed), int(validation_failed), confidence),
            )
            conn.commit()

    def get_ai_reliability_today(self) -> Dict:
        today = datetime.utcnow().date().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_reliability WHERE logged_at LIKE ?",
                (f"{today}%",),
            ).fetchall()
        if not rows:
            return {"total": 0, "success_rate": 100, "parse_failed": 0,
                    "validation_failed": 0}
        total = len(rows)
        success = sum(1 for r in rows if r["success"])
        return {
            "total": total,
            "success_rate": round(success / total * 100, 1),
            "parse_failed": sum(1 for r in rows if r["parse_failed"]),
            "validation_failed": sum(1 for r in rows if r["validation_failed"]),
        }

    # ── Failures ─────────────────────────────────────────────────────────

    def log_failure(self, module: str, error: str, context: str = ""):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO failures (failed_at, module, error, context)
                   VALUES (?, ?, ?, ?)""",
                (datetime.utcnow().isoformat(), module,
                 str(error)[:2000], str(context)[:2000]),
            )
            conn.commit()

    # ── Analytics ────────────────────────────────────────────────────────

    def save_analytics(self, peak_windows: List[str], subscriber_count: int):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO analytics_history
                   (recorded_at, peak_windows, subscriber_count)
                   VALUES (?, ?, ?)""",
                (datetime.utcnow().isoformat(),
                 json.dumps(peak_windows), subscriber_count),
            )
            conn.commit()

    def get_latest_analytics(self) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM analytics_history ORDER BY recorded_at DESC LIMIT 1"
            ).fetchone()
            if row:
                d = dict(row)
                d["peak_windows"] = json.loads(d["peak_windows"])
                return d
            return None

    # ── Maintenance ───────────────────────────────────────────────────────

    def prune_old_records(self, processed_videos_days: int = 90,
                          quota_log_days: int = 30, ai_reliability_days: int = 14,
                          failures_days: int = 14, analytics_days: int = 60,
                          clip_bank_days: int = 30) -> int:
        now = datetime.utcnow()
        total = 0
        with self._conn() as conn:
            total += conn.execute(
                "DELETE FROM processed_videos WHERE processed_at < ?",
                ((now - timedelta(days=processed_videos_days)).isoformat(),)
            ).rowcount
            total += conn.execute(
                "DELETE FROM quota_log WHERE logged_at < ?",
                ((now - timedelta(days=quota_log_days)).isoformat(),)
            ).rowcount
            total += conn.execute(
                "DELETE FROM ai_reliability WHERE logged_at < ?",
                ((now - timedelta(days=ai_reliability_days)).isoformat(),)
            ).rowcount
            total += conn.execute(
                "DELETE FROM failures WHERE failed_at < ?",
                ((now - timedelta(days=failures_days)).isoformat(),)
            ).rowcount
            total += conn.execute(
                "DELETE FROM analytics_history WHERE recorded_at < ?",
                ((now - timedelta(days=analytics_days)).isoformat(),)
            ).rowcount
            # Only prune uploaded bank entries (never prune pending ones)
            total += conn.execute(
                """DELETE FROM clip_bank WHERE status='uploaded'
                   AND uploaded_at < ?""",
                ((now - timedelta(days=clip_bank_days)).isoformat(),)
            ).rowcount
            conn.execute("VACUUM")
            conn.commit()
        return total

    def get_db_size_kb(self) -> int:
        if DB_PATH.exists():
            return int(DB_PATH.stat().st_size / 1024)
        return 0

    # ── Persistence ───────────────────────────────────────────────────────

    def save_to_dump(self) -> bool:
        try:
            with self._conn() as conn:
                lines = list(conn.iterdump())
            SQL_DUMP_PATH.write_text("\n".join(lines), encoding="utf-8")
            print(f"✅ DB exported to {SQL_DUMP_PATH.name}")
            return True
        except Exception as e:
            print(f"❌ DB export failed: {e}")
            return False

    def restore_from_dump(self):
        if DB_PATH.exists():
            return
        if not SQL_DUMP_PATH.exists():
            print("ℹ️  No existing DB dump — starting fresh.")
            return
        try:
            sql = SQL_DUMP_PATH.read_text(encoding="utf-8")
            with self._conn() as conn:
                conn.executescript(sql)
            print(f"✅ DB restored from {SQL_DUMP_PATH.name}")
        except Exception as e:
            print(f"⚠️  DB restore failed ({e}) — starting fresh.")
            if DB_PATH.exists():
                DB_PATH.unlink()


db = Database()
