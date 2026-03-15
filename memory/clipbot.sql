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
INSERT INTO "ai_reliability" VALUES(1,'2026-03-15T15:49:21.080983','gemini-2.5-flash','clip_selection',0,1,0,0.0);
INSERT INTO "ai_reliability" VALUES(2,'2026-03-15T15:49:24.194808','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(3,'2026-03-15T15:49:24.316346','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(4,'2026-03-15T15:49:27.424942','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(5,'2026-03-15T15:49:27.598830','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(6,'2026-03-15T15:49:30.712941','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(7,'2026-03-15T15:50:09.948827','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(8,'2026-03-15T15:50:13.056600','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(9,'2026-03-15T15:50:28.923841','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(10,'2026-03-15T15:50:32.031197','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(11,'2026-03-15T15:50:48.886005','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(12,'2026-03-15T15:50:51.994869','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(13,'2026-03-15T15:51:26.995187','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(14,'2026-03-15T15:51:30.104712','gemini-2.5-flash','clip_selection',0,0,0,0.0);
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
INSERT INTO "failures" VALUES(1,'2026-03-15T15:49:24.196580','llm_client','All 3 attempts failed','clip_selection');
INSERT INTO "failures" VALUES(2,'2026-03-15T15:49:27.427446','llm_client','All 3 attempts failed','clip_selection');
INSERT INTO "failures" VALUES(3,'2026-03-15T15:49:30.714899','llm_client','All 3 attempts failed','clip_selection');
INSERT INTO "failures" VALUES(4,'2026-03-15T15:49:30.716679','clip_selector','No clips from AI','AoN1K4c7VKE');
INSERT INTO "failures" VALUES(5,'2026-03-15T15:50:13.059074','llm_client','All 3 attempts failed','clip_selection');
INSERT INTO "failures" VALUES(6,'2026-03-15T15:50:13.060815','clip_selector','No clips from AI','hjkbqeWQAM8');
INSERT INTO "failures" VALUES(7,'2026-03-15T15:50:13.159505','fetcher.fetch_viral_videos','EOF occurred in violation of protocol (_ssl.c:2437)','Traceback (most recent call last):
  File "/home/runner/work/YouTube-ClipBot/YouTube-ClipBot/pipeline/fetcher.py", line 190, in fetch_viral_videos
    ).execute()
      ^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/googleapiclient/_helpers.py", line 130, in positional_wrapper
    return wrapped(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/googleapiclient/http.py", line 923, in execute
    resp, content = _retry_request(
                    ^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/googleapiclient/http.py", line 222, in _retry_request
    raise exception
  File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/googleapiclient/http.py", line 191, in _retry_request
    resp, content = http.request(uri, method, *args, **kwargs)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/google_auth_httplib2.py", line 218, in request
    response, content = self.http.request(
                        ^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httplib2/__init__.py", line 1727, in request
    (response, content) = self._request(
                          ^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httplib2/__init__.py", line 1447, in _request
    (response, content) = self._conn_request(conn, request_uri, method, body, headers)
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httplib2/__init__.py", line 1370, in _conn_request
    conn.request(method, request_uri, body, headers)
  File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/http/client.py", line 1303, in request
    self._se');
INSERT INTO "failures" VALUES(8,'2026-03-15T15:50:32.033546','llm_client','All 3 attempts failed','clip_selection');
INSERT INTO "failures" VALUES(9,'2026-03-15T15:50:32.035614','clip_selector','No clips from AI','3GNyw4uaAqU');
INSERT INTO "failures" VALUES(10,'2026-03-15T15:50:51.997276','llm_client','All 3 attempts failed','clip_selection');
INSERT INTO "failures" VALUES(11,'2026-03-15T15:50:51.999489','clip_selector','No clips from AI','IJkB-oapuks');
INSERT INTO "failures" VALUES(12,'2026-03-15T15:51:30.106703','llm_client','All 3 attempts failed','clip_selection');
INSERT INTO "failures" VALUES(13,'2026-03-15T15:51:30.108373','clip_selector','No clips from AI','9BsQpGhwVAY');
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
INSERT INTO "processed_videos" VALUES('AoN1K4c7VKE','MrBeast','Survive 30 Days Stranded With Your Ex, Win $250,000','no_clips',0,'2026-03-15T15:49:30.718201');
INSERT INTO "processed_videos" VALUES('hjkbqeWQAM8','MrBeast','Every Step You Take, Win $1,000','no_clips',0,'2026-03-15T15:50:13.062523');
INSERT INTO "processed_videos" VALUES('3GNyw4uaAqU','MrBeast','Subscribe for an iPhone','no_clips',0,'2026-03-15T15:50:32.037173');
INSERT INTO "processed_videos" VALUES('IJkB-oapuks','MrBeast','Giving Away $1,000,000 in Gifts To My Subscribers','no_clips',0,'2026-03-15T15:50:52.001519');
INSERT INTO "processed_videos" VALUES('9BsQpGhwVAY','Mark Rober','pride comes before flop','no_clips',0,'2026-03-15T15:51:30.110190');
CREATE TABLE quota_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at       TEXT NOT NULL,
                    api_name        TEXT NOT NULL,
                    model_name      TEXT,
                    units_used      INTEGER DEFAULT 1,
                    operation       TEXT
                );
INSERT INTO "quota_log" VALUES(1,'2026-03-15T15:25:45.125261','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(2,'2026-03-15T15:25:45.222768','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(3,'2026-03-15T15:25:45.373668','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(4,'2026-03-15T15:25:45.510578','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(5,'2026-03-15T15:49:21.078367','ai_gemini','gemini-2.5-flash',1,'generate');
INSERT INTO "quota_log" VALUES(6,'2026-03-15T15:50:14.139045','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(7,'2026-03-15T15:50:14.376724','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(8,'2026-03-15T15:50:14.580660','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(9,'2026-03-15T15:50:52.104291','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(10,'2026-03-15T15:50:52.240699','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(11,'2026-03-15T15:50:52.365190','youtube',NULL,1,'videos_list');
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
INSERT INTO "sqlite_sequence" VALUES('quota_log',11);
INSERT INTO "sqlite_sequence" VALUES('ai_reliability',14);
INSERT INTO "sqlite_sequence" VALUES('failures',13);
COMMIT;