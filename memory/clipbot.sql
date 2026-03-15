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
INSERT INTO "ai_reliability" VALUES(1,'2026-03-15T15:00:12.038804','gemini-2.5-flash','clip_selection',0,1,0,0.0);
INSERT INTO "ai_reliability" VALUES(2,'2026-03-15T15:00:23.463362','gemini-2.5-flash','clip_selection',0,1,0,0.0);
INSERT INTO "ai_reliability" VALUES(3,'2026-03-15T15:00:31.966669','gemini-2.5-flash','clip_selection',0,1,0,0.0);
INSERT INTO "ai_reliability" VALUES(4,'2026-03-15T15:00:45.239752','gemini-2.5-flash','clip_selection',0,1,0,0.0);
INSERT INTO "ai_reliability" VALUES(5,'2026-03-15T15:00:54.295719','gemini-2.5-flash','clip_selection',0,1,0,0.0);
INSERT INTO "ai_reliability" VALUES(6,'2026-03-15T15:01:06.826240','gemini-2.5-flash','clip_selection',0,1,0,0.0);
INSERT INTO "ai_reliability" VALUES(7,'2026-03-15T15:01:55.195096','gemini-2.5-flash','clip_selection',1,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(8,'2026-03-15T15:02:13.414870','gemini-2.5-flash','clip_selection',1,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(9,'2026-03-15T15:02:30.257059','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(10,'2026-03-15T15:02:33.446721','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(11,'2026-03-15T15:03:09.907370','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(12,'2026-03-15T15:03:13.090342','gemini-2.5-flash','clip_selection',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(13,'2026-03-15T15:03:53.461509','gemini-2.5-flash','seo_generation',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(14,'2026-03-15T15:03:56.569533','gemini-2.5-flash','seo_generation',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(15,'2026-03-15T15:03:56.678684','gemini-2.5-flash','quality_check',0,0,0,0.0);
INSERT INTO "ai_reliability" VALUES(16,'2026-03-15T15:03:59.862150','gemini-2.5-flash','quality_check',0,0,0,0.0);
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
INSERT INTO "clip_bank" VALUES(1,'hjkbqeWQAM8','https://www.youtube.com/watch?v=hjkbqeWQAM8','MrBeast','Every Step You Take, Win $1,000',0.0,38.3,'challenge','Every step you remember, win $1,000!',0.95,'This clip captures the entire challenge for one participant, from the initial setup and increasing prize money to the confident guess and sudden, shocking failure.','[{"word": "Memorize", "start": 0.0, "end": 0.66, "confidence": 0.568}, {"word": "this", "start": 0.66, "end": 0.88, "confidence": 0.97}, {"word": "pattern.", "start": 0.88, "end": 1.18, "confidence": 0.762}, {"word": "Every", "start": 1.62, "end": 1.7, "confidence": 0.979}, {"word": "step", "start": 1.7, "end": 1.94, "confidence": 0.991}, {"word": "you", "start": 1.94, "end": 2.12, "confidence": 0.973}, {"word": "remember,", "start": 2.12, "end": 2.48, "confidence": 0.992}, {"word": "I''ll", "start": 2.66, "end": 2.8, "confidence": 0.965}, {"word": "give", "start": 2.8, "end": 2.94, "confidence": 0.996}, {"word": "you", "start": 2.94, "end": 3.1, "confidence": 0.997}, {"word": "$1", "start": 3.1, "end": 3.4, "confidence": 0.624}, {"word": ",000.", "start": 3.4, "end": 3.74, "confidence": 0.996}, {"word": "All", "start": 4.81, "end": 4.95, "confidence": 0.398}, {"word": "right,", "start": 4.95, "end": 5.05, "confidence": 0.999}, {"word": "we", "start": 5.13, "end": 5.21, "confidence": 0.897}, {"word": "got", "start": 5.21, "end": 5.33, "confidence": 0.811}, {"word": "this", "start": 5.33, "end": 5.55, "confidence": 0.999}, {"word": "one", "start": 5.55, "end": 5.73, "confidence": 0.996}, {"word": "right", "start": 5.73, "end": 5.91, "confidence": 0.992}, {"word": "here.", "start": 5.91, "end": 6.23, "confidence": 0.998}, {"word": "Okay.", "start": 6.37, "end": 6.53, "confidence": 0.419}, {"word": "And", "start": 6.87, "end": 6.99, "confidence": 0.7}, {"word": "we''re", "start": 6.99, "end": 7.11, "confidence": 0.994}, {"word": "going", "start": 7.11, "end": 7.15, "confidence": 0.417}, {"word": "to", "start": 7.15, "end": 7.23, "confidence": 0.998}, {"word": "come", "start": 7.23, "end": 7.37, "confidence": 0.999}, {"word": "right", "start": 7.37, "end": 7.55, "confidence": 0.996}, {"word": "here.", "start": 7.55, "end": 7.87, "confidence": 0.999}, {"word": "Careful,", "start": 8.33, "end": 8.67, "confidence": 0.987}, {"word": "one", "start": 8.83, "end": 8.93, "confidence": 0.967}, {"word": "wrong", "start": 8.93, "end": 9.13, "confidence": 0.997}, {"word": "step", "start": 9.13, "end": 9.39, "confidence": 0.998}, {"word": "and", "start": 9.39, "end": 9.55, "confidence": 0.833}, {"word": "you", "start": 9.55, "end": 9.67, "confidence": 0.998}, {"word": "lose", "start": 9.67, "end": 9.85, "confidence": 0.905}, {"word": "it", "start": 9.85, "end": 10.01, "confidence": 0.999}, {"word": "all.", "start": 10.01, "end": 10.21, "confidence": 0.998}, {"word": "You''re", "start": 10.37, "end": 10.53, "confidence": 0.805}, {"word": "now", "start": 10.53, "end": 10.67, "confidence": 0.952}, {"word": "up", "start": 10.67, "end": 10.81, "confidence": 0.99}, {"word": "to", "start": 10.81, "end": 11.01, "confidence": 0.995}, {"word": "three", "start": 11.01, "end": 11.15, "confidence": 0.455}, {"word": "grand.", "start": 11.15, "end": 11.49, "confidence": 0.998}, {"word": "Four", "start": 12.33, "end": 12.51, "confidence": 0.155}, {"word": "thousand", "start": 12.51, "end": 12.87, "confidence": 0.978}, {"word": "dollars.", "start": 12.87, "end": 13.19, "confidence": 0.997}, {"word": "Okay,", "start": 13.49, "end": 13.67, "confidence": 0.959}, {"word": "you", "start": 13.71, "end": 13.81, "confidence": 0.994}, {"word": "can", "start": 13.81, "end": 13.95, "confidence": 0.945}, {"word": "quit", "start": 13.95, "end": 14.11, "confidence": 0.99}, {"word": "at", "start": 14.11, "end": 14.29, "confidence": 0.969}, {"word": "any", "start": 14.29, "end": 14.43, "confidence": 0.999}, {"word": "point.", "start": 14.43, "end": 14.61, "confidence": 0.997}, {"word": "I''m", "start": 14.71, "end": 14.73, "confidence": 0.964}, {"word": "not", "start": 14.73, "end": 14.87, "confidence": 0.998}, {"word": "quitting,", "start": 14.87, "end": 15.09, "confidence": 0.978}, {"word": "Jimmy.", "start": 15.23, "end": 15.33, "confidence": 0.974}, {"word": "We''re", "start": 15.37, "end": 15.53, "confidence": 0.992}, {"word": "making", "start": 15.53, "end": 15.75, "confidence": 0.996}, {"word": "it.", "start": 15.75, "end": 15.91, "confidence": 0.998}, {"word": "Oh", "start": 15.91, "end": 16.01, "confidence": 0.98}, {"word": "my", "start": 16.01, "end": 16.13, "confidence": 0.773}, {"word": "gosh,", "start": 16.13, "end": 16.23, "confidence": 0.81}, {"word": "he", "start": 16.33, "end": 16.37, "confidence": 0.909}, {"word": "is", "start": 16.37, "end": 16.49, "confidence": 0.934}, {"word": "printing", "start": 16.49, "end": 16.81, "confidence": 0.996}, {"word": "money", "start": 16.81, "end": 17.09, "confidence": 0.998}, {"word": "right", "start": 17.09, "end": 17.27, "confidence": 0.995}, {"word": "now.", "start": 17.27, "end": 17.49, "confidence": 0.999}, {"word": "Okay,", "start": 18.13, "end": 18.39, "confidence": 0.985}, {"word": "eight", "start": 18.59, "end": 18.73, "confidence": 0.233}, {"word": "thousand", "start": 18.73, "end": 19.03, "confidence": 0.993}, {"word": "dollars.", "start": 19.03, "end": 19.41, "confidence": 0.998}, {"word": "Thousand", "start": 19.91, "end": 20.13, "confidence": 0.771}, {"word": "dollars.", "start": 20.13, "end": 20.53, "confidence": 0.994}, {"word": "Okay,", "start": 20.91, "end": 21.09, "confidence": 0.93}, {"word": "nine", "start": 21.17, "end": 21.29, "confidence": 0.963}, {"word": "thousand.", "start": 21.29, "end": 21.61, "confidence": 0.991}, {"word": "You", "start": 22.07, "end": 22.21, "confidence": 0.992}, {"word": "can", "start": 22.21, "end": 22.41, "confidence": 0.998}, {"word": "quit", "start": 22.41, "end": 22.55, "confidence": 0.997}, {"word": "at", "start": 22.55, "end": 22.71, "confidence": 0.992}, {"word": "any", "start": 22.71, "end": 22.87, "confidence": 0.999}, {"word": "point,", "start": 22.87, "end": 23.17, "confidence": 1.0}, {"word": "but", "start": 23.17, "end": 23.37, "confidence": 0.997}, {"word": "it''s", "start": 23.37, "end": 23.49, "confidence": 0.997}, {"word": "up", "start": 23.49, "end": 23.61, "confidence": 1.0}, {"word": "to", "start": 23.61, "end": 23.79, "confidence": 0.999}, {"word": "you.", "start": 23.79, "end": 23.97, "confidence": 0.999}, {"word": "We", "start": 24.51, "end": 24.67, "confidence": 0.989}, {"word": "got", "start": 24.67, "end": 24.79, "confidence": 0.517}, {"word": "to", "start": 24.79, "end": 24.89, "confidence": 0.986}, {"word": "take", "start": 24.89, "end": 25.01, "confidence": 0.999}, {"word": "this", "start": 25.01, "end": 25.15, "confidence": 0.743}, {"word": "step.", "start": 25.15, "end": 25.43, "confidence": 0.999}, {"word": "Ten", "start": 26.15, "end": 26.31, "confidence": 0.89}, {"word": "thousand", "start": 26.31, "end": 26.75, "confidence": 0.995}, {"word": "dollars.", "start": 26.75, "end": 27.07, "confidence": 0.999}, {"word": "Before", "start": 27.07, "end": 27.41, "confidence": 0.631}, {"word": "his", "start": 27.41, "end": 27.67, "confidence": 0.991}, {"word": "next", "start": 27.67, "end": 27.87, "confidence": 0.995}, {"word": "step,", "start": 27.87, "end": 28.07, "confidence": 0.834}, {"word": "this", "start": 28.15, "end": 28.25, "confidence": 0.982}, {"word": "is", "start": 28.25, "end": 28.37, "confidence": 0.989}, {"word": "a", "start": 28.37, "end": 28.51, "confidence": 0.994}, {"word": "smaller", "start": 28.51, "end": 29.01, "confidence": 0.993}, {"word": "version", "start": 29.01, "end": 29.33, "confidence": 0.996}, {"word": "of", "start": 29.33, "end": 29.51, "confidence": 0.997}, {"word": "what", "start": 29.51, "end": 29.65, "confidence": 0.997}, {"word": "we", "start": 29.65, "end": 29.81, "confidence": 0.999}, {"word": "did", "start": 29.81, "end": 29.95, "confidence": 0.998}, {"word": "in", "start": 29.95, "end": 30.05, "confidence": 0.954}, {"word": "our", "start": 30.05, "end": 30.15, "confidence": 0.992}, {"word": "brand", "start": 30.15, "end": 30.45, "confidence": 0.99}, {"word": "new", "start": 30.45, "end": 30.67, "confidence": 0.855}, {"word": "episode", "start": 30.67, "end": 30.91, "confidence": 0.996}, {"word": "of", "start": 30.91, "end": 31.09, "confidence": 0.997}, {"word": "B", "start": 31.09, "end": 31.21, "confidence": 0.355}, {"word": "-Scans.", "start": 31.21, "end": 31.57, "confidence": 0.776}, {"word": "Go", "start": 31.73, "end": 31.83, "confidence": 0.982}, {"word": "watch", "start": 31.83, "end": 32.03, "confidence": 0.996}, {"word": "B", "start": 32.03, "end": 32.23, "confidence": 0.94}, {"word": "-Scan", "start": 32.23, "end": 32.35, "confidence": 0.693}, {"word": "season", "start": 32.35, "end": 32.63, "confidence": 0.456}, {"word": "two", "start": 32.63, "end": 32.83, "confidence": 0.464}, {"word": "on", "start": 32.83, "end": 32.97, "confidence": 0.982}, {"word": "Prime", "start": 32.97, "end": 33.17, "confidence": 0.978}, {"word": "Video.", "start": 33.17, "end": 33.43, "confidence": 0.845}, {"word": "Let''s", "start": 33.67, "end": 33.79, "confidence": 0.982}, {"word": "see", "start": 33.79, "end": 33.87, "confidence": 0.998}, {"word": "what", "start": 33.87, "end": 33.91, "confidence": 0.999}, {"word": "he", "start": 33.91, "end": 33.99, "confidence": 0.991}, {"word": "does.", "start": 33.99, "end": 34.21, "confidence": 0.999}, {"word": "I", "start": 34.43, "end": 34.43, "confidence": 0.368}, {"word": "think", "start": 34.43, "end": 34.85, "confidence": 0.708}, {"word": "I''m", "start": 34.85, "end": 35.13, "confidence": 0.661}, {"word": "pretty", "start": 35.13, "end": 35.29, "confidence": 0.997}, {"word": "sure", "start": 35.29, "end": 35.49, "confidence": 0.999}, {"word": "it''s", "start": 35.49, "end": 35.63, "confidence": 0.981}, {"word": "this", "start": 35.63, "end": 35.77, "confidence": 0.998}, {"word": "one,", "start": 35.77, "end": 35.93, "confidence": 0.996}, {"word": "Jimmy.", "start": 35.99, "end": 36.13, "confidence": 0.985}, {"word": "That''s", "start": 36.43, "end": 36.55, "confidence": 0.761}, {"word": "up", "start": 36.55, "end": 36.67, "confidence": 0.998}, {"word": "to", "start": 36.67, "end": 36.85, "confidence": 0.999}, {"word": "you.", "start": 36.85, "end": 37.13, "confidence": 0.999}, {"word": "Oh", "start": 37.59, "end": 37.71, "confidence": 0.956}, {"word": "no.", "start": 37.71, "end": 38.01, "confidence": 0.654}]','uploaded','2026-03-15T15:01:55.197014','2026-03-15T15:04:02.679992');
CREATE TABLE failures (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    failed_at       TEXT NOT NULL,
                    module          TEXT NOT NULL,
                    error           TEXT NOT NULL,
                    context         TEXT
                );
INSERT INTO "failures" VALUES(1,'2026-03-15T15:01:06.827589','clip_selector','No clips from AI','AoN1K4c7VKE');
INSERT INTO "failures" VALUES(2,'2026-03-15T15:01:55.247408','fetcher.fetch_viral_videos','EOF occurred in violation of protocol (_ssl.c:2437)','Traceback (most recent call last):
  File "/home/runner/work/YouTube-ClipBot/YouTube-ClipBot/pipeline/fetcher.py", line 194, in fetch_viral_videos
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
INSERT INTO "failures" VALUES(3,'2026-03-15T15:02:13.416350','clip_selector','No clips from AI','3GNyw4uaAqU');
INSERT INTO "failures" VALUES(4,'2026-03-15T15:02:33.448472','llm_client','All 3 attempts failed','clip_selection');
INSERT INTO "failures" VALUES(5,'2026-03-15T15:02:33.450120','clip_selector','No clips from AI','IJkB-oapuks');
INSERT INTO "failures" VALUES(6,'2026-03-15T15:03:13.092190','llm_client','All 3 attempts failed','clip_selection');
INSERT INTO "failures" VALUES(7,'2026-03-15T15:03:13.093770','clip_selector','No clips from AI','9BsQpGhwVAY');
INSERT INTO "failures" VALUES(8,'2026-03-15T15:03:17.420566','voiceover','403, message=''Invalid response status'', url=''wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=6A5AA1D4EAFF4E9FB37E23D68491D6F4&Sec-MS-GEC=67761E9D092F32097C224E059925271555EC876F7AFCBD6EB88549C0C68C1728&Sec-MS-GEC-Version=1-130.0.2849.68&ConnectionId=e62fd35c69634738a216c412ac532fc5''','status'', url=''wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=6A5AA1D4EAFF4E9FB37E23D68491D6F4&Sec-MS-GEC=67761E9D092F32097C224E059925271555EC876F7AFCBD6EB88549C0C68C1728&Sec-MS-GEC-Version=1-130.0.2849.68&ConnectionId=e62fd35c69634738a216c412ac532fc5''
');
INSERT INTO "failures" VALUES(9,'2026-03-15T15:03:56.571506','llm_client','All 3 attempts failed','seo_generation');
INSERT INTO "failures" VALUES(10,'2026-03-15T15:03:59.864228','llm_client','All 3 attempts failed','quality_check');
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
INSERT INTO "processed_videos" VALUES('AoN1K4c7VKE','MrBeast','Survive 30 Days Stranded With Your Ex, Win $250,000','no_clips',0,'2026-03-15T15:01:06.829101');
INSERT INTO "processed_videos" VALUES('hjkbqeWQAM8','MrBeast','Every Step You Take, Win $1,000','banked',1,'2026-03-15T15:01:55.198713');
INSERT INTO "processed_videos" VALUES('3GNyw4uaAqU','MrBeast','Subscribe for an iPhone','no_clips',0,'2026-03-15T15:02:13.417729');
INSERT INTO "processed_videos" VALUES('IJkB-oapuks','MrBeast','Giving Away $1,000,000 in Gifts To My Subscribers','no_clips',0,'2026-03-15T15:02:33.451504');
INSERT INTO "processed_videos" VALUES('9BsQpGhwVAY','Mark Rober','pride comes before flop','no_clips',0,'2026-03-15T15:03:13.095347');
CREATE TABLE quota_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at       TEXT NOT NULL,
                    api_name        TEXT NOT NULL,
                    model_name      TEXT,
                    units_used      INTEGER DEFAULT 1,
                    operation       TEXT
                );
INSERT INTO "quota_log" VALUES(1,'2026-03-15T14:35:47.550833','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(2,'2026-03-15T14:35:47.655305','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(3,'2026-03-15T14:35:47.858327','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(4,'2026-03-15T14:35:48.066890','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(5,'2026-03-15T15:00:12.036764','ai_gemini','gemini-2.5-flash',1,'generate');
INSERT INTO "quota_log" VALUES(6,'2026-03-15T15:00:23.461632','ai_gemini','gemini-2.5-flash',1,'generate');
INSERT INTO "quota_log" VALUES(7,'2026-03-15T15:00:31.964941','ai_gemini','gemini-2.5-flash',1,'generate');
INSERT INTO "quota_log" VALUES(8,'2026-03-15T15:00:45.237887','ai_gemini','gemini-2.5-flash',1,'generate');
INSERT INTO "quota_log" VALUES(9,'2026-03-15T15:00:54.293955','ai_gemini','gemini-2.5-flash',1,'generate');
INSERT INTO "quota_log" VALUES(10,'2026-03-15T15:01:06.824454','ai_gemini','gemini-2.5-flash',1,'generate');
INSERT INTO "quota_log" VALUES(11,'2026-03-15T15:01:55.193363','ai_gemini','gemini-2.5-flash',1,'generate');
INSERT INTO "quota_log" VALUES(12,'2026-03-15T15:01:56.092187','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(13,'2026-03-15T15:01:56.283639','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(14,'2026-03-15T15:01:56.458809','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(15,'2026-03-15T15:02:13.413246','ai_gemini','gemini-2.5-flash',1,'generate');
INSERT INTO "quota_log" VALUES(16,'2026-03-15T15:02:33.536648','youtube',NULL,1,'channels_list');
INSERT INTO "quota_log" VALUES(17,'2026-03-15T15:02:33.744200','youtube',NULL,1,'playlist_items_list');
INSERT INTO "quota_log" VALUES(18,'2026-03-15T15:02:33.910037','youtube',NULL,1,'videos_list');
INSERT INTO "quota_log" VALUES(19,'2026-03-15T15:04:02.392913','youtube',NULL,1600,'videos_insert');
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
INSERT INTO "uploaded_shorts" VALUES(1,'0K2r3J1YW60','hjkbqeWQAM8','MrBeast','MrBeast 🏆 Best Challenge Moment #shorts','2026-03-15T19:00:00+00:00','2026-03-15T15:04:02.394542','scheduled');
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('quota_log',19);
INSERT INTO "sqlite_sequence" VALUES('ai_reliability',16);
INSERT INTO "sqlite_sequence" VALUES('failures',10);
INSERT INTO "sqlite_sequence" VALUES('clip_bank',1);
INSERT INTO "sqlite_sequence" VALUES('uploaded_shorts',1);
COMMIT;