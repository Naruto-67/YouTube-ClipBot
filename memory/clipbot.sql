BEGIN TRANSACTION;
CREATE TABLE ai_reliability (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at       TEXT NOT NULL,
                    model_name      TEXT NOT NULL,
                    call_type       TEXT NOT NULL,
                    success         INTEGER NOT NULL,
                    parse_failed    INTEGER DEFAULT 0,
                    validation_failed INTEGER DEFAULT 0,
                    confidence      REAL DEFAULT 0.0
                );
CREATE TABLE analytics_history (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at     TEXT NOT NULL,
                    peak_windows    TEXT NOT NULL,
                    subscriber_count INTEGER DEFAULT 0
                );
CREATE TABLE clip_bank (
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
CREATE TABLE creator_performance (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    creator_name TEXT NOT NULL,
                    recorded_at  TEXT NOT NULL,
                    avg_views    INTEGER DEFAULT 0,
                    clips_banked INTEGER DEFAULT 0,
                    clips_viral  INTEGER DEFAULT 0
                );
CREATE TABLE failures (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    failed_at       TEXT NOT NULL,
                    module          TEXT NOT NULL,
                    error           TEXT NOT NULL,
                    context         TEXT
                );
CREATE TABLE manual_queue (
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
CREATE TABLE processed_videos (
                    video_id        TEXT PRIMARY KEY,
                    creator_name    TEXT NOT NULL,
                    title           TEXT,
                    status          TEXT NOT NULL,
                    clips_made      INTEGER DEFAULT 0,
                    processed_at    TEXT NOT NULL
                , failed_attempts INTEGER DEFAULT 0);
CREATE TABLE quota_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at       TEXT NOT NULL,
                    api_name        TEXT NOT NULL,
                    model_name      TEXT,
                    units_used      INTEGER DEFAULT 1,
                    operation       TEXT
                );
CREATE TABLE trending_snapshots (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at  TEXT NOT NULL,
                    region       TEXT DEFAULT 'US',
                    trending_tags TEXT NOT NULL,
                    hot_clip_types TEXT NOT NULL
                );
CREATE TABLE uploaded_shorts (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_id      TEXT UNIQUE,
                    source_video_id TEXT,
                    creator_name    TEXT,
                    title           TEXT,
                    scheduled_at    TEXT,
                    uploaded_at     TEXT NOT NULL,
                    status          TEXT DEFAULT 'scheduled'
                , health_status TEXT DEFAULT 'ok', last_health_check TEXT, removal_reason TEXT);
CREATE INDEX idx_clip_bank_status
                        ON clip_bank (status);
CREATE INDEX idx_clip_bank_source
                        ON clip_bank (source_video_id, status);
CREATE INDEX idx_clip_bank_creator
                        ON clip_bank (creator_name, status);
CREATE INDEX idx_bank_range
                        ON clip_bank (source_video_id, start_seconds, end_seconds);
CREATE INDEX idx_processed_video_id
                        ON processed_videos (video_id);
CREATE INDEX idx_manual_queue_status
                        ON manual_queue (status);
CREATE INDEX idx_uploaded_status
                        ON uploaded_shorts (status);
CREATE INDEX idx_quota_api
                        ON quota_log (api_name, logged_at);
CREATE INDEX idx_ai_reliability
                        ON ai_reliability (call_type, logged_at);
DELETE FROM "sqlite_sequence";
COMMIT;