# 🤖 ClipBot

A fully automated YouTube Shorts pipeline that finds viral moments from creator videos, cuts intelligent clips, adds styled captions and a voiceover hook, and uploads them on a dynamic schedule — all on free-tier infrastructure.

---

## New Features (V2)

### 🧪 TEST_MODE (Dry Run — no quota, no upload)
Set `TEST_MODE=true` to run the full pipeline without consuming any YouTube quota or uploading anything:
- Uses a **separate test database** (`memory/clipbot_test.db` / `clipbot_test.sql`)
- **No YouTube API calls** — discovery, subscriber count, and uploads are all simulated
- **Real AI calls** (Gemini/Groq) still happen so you can validate clip selection quality
- **Real rendering** happens so you can inspect the output videos
- Trigger via GitHub Actions: **Actions → 06 Test Mode (Dry Run)** → optionally paste a video URL
- Rendered test shorts are uploaded as **GitHub Actions artifacts** for download

### 🔒 Dedup — never re-create the same shorts
- `processed_videos` is now **never pruned** — it's a permanent dedup fingerprint
- Videos with **any** banked clips (pending/uploaded/failed) are skipped during discovery
- Clip selection **excludes time ranges already in the bank** for that video
- Exact duplicate clip ranges are rejected before saving to the bank

### 🧠 Narrative Coherence — clips that make sense
- Clips are **snapped to sentence boundaries** — they start at the beginning of a new thought and end at a natural pause/punchline
- AI prompt now requires **complete, self-contained narrative beats** (setup → tension → payoff)
- `hook_text` must be a **verbatim quote** from the actual transcript — no invented hooks

### 🔬 Auto Model Discovery
- Queries Gemini's model list at startup and **automatically adds newer free models** (e.g. `gemini-3.0-flash`) at top priority
- Version-scored: `3.0 > 2.5 > 2.0 > 1.5` — newer models always preferred
- Falls back to static config if discovery fails
- Toggle via `auto_discovery.enabled` in `config/providers.yaml`
- **New:** also auto-discovers **Groq** text models (`discover_groq: true`) so new Llama/Gemma/Mixtral releases are picked up without code changes

### 🎙️ Groq Cloud Transcription (fast fallback)
- When YouTube captions are unavailable, ClipBot now tries **Groq's hosted `whisper-large-v3`** first (audio-only download, no local model, seconds not minutes)
- Falls back to local faster-whisper (CPU) only if Groq fails or no `GROQ_API_KEY`
- Config: `groq_whisper_model` in `config/pipeline.yaml`

### 🔊 Piper TTS voiceover fallback
- edge-tts (primary) now falls back to **Piper TTS** (local CPU, offline) when the Bing WebSocket is blocked on Azure IPs
- `hook_tts_provider: auto | edge | piper` in `config/pipeline.yaml`
- Optional dep: `piper-tts>=1.2.0` + `piper` CLI + a voice model

### ⚡ Parallel chunk analysis
- Long videos' transcript chunks are now analysed **concurrently** (bounded small thread pool) instead of serially — much faster multi-chunk clip selection
- RPM throttling inside the LLM client still respects per-minute provider limits

### 🔁 Failed-video circuit breaker
- A source video that fails N times consecutively (`circuit_breaker_failures`, default 3) is **skipped permanently** instead of retried every run

### 🎚️ Clip-bank diversity + content spacing
- Uploads now alternate **source videos** so clips from the same video are never pushed back-to-back (content diversity)
- Every iteration asks the bank for a clip from a *different* source, falling back only if the bank is single-source

### 💽 DB indexes + failed-clip prune
- Added indexes for the hot queries (`clip_bank.status`, `source_video_id`, `quota_log`, etc.)
- Failed bank clips are pruned after a shorter window so they don't accumulate

### 🛑 FATAL auth handling
- An invalid/expired YouTube OAuth token now **raises a fatal error** and halts the run (instead of burning quota retrying 401s), with a Discord alert

### 🎵 Background music + Content-ID mitigation
- Optional royalty-free music under `assets/music/` (`add_background_music`, `music_volume`)
- Optional **pitch-shift** of the source audio (`content_id_pitch_shift` semitones) so clips fingerprint differently and are less likely to trigger Content ID

### 🏷️ Per-channel category
- `category_id` in `config/channels.yaml` → applied to every upload (default `22` People & Blogs)

### 📊 Weekly monitoring (API monitor + performance analyst)
- `scripts/api_monitor.py`: weekly audit of Gemini/Groq/YouTube for deprecations, new free models, quota changes → posts to Discord
- `scripts/performance_analyst.py`: optional Analytics feedback loop (`performance_feedback`) that learns which clip_types perform best

### 🧹 Structured logging
- `engine/logger.py`: timestamped, tagged, level-coded console logs across the pipeline (matches Ghost Engine's logger)

### 🔁 Dependabot auto-update
- `.github/dependabot.yml` + `00_auto_merge_deps.yml`: weekly dependency scan, auto-merge of safe patch/minor bumps, manual review for major bumps and fragile native-binary packages (faster-whisper, opencv)

---

## How It Works

```
Every day at 14:00 UTC (GitHub Actions triggers)
  │
  ├── Sync manual_queue.yaml → process any manually queued videos first
  │
  ├── Check clip bank:
  │     ├── Bank has enough clips → skip discovery, upload directly
  │     └── Bank is low → run discovery to refill
  │
  ├── Discovery (if needed):
  │     ├── Fetch viral videos from each source creator (YouTube Data API)
  │     ├── If still low → extend to 90-day backlog window
  │     ├── Download video at 720p (yt-dlp, auto-updates itself)
  │     ├── Transcribe audio with word-level timestamps (Whisper medium.en)
  │     │     └── Long videos (>15 min) → chunked transcription with overlap
  │     ├── AI selects ALL logical clips (2–10 based on video length)
  │     └── Save ALL clips to clip bank
  │
  ├── Upload up to 3 clips from bank today
  │     ├── Re-download source video if needed
  │     ├── Generate 3-second voiceover hook (edge-tts)
  │     ├── Smart face-detected 9:16 crop (OpenCV)
  │     ├── Render with word-by-word captions + vignette (FFmpeg)
  │     ├── Technical QC (ffprobe — resolution, duration, audio)
  │     ├── Generate SEO title/description/tags (AI)
  │     ├── Metadata QC + auto-fix (AI + rules)
  │     ├── Dynamic scheduling (YouTube Analytics API)
  │     └── Upload as private scheduled Short (YouTube Data API)
  │
  └── Daily report → Discord webhook

Every Sunday: token health check, post-upload monitor, storage cleanup.
```

**Key behaviour:** One good 40-minute MrBeast video yields ~10 clips. Those 10 clips get banked and drip-fed at 3/day — keeping the channel fed for 3 days without any new discovery needed.

---

## Source Creators (pre-configured)

| Creator | Permission | Content Type |
|---|---|---|
| MrBeast | Vyro partner — authorized | Challenges, reactions, funny moments |
| Mark Rober | Vyro partner — authorized | Science reveals, satisfying outcomes |

Add more creators any time by editing `config/channels.yaml` — no code changes needed.

---

## Free-Tier Stack

| Component | Tool | Cost |
|---|---|---|
| CI/CD runner | GitHub Actions (public repo) | Free — unlimited minutes |
| Video download | yt-dlp | Free |
| Transcription | faster-whisper medium.en (CPU, int8) | Free |
| AI (primary) | Gemini 2.5 Flash | Free — 10 RPM, 250 RPD |
| AI (fallback 1) | Gemini 2.5 Flash-Lite | Free — 15 RPM, 1,000 RPD |
| AI (fallback 2) | Groq LLaMA 3.3 70B | Free — 14,400 RPD |
| AI (last resort) | Groq LLaMA 3.1 8B | Free |
| Video rendering | FFmpeg | Free |
| Voiceover | edge-tts | Free |
| Database | SQLite (committed as SQL dump) | Free |
| Storage | GitHub repo | Free |

---

## One-Time Setup (15 minutes)

### Step 1 — Create this repo as Public

GitHub Actions unlimited minutes only apply to **public** repos.

### Step 2 — Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a **new project** (e.g. `clipbot-prod`)
3. Enable **YouTube Data API v3**
4. Enable **YouTube Analytics API**
5. Go to **Credentials** → Create **OAuth 2.0 Client ID** (Desktop app type)
6. Note the `client_id` and `client_secret`

> ⚠️ Use a **new project** separate from any other YouTube automation. Each project gets its own 10,000 units/day quota.

### Step 3 — Get your API keys

**Gemini:** [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) → Create API key

**Groq:** [console.groq.com/keys](https://console.groq.com/keys) → Create API key

### Step 4 — Authenticate YouTube

Run the setup script **locally** (one time only):

```bash
pip install google-auth-oauthlib google-api-python-client
python scripts/setup_auth.py
```

It opens a browser, asks you to log into your upload channel, and prints a JSON block. Copy the entire JSON.

### Step 5 — Add GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret Name | Value |
|---|---|
| `YOUTUBE_CREDENTIALS` | The JSON printed by `setup_auth.py` |
| `GEMINI_API_KEY` | Your Gemini API key |
| `GROQ_API_KEY` | Your Groq API key |
| `DISCORD_WEBHOOK` | Your Discord channel webhook URL |

**How to create a Discord webhook:**
1. Open your Discord server → channel settings → Integrations → Webhooks → New Webhook
2. Copy the webhook URL → paste it as the `DISCORD_WEBHOOK` secret

### Step 6 — Configure source creators

`config/channels.yaml` is pre-configured with MrBeast, Speed, and Mark Rober. Edit as needed:

```yaml
source_creators:
  - name: "MrBeast"
    channel_id: "UCX6OQ3DkcsbYNE6H8uQQuVA"
    active: true
    max_videos_per_run: 2
```

To find any channel's ID: go to the channel page → view page source → search `channelId`.

### Step 7 — Download the caption font

```bash
python scripts/download_font.py
git add assets/fonts/Anton-Regular.ttf
git commit -m "feat: add caption font"
git push
```

Or skip — the pipeline auto-downloads it on every run (slower startup without cache).

### Step 8 — Enable the kill switch variable

Go to **Settings** → **Secrets and variables** → **Actions** → **Variables** → **New repository variable**

| Variable Name | Value |
|---|---|
| `CLIPBOT_ENABLED` | `true` |

### Step 9 — Run it

Go to **Actions** tab → **01 Daily Pipeline** → **Run workflow**.

Check Discord for the daily report.

---

## Configuration Reference

All behaviour is controlled by YAML files — no code changes ever needed.

### `config/channels.yaml`
- `upload_channel` — your channel's credentials and Discord webhook env key names
- `source_creators` — list of channels to clip from. Set `active: false` to pause one.

### `config/pipeline.yaml`

Key settings:

| Setting | Default | Description |
|---|---|---|
| `max_clips_per_day` | 3 | Max shorts uploaded per day from the bank |
| `max_video_length_minutes` | 90 | Max source video length (chunked transcription handles up to this) |
| `backlog_max_age_days` | 90 | Extended discovery window when bank is low |
| `clip_bank_low_threshold` | 3 | Trigger new discovery when bank drops below this |
| `clips_per_video_tiers` | see below | Dynamic clip count based on video duration |
| `chunk_duration_minutes` | 15 | Size of each transcript chunk for long videos |
| `chunk_overlap_minutes` | 2 | Overlap between chunks to avoid missing boundary moments |
| `min_clip_seconds` | 30 | Minimum short length |
| `max_clip_seconds` | 60 | Maximum short length |
| `ai_confidence_threshold` | 0.60 | Preferred minimum AI clip confidence |
| `analytics_subscriber_threshold` | 1000 | Subs needed to use Analytics API for scheduling |
| `add_voiceover_hook` | true | Enable/disable AI voiceover hook |
| `apply_vignette` | true | Enable/disable vignette filter |
| `original_audio_db` | -20 | Source audio reduction (Content ID mitigation) |

**Dynamic clip count tiers:**

| Video Length | Clips Extracted |
|---|---|
| 0–10 min | 2 |
| 10–20 min | 4 |
| 20–35 min | 6 |
| 35+ min | 10 |

### `config/manual_queue.yaml`

Add any specific YouTube URL here to have it processed on the next run. Use this for Vyro campaign drops or any video you want to target immediately:

```yaml
videos:
  - url: "https://www.youtube.com/watch?v=XXXXXXXXXXX"
    creator_name: "MrBeast"
    source: "Vyro"
    note: "Vyro campaign — Beast Games finale"
    max_clips: 8        # 0 = use dynamic count
    status: "pending"   # set to pending to process
```

After processing, `status` is automatically updated to `done` in the database — it will never run twice.

### `config/providers.yaml`
- AI model list, tiers, and all rate limits
- YouTube quota unit costs
- Update numbers here if Google/Groq changes their free tier

### `config/prompts.yaml`
- All AI prompts in one file
- Tweak clip selection criteria, SEO style, or quality check rules without touching code

---

## Clip Bank

The system separates **discovery** from **uploading**:

- When a video is processed, **all clips** are extracted and saved to the clip bank
- Each day, the pipeline uploads up to `max_clips_per_day` from the bank
- One 40-minute video yields ~10 clips = ~3 days of content without new discovery
- When the bank runs low, discovery runs automatically
- If the bank is completely empty and no new videos are found, a Discord alert fires

This means a single good video keeps the channel going for days, and the channel never silently goes dark.

---

## GitHub Actions Workflows

| Workflow | Schedule | Description |
|---|---|---|
| `01_daily_pipeline` | 14:00 UTC daily | Main pipeline — discovery, bank, upload |
| `02_weekly_maintenance` | Sunday 10:00 UTC | Token health, post-upload monitor, DB cleanup, API monitor, performance analyst |
| `03_cache_nuke` | Manual only | Purge all GitHub Actions caches |
| `04_system_control` | Manual only | Enable/disable pipeline with Discord notification |
| `05_run_tests` | On push/PR | Run test suite |
| `06_test_mode` | Manual only | Dry-run pipeline — no quota, no upload, artifact output |
| `00_auto_merge_deps` | On Dependabot PR | Auto-merge safe dependency bumps + flag fragile/major |

---

## Kill Switch

To stop the pipeline without losing anything:

1. Go to **Actions** → **04 System Control** → **Run workflow**
2. Select `disable` → Run
3. To resume: same workflow → select `enable`

All banked clips are preserved. The system resumes exactly where it left off.

---

## Adding a New Source Creator

Edit `config/channels.yaml`:

```yaml
  - name: "KSI"
    channel_id: "UCVtFOytbRpEvzLjvqGG5gxQ"
    active: true
    max_videos_per_run: 1
```

Commit and push — takes effect on the next run.

---

## Vyro Integration

Vyro is a platform where MrBeast, Mark Rober, and other creators pay clippers per view. When a Vyro campaign drops:

1. Copy the campaign video URL
2. Add it to `config/manual_queue.yaml` with `source: "Vyro"`
3. Push — the next run processes it at top priority
4. After upload, copy the YouTube Short URL into the Vyro dashboard (one manual step — unavoidable, Vyro has no API)

---

## AI Model Fallback Chain

```
1. gemini-2.5-flash        → 10 RPM, 250 RPD   (primary)
2. gemini-2.5-flash-lite   → 15 RPM, 1,000 RPD
3. llama-3.3-70b-versatile → Groq, 14,400 RPD
4. llama-3.1-8b-instant    → Groq, 14,400 RPD  (high volume)
5. gemini-2.5-pro          → 5 RPM, 100 RPD    (absolute last resort)
```

Reset timers: Gemini = Pacific Time midnight | Groq = UTC midnight

---

## Hallucination Defense

Every AI output is protected by multiple layers:

1. **Strict JSON schema** — free text responses are rejected and retried
2. **Hard validation** — timestamps bounded by video duration, duration within range
3. **Whisper as caption truth** — AI cannot add or change words in captions
4. **Confidence gating** — clips below 0.30 confidence are never used
5. **Fallback defaults** — if all AI fails, safe defaults are used; pipeline never crashes
6. **Chunked AI analysis** — long videos are analyzed in overlapping 15-min chunks to stay within context limits

---

## Quota Safety

Before every API call the system checks available budget:

- YouTube: 10,000 units/day, resets PT midnight
- Gemini: RPM (rolling 60s window) + RPD, resets PT midnight
- Groq: RPM + RPD, resets UTC midnight

On 429: exponential backoff → escalate to next model in fallback chain.
Daily Discord report always shows quota usage per provider.

---

## Storage

- Database: SQLite exported as `memory/clipbot.sql` (plain text, git-friendly diffs)
- Quota state: `memory/quota_state.json`
- Temp files: source videos and rendered shorts deleted immediately after use
- Weekly cleanup: prunes old records, vacuums DB, reports size to Discord

---

## Troubleshooting

**No uploads today:**
- Check Discord daily report — bank may be empty, quota may be exhausted
- Check `CLIPBOT_ENABLED` is `true` in repo variables

**Bank empty — no new videos found:**
- Add more source creators in `config/channels.yaml`
- Or add a specific video to `config/manual_queue.yaml`
- The system already tried the 90-day backlog automatically

**yt-dlp download fails:**
- Pipeline auto-updates yt-dlp and retries once
- If it keeps failing, YouTube may have changed — wait 24h

**AI returns no clips:**
- Check Gemini/Groq API keys via token health check (Actions → 02 Weekly Maintenance)
- Check if all model quotas are exhausted in Discord report

**Captions look wrong:**
- Check caption settings in `config/pipeline.yaml`
- Ensure font is at `assets/fonts/Anton-Regular.ttf`

**OAuth token broken:**
- Run `python scripts/setup_auth.py` locally
- Update `YOUTUBE_CREDENTIALS` secret

---

## Project Structure

```
clipbot/
├── main.py                       ← Entry point + kill switch
├── requirements.txt              ← Pinned dependencies
│
├── config/
│   ├── channels.yaml             ← Upload channel + source creators
│   ├── manual_queue.yaml         ← Specific videos to process (Vyro campaigns etc.)
│   ├── providers.yaml            ← AI models + API limits
│   ├── pipeline.yaml             ← All tunable settings
│   └── prompts.yaml              ← All AI prompts
│
├── engine/
│   ├── config_manager.py         ← Loads all YAML configs
│   ├── database.py               ← SQLite: clip_bank, manual_queue, quotas, etc.
│   ├── quota_manager.py          ← Per-provider quota tracking + fallback
│   ├── llm_client.py             ← Unified AI client + fallback chain
│   ├── model_discovery.py        ← Auto model discovery (Gemini + Groq)
│   ├── logger.py                 ← Structured, tagged console logging
│   └── discord_notifier.py       ← Discord webhook notifications
│
├── pipeline/
│   ├── orchestrator.py           ← Master controller: queue → bank → discover → upload
│   ├── fetcher.py                ← yt-dlp discovery + download + manual queue resolver
│   ├── transcriber.py            ← YouTube captions → Groq Whisper → faster-whisper
│   ├── clip_selector.py          ← AI clip selection: parallel chunked analysis + dedup
│   ├── renderer.py               ← FFmpeg: smart crop, glow captions, music, pitch-shift
│   ├── voiceover.py              ← Hook TTS: edge-tts → Piper fallback
│   ├── seo_generator.py          ← AI SEO metadata
│   ├── quality_checker.py        ← ffprobe + AI metadata QC
│   ├── scheduler.py              ← Dynamic publish time (Analytics or bootstrap)
│   └── uploader.py               ← YouTube Data API upload
│
├── scripts/
│   ├── setup_auth.py             ← One-time OAuth setup (run locally)
│   ├── download_font.py          ← Downloads Anton caption font
│   ├── maintenance.py            ← Weekly DB prune + vacuum
│   ├── token_health.py           ← Weekly API key validation
│   ├── post_monitor.py           ← Weekly uploaded shorts status check
│   ├── api_monitor.py            ← Weekly provider deprecation/new-model audit
│   └── performance_analyst.py    ← Optional Analytics feedback loop
│
├── tests/
│   ├── test_clip_selector.py     ← Clip validation tests
│   ├── test_quota_manager.py     ← Quota tracking tests
│   └── test_dedup_and_coherence.py ← Dedup + sentence snapping + model scoring
│
├── assets/fonts/                 ← Anton-Regular.ttf (caption font)
├── assets/music/                 ← Optional royalty-free short background music
├── memory/                       ← clipbot.sql + quota_state.json (auto-generated)
├── temp/                         ← Working directory (auto-cleaned after each run)
│
└── .github/
    ├── dependabot.yml            ← Weekly dependency scan config
    └── workflows/
        ├── 00_auto_merge_deps.yml ← Auto-merge safe Dependabot PRs
        ├── 01_daily_pipeline.yml  ← Main daily run
        ├── 02_weekly_maintenance.yml ← Weekly health + cleanup + audits
        ├── 03_cache_nuke.yml      ← Manual cache purge
        ├── 04_system_control.yml  ← Kill switch
        ├── 05_run_tests.yml       ← Tests on push/PR
        └── 06_test_mode.yml       ← Dry-run pipeline (no quota, no upload)
```
