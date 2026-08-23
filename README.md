# 🤖 ClipBot

A fully automated YouTube Shorts pipeline that finds viral moments from creator videos, cuts intelligent clips, adds styled captions and a voiceover hook, and uploads them on a dynamic schedule — all on 100% free-tier infrastructure.

Built with a **self-improving architecture** — nothing is hardcoded. Models, upload timing, SEO, creator priority, and content safety rules all adapt automatically as the internet changes.

---

## Architecture Overview

```
Every day at 14:00 UTC (GitHub Actions)
  │
  ├── Step 0: Video Guardian
  │     └── Batch-check all uploaded Shorts for removals/rejections
  │           (1 unit per 50 videos — essentially free)
  │           └── Auto-make policy-violating videos private
  │
  ├── Step 1: Trend Research
  │     └── Fetch today's trending topics from YouTube (~3 units)
  │           └── Cached for full session, injected into all SEO prompts
  │
  ├── Step 2: Manual queue → process any queued videos first
  │
  ├── Step 3: Clip Bank check
  │     ├── Bank has enough clips → skip discovery
  │     └── Bank is low → run discovery
  │
  ├── Step 4: Discovery (if needed)
  │     ├── Channel Scorer: score creators by niche + Content ID risk + bank history
  │     │     → dynamically allocate video budget per creator
  │     ├── Fetch viral videos from top-scored creators (YouTube Data API)
  │     ├── If still low → extend to backlog window
  │     ├── Transcribe: YouTube captions → Groq Whisper → local faster-whisper
  │     ├── AI selects ALL logical clips (parallel chunked analysis)
  │     └── Save all clips to clip bank
  │
  ├── Step 5: Upload up to 6 clips from bank
  │     ├── Pre-upload safety guard:
  │     │     ├── Weekly cap check (max 30/week)
  │     │     ├── Min 3-hour gap between uploads
  │     │     └── Title similarity check (blocks near-duplicates within 7 days)
  │     ├── Download clip segment only (not full video)
  │     ├── Generate voiceover hook (Piper TTS → edge-tts fallback)
  │     ├── Smart 9:16 crop (OpenCV face detection)
  │     ├── Render: word-by-word captions + vignette + background music (FFmpeg)
  │     │     └── Pitch-shift audio 2 semitones (Content ID bypass)
  │     ├── Video QC (ffprobe)
  │     ├── Generate SEO with live trending tags (AI)
  │     ├── Dynamic category routing by clip_type
  │     ├── Metadata QC + auto-fix (AI + rules from safety.yaml)
  │     ├── Pick publish slot with jitter (±15 min anti-spam)
  │     └── Upload as private scheduled Short (YouTube Data API)
  │
  ├── Daily report → Discord
  │
  └── Every Monday: ClipBot Manager weekly self-improvement audit
```

---

## What Makes It Self-Improving

| System | What It Updates Automatically |
|--------|-------------------------------|
| **Model Discovery** | Queries Gemini + Groq APIs at every run — picks up newly released free models immediately |
| **Trend Research** | Fetches YouTube Trending daily — SEO titles use today's actual trending tags |
| **Channel Scorer** | Adjusts per-creator video allocation based on historical clip productivity + Content ID risk |
| **Video Guardian** | Monitors all uploaded Shorts — auto-protects against policy violations |
| **Analytics Scheduling** | Upload times learn from your channel's actual audience activity patterns |
| **ClipBot Manager** | Weekly audit: detects outdated packages, new AI models, trending channel niches |
| **Dependabot** | Weekly PRs for safe package bumps, auto-merged by `00_auto_merge_deps.yml` |

---

## Source Creators (pre-configured)

| Creator | Channel ID | Niche | Content ID Risk |
|---------|-----------|-------|-----------------|
| Lex Fridman | UCnU1Q2bngrTSXigAVZyuTHQ | Podcast/Interview | 🟢 Low |
| Theo Von | UC2hCt5eYf9J9GqNiKdTUeUw | Comedy Podcast | 🟢 Low |
| Valuetainment | UCIix1hy5XUulDpA8L8UZI1A | Business Interview | 🟢 Low |
| Ludwig | UCyzsYXkSQN_fXXlS9pI9jjQ | Gaming/Variety | 🟡 Medium |
| penguinz0 | UC4IydptVGWpDPVYGE5A8wGQ | Commentary | 🟡 Medium |
| Airrack | UCiGm_E4ZwYSHV3bcW1pnmVA | Stunts/Challenge | 🟢 Low |
| Veritasium | UCHnyfMqiRRG1u-2MsSQLbXA | Science/Tech | 🟢 Low |

Add or remove creators any time by editing `config/channels.yaml` — no code changes needed.

---

## Free-Tier Stack

| Component | Tool | Cost |
|-----------|------|------|
| CI/CD runner | GitHub Actions (public repo) | Free |
| Video download | yt-dlp | Free |
| Transcription | YouTube captions → Groq Whisper → faster-whisper | Free |
| AI (primary) | Gemini 2.5 Flash + auto-discovered newer models | Free |
| AI (fallback 1) | Gemini 2.5 Flash-Lite | Free |
| AI (fallback 2) | Groq LLaMA 3.3 70B | Free |
| AI (last resort) | Groq LLaMA 3.1 8B | Free |
| Video rendering | FFmpeg | Free |
| Voiceover | Piper TTS / edge-tts | Free |
| Database | SQLite committed as SQL dump | Free |
| Storage | GitHub repo | Free |

---

## One-Time Setup (~15 minutes)

### Step 1 — Make this repo Public

GitHub Actions unlimited minutes only apply to **public** repos.

### Step 2 — Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. `clipbot-prod`)
3. Enable **YouTube Data API v3**
4. Enable **YouTube Analytics API**
5. Credentials → Create **OAuth 2.0 Client ID** (Desktop app type)

> ⚠️ Use a **new project** separate from any other YouTube automation. Each project gets its own 10,000 units/day quota.

### Step 3 — Get your API keys

- **Gemini:** [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
- **Groq:** [console.groq.com/keys](https://console.groq.com/keys)

### Step 4 — Authenticate YouTube

Run locally (one time only):

```bash
pip install google-auth-oauthlib google-api-python-client
python scripts/setup_auth.py
```

Copy the printed JSON block.

### Step 5 — Add GitHub Secrets

**Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Value |
|-------------|-------|
| `YOUTUBE_CREDENTIALS` | JSON from setup_auth.py |
| `GEMINI_API_KEY` | Your Gemini API key |
| `GROQ_API_KEY` | Your Groq API key |
| `DISCORD_WEBHOOK` | Your Discord webhook URL |

### Step 6 — Enable the kill switch variable

**Settings → Variables → New repository variable:** `CLIPBOT_ENABLED` = `true`

### Step 7 — Run it

**Actions → 01 Daily Pipeline → Run workflow.** Check Discord for the daily report.

---

## Configuration Reference

All behaviour is controlled by YAML files — no code changes ever needed.

### `config/channels.yaml`
- `upload_channel` — your channel credentials
- `source_creators` — fields: name, channel_id, active, max_videos_per_run, niche, content_id_risk

### `config/pipeline.yaml`

| Setting | Default | Description |
|---------|---------|-------------|
| `max_clips_per_day` | 6 | Max uploads per day |
| `max_clips_per_week` | 30 | Weekly upload cap (spam protection) |
| `clip_bank_low_threshold` | 12 | Trigger discovery when bank drops below this |
| `min_hours_between_uploads` | 3 | Minimum gap between uploads |
| `upload_jitter_minutes` | 15 | Random ±minutes added to publish time |
| `max_video_age_days` | 14 | Only discover videos newer than this |
| `max_video_length_minutes` | 180 | Max source video length (handles full podcasts) |
| `content_id_pitch_shift` | 2 | Semitones to pitch-shift source audio |
| `add_background_music` | true | Mix royalty-free music from assets/music/ |
| `add_voiceover_hook` | true | Generate 3s voiceover hook |
| `hook_tts_provider` | piper | `piper` or `edge-tts` |
| `run_video_guardian` | true | Enable daily health check of uploaded Shorts |
| `run_trend_research` | true | Enable daily trending topic fetch |
| `analytics_subscriber_threshold` | 1000 | Subs needed to use Analytics for scheduling |

### `config/safety.yaml`
- `demonetizing_words` — dynamically loaded by seo_generator (not hardcoded)
- `banned_clickbait_phrases` — blocked from titles
- `clip_type_category_ids` — maps clip_type to YouTube category ID
- `fallback_tags` — used when AI returns too few tags

### `config/providers.yaml`
- AI model list, tiers, RPM/RPD limits, YouTube quota unit costs
- Auto-discovery: `max_stable_models: 6`

### `config/prompts.yaml`
- All AI prompts — SEO prompt automatically receives `{trending_tags}` from trend research

### `config/manual_queue.yaml`

```yaml
videos:
  - url: "https://www.youtube.com/watch?v=XXXXXXXXXXX"
    creator_name: "Lex Fridman"
    source: "Manual"
    max_clips: 8        # 0 = dynamic
    status: "pending"
```

---

## GitHub Actions Workflows

| Workflow | Schedule | Description |
|----------|----------|-------------|
| `01_daily_pipeline` | 14:00 UTC daily | Main pipeline — guardian → trends → bank → upload |
| `02_weekly_maintenance` | Sunday 10:00 UTC | Health + cleanup + audit |
| `03_cache_nuke` | Manual only | Purge caches |
| `04_system_control` | Manual only | Kill switch |
| `05_run_tests` | On push/PR | Test suite |
| `06_test_mode` | Manual only | Dry-run pipeline |
| **`07_clipbot_manager`** | **Monday 10:00 UTC** | **Weekly self-improvement audit** |
| `00_auto_merge_deps` | On Dependabot PR | Auto-merge safe dependency bumps |

---

## ClipBot Manager (Self-Improvement System)

`scripts/clipbot_manager.py` runs every Monday before the daily pipeline. Keeps the entire system current with the latest internet technologies automatically.

**What it checks each week:**

1. **Package currency** — compares installed versions against PyPI latest. Flags outdated packages; marks native-binary packages as manual-review required.
2. **yt-dlp auto-update** — runs `yt-dlp --update` (YouTube changes extraction frequently).
3. **Gemini model freshness** — detects newly released free-tier models not yet in `providers.yaml`.
4. **Groq model freshness** — detects new LLaMA/Gemma releases.
5. **Trending channel suggestions** — uses local trending snapshot to suggest creator niches not yet in lineup.

All findings are posted to Discord. Manual-review items appear as action items in the report.

```bash
python scripts/clipbot_manager.py --dry-run   # report only, no changes
python scripts/clipbot_manager.py              # apply updates
```

---

## Upload Protection System

| Check | Protection |
|-------|-----------|
| **Video Guardian** | Daily health-check all Shorts via API. Auto-makes policy-violating videos private. Discord alert. |
| **Weekly cap** | Blocks uploads at weekly limit. Prevents spam flags from YouTube's algorithm. |
| **Min gap** | 3-hour minimum between uploads. Prevents mechanical pattern detection. |
| **Jitter** | Random ±15 min on publish times. Natural variation that mimics human scheduling. |
| **Title similarity** | Blocks near-duplicate Shorts within 7 days. |
| **Category routing** | clip_type → YouTube category via `safety.yaml` (not hardcoded). |
| **Content ID pitch** | Shifts audio 2 semitones — defeats fingerprint matching, inaudible to humans. |

---

## AI Model Fallback Chain

```
1. [Auto-discovered newest stable Gemini model]   ← updated every run
2. gemini-2.5-flash        → 10 RPM, 250 RPD
3. gemini-2.5-flash-lite   → 15 RPM, 1,000 RPD
4. [Auto-discovered Groq models]                  ← updated every run
5. llama-3.3-70b-versatile → Groq, 14,400 RPD
6. llama-3.1-8b-instant    → Groq, 14,400 RPD
7. gemini-2.5-pro          → 5 RPM, 100 RPD    (absolute last resort)
```

New models are picked up automatically. Toggle via `auto_discovery.enabled` in `config/providers.yaml`.

---

## Hallucination Defense

1. **Strict JSON schema** — free text responses rejected and retried
2. **Hard validation** — timestamps bounded by video duration
3. **Whisper as caption truth** — AI cannot invent words
4. **Confidence gating** — clips below 0.30 confidence never used
5. **Fallback defaults** — if all AI fails, safe defaults used; pipeline never crashes
6. **Banned word filter** — dynamically loaded from `config/safety.yaml`

---

## Quota Safety

- **YouTube:** 10,000 units/day, resets PT midnight
- **Gemini:** RPM (rolling 60s) + RPD, resets PT midnight
- **Groq:** RPM + RPD, resets UTC midnight

On 429: exponential backoff → escalate to next model in fallback chain.

---

## Kill Switch

**Actions → 04 System Control → Run workflow** → select disable/enable.

All banked clips are preserved. Resumes exactly where it left off.

---

## Background Music Setup (Optional)

Drop royalty-free MP3s into `assets/music/`:
- [Pixabay Music](https://pixabay.com/music/) — free, no attribution required
- [Free Music Archive](https://freemusicarchive.org/) — CC licensed

Set `add_background_music: true` in `config/pipeline.yaml`.

---

## Troubleshooting

**No uploads:** Check Discord — bank may be empty, quota exhausted, or safety guard blocked.

**Upload blocked:** Check Discord for specific reason (weekly cap, min gap, title similarity).

**Short removed:** Video Guardian auto-protects. Review `config/safety.yaml`.

**Bank empty:** Add creators to `channels.yaml` or add a URL to `manual_queue.yaml`.

**yt-dlp fails:** ClipBot Manager auto-updates it weekly. If persistent, wait 24h.

**AI returns no clips:** Check API keys via 02 Weekly Maintenance workflow.

**OAuth broken:** Run `python scripts/setup_auth.py` locally and update the secret.

---

## Project Structure

```
clipbot/
├── main.py
├── requirements.txt
│
├── config/
│   ├── channels.yaml          ← Upload channel + source creators (niche/risk metadata)
│   ├── safety.yaml            ← Content rules: banned words, category routing, tags
│   ├── manual_queue.yaml      ← Specific videos to process
│   ├── providers.yaml         ← AI models + API limits (max_stable_models: 6)
│   ├── pipeline.yaml          ← All tunable settings (73 settings)
│   └── prompts.yaml           ← All AI prompts (trending_tags injection)
│
├── engine/
│   ├── config_manager.py
│   ├── database.py            ← SQLite: clips, uploads, trending snapshots, health
│   ├── quota_manager.py
│   ├── llm_client.py          ← Unified AI client + fallback chain
│   ├── model_discovery.py     ← Auto discovery (score > 0 filter, max 6 stable)
│   ├── logger.py
│   └── discord_notifier.py
│
├── pipeline/
│   ├── orchestrator.py        ← Master controller
│   ├── video_guardian.py      ← Health-check + auto-protect uploaded Shorts
│   ├── trend_researcher.py    ← Daily trending context + DB cache
│   ├── channel_scorer.py      ← Dynamic per-creator budget allocation
│   ├── fetcher.py
│   ├── transcriber.py
│   ├── clip_selector.py
│   ├── renderer.py
│   ├── voiceover.py
│   ├── seo_generator.py       ← AI SEO + trending tags + safety.yaml (dynamic)
│   ├── quality_checker.py
│   ├── scheduler.py           ← Publish time + jitter
│   └── uploader.py            ← Upload guard + YouTube API
│
├── scripts/
│   ├── clipbot_manager.py     ← Weekly self-improvement audit
│   ├── setup_auth.py
│   ├── download_font.py
│   ├── maintenance.py
│   ├── token_health.py
│   ├── post_monitor.py
│   ├── api_monitor.py
│   └── performance_analyst.py
│
├── tests/
│   ├── test_clip_selector.py
│   ├── test_quota_manager.py
│   └── test_dedup_and_coherence.py
│
├── assets/fonts/              ← Anton-Regular.ttf
├── assets/music/              ← Royalty-free MP3s (drop here to enable music)
├── memory/                    ← clipbot.sql + quota_state.json
├── temp/                      ← Auto-cleaned working directory
│
└── .github/
    ├── dependabot.yml
    └── workflows/
        ├── 00_auto_merge_deps.yml
        ├── 01_daily_pipeline.yml
        ├── 02_weekly_maintenance.yml
        ├── 03_cache_nuke.yml
        ├── 04_system_control.yml
        ├── 05_run_tests.yml
        ├── 06_test_mode.yml
        └── 07_clipbot_manager.yml
```
