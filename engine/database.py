# engine/database.py
import os
import sqlite3
import json
import contextlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

ROOT = Path(__file__).parent.parent
MEMORY_DIR = ROOT / "memory"
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
DB_PATH = MEMORY_DIR / ("clipbot_test.db" if TEST_MODE else "clipbot.db")
SQL_DUMP_PATH = MEMORY_DIR / ("clipbot_test.sql" if TEST_MODE else "clipbot.sql")


class Database:
    """
    SQLite database with WAL mode for GitHub Actions safety.
    Persisted as plain SQL text dump for git-friendly diffs.

    TEST_MODE:
    - Uses a separate clipbot_test.db / clipbot_test.sql
    - Never touches the production database
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
                    processed_at    TEXT NOT NULL,
                    failed_attempts INTEGER DEFAULT 0
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
            # ── Indexes for frequent queries ──────────────────────────────
            try:
                conn.executescript("""
                    CREATE INDEX IF NOT EXISTS idx_clip_bank_status
                        ON clip_bank (status);
                    CREATE INDEX IF NOT EXISTS idx_clip_bank_source
                        ON clip_bank (source_video_id, status);
                    CREATE INDEX IF NOT EXISTS idx_clip_bank_creator
                        ON clip_bank (creator_name, status);
                    CREATE INDEX IF NOT EXISTS idx_bank_range
                        ON clip_bank (source_video_id, start_seconds, end_seconds);
                    CREATE INDEX IF NOT EXISTS idx_processed_video_id
                        ON processed_videos (video_id);
                    CREATE INDEX IF NOT EXISTS idx_manual_queue_status
                        ON manual_queue (status);
                    CREATE INDEX IF NOT EXISTS idx_uploaded_status
                        ON uploaded_shorts (status);
                    CREATE INDEX IF NOT EXISTS idx_quota_api
                        ON quota_log (api_name, logged_at);
                    CREATE INDEX IF NOT EXISTS idx_ai_reliability
                        ON ai_reliability (call_type, logged_at);
                """)
            except Exception:
                pass
            # ── New tables: trending snapshots, creator performance ────────
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trending_snapshots (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at  TEXT NOT NULL,
                    region       TEXT DEFAULT 'US',
                    trending_tags TEXT NOT NULL,
                    hot_clip_types TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS creator_performance (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    creator_name TEXT NOT NULL,
                    recorded_at  TEXT NOT NULL,
                    avg_views    INTEGER DEFAULT 0,
                    clips_banked INTEGER DEFAULT 0,
                    clips_viral  INTEGER DEFAULT 0
                );
            """)
            # ── Circuit breaker column (safe migration for existing DBs) ──
            try:
                conn.execute("ALTER TABLE processed_videos ADD COLUMN failed_attempts INTEGER DEFAULT 0")
            except Exception:
                pass  # Column already exists (or DB is fresh)
            # ── Video Guardian columns (safe migration) ────────────────────
            for col_def in [
                "health_status TEXT DEFAULT 'ok'",
                "last_health_check TEXT",
                "removal_reason TEXT",
            ]:
                try:
                    conn.execute(f"ALTER TABLE uploaded_shorts ADD COLUMN {col_def}")
                except Exception:
                    pass  # Column already exists
            conn.commit()

    # ── Processed videos ─────────────────────────────────────────────────

    def is_video_processed(self, video_id: str,
                           circuit_breaker_limit: int = 3) -> bool:
        """
        Returns True only for videos that completed successfully.
        Videos that failed at download or transcription are NOT considered
        processed — they will be retried on the next run.

        Statuses that block re-processing: 'banked', 'no_clips'
        Statuses that allow retry:         'download_failed', 'transcription_failed'
        Circuit breaker: after `circuit_breaker_limit` consecutive failures the
        video is treated as permanently processed (status flips to 'circuit_open')
        so we never re-attempt a video that keeps failing.
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT status, failed_attempts FROM processed_videos
                   WHERE video_id = ?""",
                (video_id,)
            ).fetchone()
            if row is None:
                return False
            status = row["status"]
            if status not in ("download_failed", "transcription_failed", "error"):
                return True
            # Failure status: allow retry only if under the circuit-breaker limit
            attempts = row["failed_attempts"] or 0
            return attempts >= circuit_breaker_limit

    def mark_video_processed(self, video_id: str, creator_name: str, title: str,
                              status: str, clips_made: int = 0):
        with self._conn() as conn:
            # Circuit breaker: bump a counter on failure statuses, reset on success
            failure_statuses = ("download_failed", "transcription_failed", "error")
            prev = conn.execute(
                "SELECT failed_attempts FROM processed_videos WHERE video_id=?",
                (video_id,)
            ).fetchone()
            attempts = 0
            if status in failure_statuses:
                attempts = (prev["failed_attempts"] or 0) + 1 if prev else 1
            conn.execute(
                """INSERT OR REPLACE INTO processed_videos
                   (video_id, creator_name, title, status, clips_made,
                    processed_at, failed_attempts)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (video_id, creator_name, title, status, clips_made,
                 datetime.utcnow().isoformat(), attempts),
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

    def get_pending_bank_clips(self, limit: int = 10,
                               exclude_source_ids: List[str] = None) -> List[Dict]:
        """
        Return pending clips from bank, highest confidence first.

        exclude_source_ids: if provided, prefer clips whose source_video_id is
        NOT in this set (content diversity — avoid uploading back-to-back clips
        from the same source video). If all pending clips share the excluded
        sources, falls back to returning the best clip regardless so the bank
        never stalls.
        """
        exclude = exclude_source_ids or []
        result = []
        with self._conn() as conn:
            rows = None
            if exclude:
                placeholders = ",".join("?" for _ in exclude)
                rows = conn.execute(
                    f"""SELECT * FROM clip_bank WHERE status = 'pending'
                        AND source_video_id NOT IN ({placeholders})
                        ORDER BY confidence DESC LIMIT ?""",
                    tuple(exclude) + (limit,)
                ).fetchall()
            if not rows or len(rows) == 0:
                # All pending are excluded sources (or no exclusion) — fall back
                rows = conn.execute(
                    """SELECT * FROM clip_bank WHERE status = 'pending'
                       ORDER BY confidence DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
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

    # ── Dedup helpers (prevent same video/shorts being re-created) ────────

    def has_banked_clip(self, source_video_id: str, start_seconds: float,
                        end_seconds: float) -> bool:
        """
        Check if a clip with the same source video + time range already
        exists in the bank (any status — pending, uploaded, or failed).
        This prevents duplicate shorts from ever being created.
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM clip_bank
                   WHERE source_video_id = ?
                   AND ABS(start_seconds - ?) < 2.0
                   AND ABS(end_seconds - ?) < 2.0
                   LIMIT 1""",
                (source_video_id, start_seconds, end_seconds),
            ).fetchone()
            return row is not None

    def get_banked_time_ranges(self, source_video_id: str) -> List[Dict]:
        """
        Return all time ranges already banked for a source video.
        Used by clip_selector to exclude already-used moments.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT start_seconds, end_seconds FROM clip_bank
                   WHERE source_video_id = ?""",
                (source_video_id,),
            ).fetchall()
            return [{"start": r["start_seconds"], "end": r["end_seconds"]} for r in rows]

    def has_any_banked_clips(self, source_video_id: str) -> bool:
        """Check if a video has ANY clips in the bank (any status)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM clip_bank WHERE source_video_id = ? LIMIT 1",
                (source_video_id,),
            ).fetchone()
            return row is not None

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
        """
        Prune old records. NOTE: processed_videos is NEVER pruned — it's the
        permanent dedup fingerprint that prevents the same video from being
        re-discovered and re-clipped. Only quota_log, ai_reliability, failures,
        analytics_history, and uploaded bank clips are pruned.
        """
        now = datetime.utcnow()
        total = 0
        with self._conn() as conn:
            # processed_videos is intentionally NOT pruned — permanent dedup
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
            # Prune FAILED bank clips after a shorter window so retries on
            # never-succeeding clips don't accumulate forever.
            total += conn.execute(
                """DELETE FROM clip_bank WHERE status='failed'
                   AND created_at < ?""",
                ((now - timedelta(days=max(3, clip_bank_days // 2))).isoformat(),)
            ).rowcount
            conn.execute("VACUUM")
            conn.commit()
        return total

    def get_db_size_kb(self) -> int:
        if DB_PATH.exists():
            return int(DB_PATH.stat().st_size / 1024)
        return 0

    # ── Video Guardian ────────────────────────────────────────────────────

    def get_recent_uploads_for_health_check(self,
                                             age_hours: int = 336) -> List[Dict]:
        """
        Return uploaded shorts that need a health check.
        Includes videos uploaded within age_hours that haven't been checked recently.
        age_hours default = 336 = 14 days (guardian checks weekly lookback).
        """
        cutoff = (datetime.utcnow() - timedelta(hours=age_hours)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM uploaded_shorts
                   WHERE uploaded_at > ?
                   AND health_status != 'removed'
                   AND (last_health_check IS NULL
                        OR last_health_check < datetime('now', '-20 hours'))
                   ORDER BY uploaded_at DESC""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_short_health(self, youtube_id: str, health_status: str,
                            removal_reason: Optional[str], checked_at: str):
        """Update the health status of an uploaded short."""
        with self._conn() as conn:
            conn.execute(
                """UPDATE uploaded_shorts
                   SET health_status=?, removal_reason=?, last_health_check=?
                   WHERE youtube_id=?""",
                (health_status, removal_reason, checked_at, youtube_id),
            )
            conn.commit()

    # ── Trending Snapshots ────────────────────────────────────────────────

    def save_trending_snapshot(self, tags: List[str],
                               clip_types: List[str], region: str = "US"):
        """Save a trending context snapshot from YouTube trending API."""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO trending_snapshots
                   (recorded_at, region, trending_tags, hot_clip_types)
                   VALUES (?, ?, ?, ?)""",
                (
                    datetime.utcnow().isoformat(),
                    region,
                    json.dumps(tags),
                    json.dumps(clip_types),
                ),
            )
            conn.commit()

    def get_latest_trending_snapshot(self) -> Optional[Dict]:
        """Return the most recent trending snapshot, or None if not available."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM trending_snapshots
                   ORDER BY recorded_at DESC LIMIT 1"""
            ).fetchone()
            if row:
                d = dict(row)
                d["top_tags"] = json.loads(d.pop("trending_tags", "[]"))
                d["hot_clip_types"] = json.loads(d.pop("hot_clip_types", "[]"))
                return d
            return None

    # ── Creator Performance ───────────────────────────────────────────────

    def get_creator_bank_contribution(self, creator_name: str) -> int:
        """Return total clips ever banked from this creator (any status)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM clip_bank WHERE creator_name=?",
                (creator_name,),
            ).fetchone()
            return row[0] if row else 0

    # ── Upload safety helpers ─────────────────────────────────────────────

    def get_uploads_this_week_count(self) -> int:
        """Return number of uploads made in the past 7 days."""
        cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM uploaded_shorts WHERE uploaded_at > ?",
                (cutoff,),
            ).fetchone()
            return row[0] if row else 0

    def get_recent_upload_titles(self, days: int = 7) -> List[str]:
        """Return titles of shorts uploaded in the past N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT title FROM uploaded_shorts WHERE uploaded_at > ?",
                (cutoff,),
            ).fetchall()
        return [r["title"] for r in rows if r["title"]]

    def get_last_upload_time(self) -> Optional[str]:
        """Return ISO timestamp of the most recent upload, or None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT uploaded_at FROM uploaded_shorts ORDER BY uploaded_at DESC LIMIT 1"
            ).fetchone()
        return row["uploaded_at"] if row else None

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