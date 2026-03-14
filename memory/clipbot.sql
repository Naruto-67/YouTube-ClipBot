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
                );
CREATE TABLE quota_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at       TEXT NOT NULL,
                    api_name        TEXT NOT NULL,
                    model_name      TEXT,
                    units_used      INTEGER DEFAULT 1,
                    operation       TEXT
                );
INSERT INTO "quota_log" VALUES(1,'2026-03-14T16:32:20.036215','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(2,'2026-03-14T16:32:20.154288','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(3,'2026-03-14T16:32:20.341344','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(4,'2026-03-14T16:32:20.521257','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(5,'2026-03-14T16:32:27.527967','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(6,'2026-03-14T16:32:27.722717','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(7,'2026-03-14T16:32:27.848149','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(8,'2026-03-14T16:32:32.281426','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(9,'2026-03-14T16:32:32.445495','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(10,'2026-03-14T16:32:32.596736','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(11,'2026-03-14T16:32:40.376158','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(12,'2026-03-14T16:32:40.538270','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(13,'2026-03-14T16:32:40.679425','youtube',NULL,1,'videos_list');
CREATE TABLE uploaded_shorts (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_id      TEXT UNIQUE,
                    source_video_id TEXT,
                    creator_name    TEXT,
                    title           TEXT,
                    scheduled_at    TEXT,
                    uploaded_at     TEXT NOT NULL,
                    status          TEXT DEFAULT 'scheduled'
                );
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('quota_log',13);
INSERT INTO "sqlite_sequence" VALUES('failures',6);
COMMIT;
