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
INSERT INTO "failures" VALUES(1,'2026-03-15T04:30:01.158516','fetcher.download','yt-dlp failed after update: WARNING: [youtube] AoN1K4c7VKE: n challenge solving failed: Some formats may be missing. Ensure you have a supported JavaScript runtime and challenge solver script distribution installed. Review any warnings presented before this message. For more details, refer to  https://github.com/yt-dlp/yt-dlp/wiki/EJS
WARNING: Only images are available for download. use --list-formats to see them
ERROR: [youtube] AoN1K4c7VKE: Requested format is not available. Use --list-formats for a list of available for','AoN1K4c7VKE');
INSERT INTO "failures" VALUES(2,'2026-03-15T04:30:08.422792','fetcher.download','yt-dlp failed after update: WARNING: [youtube] hjkbqeWQAM8: n challenge solving failed: Some formats may be missing. Ensure you have a supported JavaScript runtime and challenge solver script distribution installed. Review any warnings presented before this message. For more details, refer to  https://github.com/yt-dlp/yt-dlp/wiki/EJS
WARNING: Only images are available for download. use --list-formats to see them
ERROR: [youtube] hjkbqeWQAM8: Requested format is not available. Use --list-formats for a list of available for','hjkbqeWQAM8');
INSERT INTO "failures" VALUES(3,'2026-03-15T04:30:17.084679','fetcher.download','yt-dlp failed after update: WARNING: [youtube] Xg1ro-zG7AM: n challenge solving failed: Some formats may be missing. Ensure you have a supported JavaScript runtime and challenge solver script distribution installed. Review any warnings presented before this message. For more details, refer to  https://github.com/yt-dlp/yt-dlp/wiki/EJS
WARNING: Only images are available for download. use --list-formats to see them
ERROR: [youtube] Xg1ro-zG7AM: Requested format is not available. Use --list-formats for a list of available for','Xg1ro-zG7AM');
INSERT INTO "failures" VALUES(4,'2026-03-15T04:30:25.396802','fetcher.download','yt-dlp failed after update: WARNING: [youtube] 3GNyw4uaAqU: n challenge solving failed: Some formats may be missing. Ensure you have a supported JavaScript runtime and challenge solver script distribution installed. Review any warnings presented before this message. For more details, refer to  https://github.com/yt-dlp/yt-dlp/wiki/EJS
WARNING: Only images are available for download. use --list-formats to see them
ERROR: [youtube] 3GNyw4uaAqU: Requested format is not available. Use --list-formats for a list of available for','3GNyw4uaAqU');
INSERT INTO "failures" VALUES(5,'2026-03-15T04:30:32.743478','fetcher.download','yt-dlp failed after update: WARNING: [youtube] IJkB-oapuks: n challenge solving failed: Some formats may be missing. Ensure you have a supported JavaScript runtime and challenge solver script distribution installed. Review any warnings presented before this message. For more details, refer to  https://github.com/yt-dlp/yt-dlp/wiki/EJS
WARNING: Only images are available for download. use --list-formats to see them
ERROR: [youtube] IJkB-oapuks: Requested format is not available. Use --list-formats for a list of available for','IJkB-oapuks');
INSERT INTO "failures" VALUES(6,'2026-03-15T04:30:41.695870','fetcher.download','yt-dlp failed after update: WARNING: [youtube] 9BsQpGhwVAY: Signature solving failed: Some formats may be missing. Ensure you have a supported JavaScript runtime and challenge solver script distribution installed. Review any warnings presented before this message. For more details, refer to  https://github.com/yt-dlp/yt-dlp/wiki/EJS
WARNING: [youtube] 9BsQpGhwVAY: n challenge solving failed: Some formats may be missing. Ensure you have a supported JavaScript runtime and challenge solver script distribution installed. Revie','9BsQpGhwVAY');
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
INSERT INTO "processed_videos" VALUES('AoN1K4c7VKE','MrBeast','Survive 30 Days Stranded With Your Ex, Win $250,000','download_failed',0,'2026-03-15T04:30:01.532288');
INSERT INTO "processed_videos" VALUES('hjkbqeWQAM8','MrBeast','Every Step You Take, Win $1,000','download_failed',0,'2026-03-15T04:30:08.783298');
INSERT INTO "processed_videos" VALUES('Xg1ro-zG7AM','Mark Rober','Engineers vs Junkyard RC Car Death Match','download_failed',0,'2026-03-15T04:30:17.290632');
INSERT INTO "processed_videos" VALUES('3GNyw4uaAqU','MrBeast','Subscribe for an iPhone','download_failed',0,'2026-03-15T04:30:25.795308');
INSERT INTO "processed_videos" VALUES('IJkB-oapuks','MrBeast','Giving Away $1,000,000 in Gifts To My Subscribers','download_failed',0,'2026-03-15T04:30:33.000381');
INSERT INTO "processed_videos" VALUES('9BsQpGhwVAY','Mark Rober','pride comes before flop','download_failed',0,'2026-03-15T04:30:41.986100');
CREATE TABLE quota_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at       TEXT NOT NULL,
                    api_name        TEXT NOT NULL,
                    model_name      TEXT,
                    units_used      INTEGER DEFAULT 1,
                    operation       TEXT
                );
INSERT INTO "quota_log" VALUES(1,'2026-03-15T04:29:53.119912','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(2,'2026-03-15T04:29:53.273015','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(3,'2026-03-15T04:29:53.454069','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(4,'2026-03-15T04:29:53.620866','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(5,'2026-03-15T04:30:08.891510','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(6,'2026-03-15T04:30:09.098555','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(7,'2026-03-15T04:30:09.230150','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(8,'2026-03-15T04:30:18.018132','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(9,'2026-03-15T04:30:18.193899','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(10,'2026-03-15T04:30:18.366310','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(11,'2026-03-15T04:30:33.070168','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(12,'2026-03-15T04:30:33.254756','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(13,'2026-03-15T04:30:33.407879','youtube',NULL,1,'videos_list');
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