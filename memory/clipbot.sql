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
INSERT INTO "failures" VALUES(1,'2026-03-14T17:22:28.611909','fetcher.download','yt-dlp failed after update','AoN1K4c7VKE');
INSERT INTO "failures" VALUES(2,'2026-03-14T17:22:35.115036','fetcher.download','yt-dlp failed after update','hjkbqeWQAM8');
INSERT INTO "failures" VALUES(3,'2026-03-14T17:22:43.166981','fetcher.download','yt-dlp failed after update','Xg1ro-zG7AM');
INSERT INTO "failures" VALUES(4,'2026-03-14T17:22:51.072513','fetcher.download','yt-dlp failed after update','3GNyw4uaAqU');
INSERT INTO "failures" VALUES(5,'2026-03-14T17:22:57.860605','fetcher.download','yt-dlp failed after update','IJkB-oapuks');
INSERT INTO "failures" VALUES(6,'2026-03-14T17:23:06.126989','fetcher.download','yt-dlp failed after update','9BsQpGhwVAY');
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
INSERT INTO "processed_videos" VALUES('AoN1K4c7VKE','MrBeast','Survive 30 Days Stranded With Your Ex, Win $250,000','download_failed',0,'2026-03-14T17:22:28.991764');
INSERT INTO "processed_videos" VALUES('hjkbqeWQAM8','MrBeast','Every Step You Take, Win $1,000','download_failed',0,'2026-03-14T17:22:35.384771');
INSERT INTO "processed_videos" VALUES('Xg1ro-zG7AM','Mark Rober','Engineers vs Junkyard RC Car Death Match','download_failed',0,'2026-03-14T17:22:43.490012');
INSERT INTO "processed_videos" VALUES('3GNyw4uaAqU','MrBeast','Subscribe for an iPhone','download_failed',0,'2026-03-14T17:22:51.557361');
INSERT INTO "processed_videos" VALUES('IJkB-oapuks','MrBeast','Giving Away $1,000,000 in Gifts To My Subscribers','download_failed',0,'2026-03-14T17:22:58.149613');
INSERT INTO "processed_videos" VALUES('9BsQpGhwVAY','Mark Rober','pride comes before flop','download_failed',0,'2026-03-14T17:23:06.449700');
CREATE TABLE quota_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at       TEXT NOT NULL,
                    api_name        TEXT NOT NULL,
                    model_name      TEXT,
                    units_used      INTEGER DEFAULT 1,
                    operation       TEXT
                );
INSERT INTO "quota_log" VALUES(1,'2026-03-14T17:22:19.211147','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(2,'2026-03-14T17:22:19.341368','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(3,'2026-03-14T17:22:19.520205','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(4,'2026-03-14T17:22:19.647130','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(5,'2026-03-14T17:22:35.459005','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(6,'2026-03-14T17:22:35.594782','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(7,'2026-03-14T17:22:35.768944','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(8,'2026-03-14T17:22:43.931785','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(9,'2026-03-14T17:22:44.104911','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(10,'2026-03-14T17:22:44.325090','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(11,'2026-03-14T17:22:58.224738','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(12,'2026-03-14T17:22:58.462034','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(13,'2026-03-14T17:22:58.633726','youtube',NULL,1,'videos_list');
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