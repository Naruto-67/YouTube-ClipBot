# 🤖 ClipBot

A fully automated YouTube Shorts pipeline that finds viral moments from creator videos, cuts intelligent clips, adds styled captions and a voiceover hook, and uploads them on a dynamic schedule — all on free-tier infrastructure.

---

## How It Works

```
Every day at 14:00 UTC (GitHub Actions triggers)
  │
  ├── Fetch top viral videos from each source creator (YouTube Data API)
  ├── Download video at 720p (yt-dlp, auto-updates itself)
  ├── Transcribe audio with word-level timestamps (Whisper medium.en)
  ├── AI selects the 2 best logical clip moments (Gemini → Groq fallback)
  │
  └── For each clip:
        ├── Generate 3-second voiceover hook (edge-tts)
        ├── Smart face-detected 9:16 crop (OpenCV)
        ├── Render with word-by-word captions + vignette (FFmpeg)
        ├── Technical QC (ffprobe — resolution, duration, audio)
        ├── Generate SEO title/description/tags (AI)
        ├── Metadata QC + auto-fix (AI + rules)
        ├── Dynamic scheduling (YouTube Analytics API)
        └── Upload as private scheduled Short (YouTube Data API)

  └── Daily report → Discord webhook
```

Every Sunday: token health check, post-upload monitor, storage cleanup.

---

## Free-Tier Stack

| Component | Tool | Cost |
|---|---|---|
| CI/CD runner | GitHub Actions (public repo) | Free — unlimited minutes |
| Video download | yt-dlp | Free |
| Transcription | faster-whisper (CPU, int8) | Free |
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

### Step 1 — Fork or create this repo as Public

GitHub Actions unlimited minutes only apply to **public** repos.

### Step 2 — Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a **new project** (e.g. `clipbot-prod`)
3. Enable **YouTube Data API v3**
4. Enable **YouTube Analytics API**
5. Go to **Credentials** → Create **OAuth 2.0 Client ID** (Desktop app type)
6. Download the client ID JSON — you will need the `client_id` and `client_secret`

> ⚠️ Use a **new project** separate from any other YouTube automation you run. Each project gets its own 10,000 units/day quota.

### Step 3 — Get your API keys

**Gemini:**
- Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
- Create API key → copy it

**Groq:**
- Go to [console.groq.com/keys](https://console.groq.com/keys)
- Create API key → copy it

### Step 4 — Authenticate YouTube

Run the setup script **locally** (one time only):

```bash
pip install google-auth-oauthlib google-api-python-client
python scripts/setup_auth.py
```

It will open a browser, ask you to log into your YouTube channel, and print a JSON block. Copy this entire JSON — you will need it in Step 5.

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

Edit `config/channels.yaml`:

```yaml
source_creators:
  - name: "MrBeast"
    channel_id: "UCX6OQ3DkcsbYNE6H8uQQuVA"
    active: true
    max_videos_per_run: 2

  - name: "Speed"
    channel_id: "UC508aO-J8KJTQ5eCcyMRF6g"
    active: true
    max_videos_per_run: 1
```

To find any channel's ID: go to the channel page → view page source → search `channelId`.

### Step 7 — Download the caption font

```bash
python scripts/download_font.py
```

Then commit the font:
```bash
git add assets/fonts/Anton-Regular.ttf
git commit -m "feat: add caption font"
git push
```

Or skip this — the pipeline will auto-download it during each GitHub Actions run. The font only needs to be committed if you want it cached (faster startup).

### Step 8 — Enable the kill switch variable

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **Variables** tab → **New repository variable**

| Variable Name | Value |
|---|---|
| `CLIPBOT_ENABLED` | `true` |

### Step 9 — Run it

Go to **Actions** tab → **01 Daily Pipeline** → **Run workflow**.

Watch the logs. Check Discord for the daily report.

---

## Configuration Reference

All behaviour is controlled by YAML files — no code changes needed.

### `config/channels.yaml`
- `upload_channel` — your YouTube channel credentials and Discord webhook secret names
- `source_creators` — list of channels to clip from. Set `active: false` to pause one.

### `config/pipeline.yaml`
Key settings:

| Setting | Default | Description |
|---|---|---|
| `max_clips_per_day` | 3 | Total shorts uploaded per day |
| `max_video_length_minutes` | 30 | Skip source videos longer than this |
| `min_clip_seconds` | 30 | Minimum clip length |
| `max_clip_seconds` | 60 | Maximum clip length |
| `ai_confidence_threshold` | 0.60 | Preferred minimum AI clip confidence |
| `analytics_subscriber_threshold` | 1000 | Subs needed to switch from default to Analytics scheduling |
| `add_voiceover_hook` | true | Enable/disable AI voiceover hook |
| `apply_vignette` | true | Enable/disable vignette filter |
| `original_audio_db` | -20 | Source audio reduction (Content ID mitigation) |

### `config/providers.yaml`
- AI model list, tiers, and rate limits
- YouTube quota unit costs
- Update numbers here if Google/Groq changes their free tier — no code changes needed

### `config/prompts.yaml`
- All AI prompts in one place
- Tweak clip selection criteria, SEO style, quality check rules without touching code

---

## GitHub Actions Workflows

| Workflow | Schedule | Description |
|---|---|---|
| `01_daily_pipeline` | 14:00 UTC daily | Main pipeline — fetch, clip, render, upload |
| `02_weekly_maintenance` | Sunday 10:00 UTC | Token health, post-upload monitor, DB cleanup |
| `03_cache_nuke` | Manual only | Purge all GitHub Actions caches if storage bloats |
| `04_system_control` | Manual only | Enable/disable pipeline with Discord notification |
| `05_run_tests` | On push/PR | Run test suite |

---

## Kill Switch

To stop the pipeline without deleting anything:

1. Go to **Actions** → **04 System Control** → **Run workflow**
2. Select `disable` → Run
3. To resume: same workflow → select `enable`

Or go to **Settings → Variables** and set `CLIPBOT_ENABLED` to `false` / `true` manually.

---

## Adding a New Source Creator

Edit `config/channels.yaml` and add a block:

```yaml
  - name: "KSI"
    channel_id: "UCVtFOytbRpEvzLjvqGG5gxQ"
    active: true
    max_videos_per_run: 1
```

Commit and push — takes effect on the next run. No code changes needed.

---

## AI Model Fallback Chain

```
1. gemini-2.5-flash        → 10 RPM, 250 RPD   (primary)
2. gemini-2.5-flash-lite   → 15 RPM, 1,000 RPD
3. llama-3.3-70b-versatile → Groq, 14,400 RPD
4. llama-3.1-8b-instant    → Groq, 14,400 RPD  (high volume fallback)
5. gemini-2.5-pro          → 5 RPM, 100 RPD    (last resort only)
```

The system tracks RPM (rolling 60-second window) and RPD separately for each model, with separate reset timers:
- Gemini: resets at **Pacific Time midnight**
- Groq: resets at **UTC midnight**

---

## Hallucination Defense

The AI is used for clip selection, SEO generation, and metadata QC. Every AI output is:

1. **Forced to return strict JSON** — if it fails to parse, it retries on the next model
2. **Validated against hard rules** — timestamps bounded by video duration, duration within allowed range, no out-of-range confidence values
3. **Caption-guarded** — Whisper is the sole source of caption text; the AI cannot add or change words
4. **Confidence-gated** — clips below 0.30 confidence are never used regardless
5. **Fallback-protected** — if all AI attempts fail for any step, safe defaults are used; the pipeline never crashes due to AI failure

---

## Quota Safety

The system never blindly fires API calls. Before every operation:

- YouTube: checks remaining daily units (10,000/day, resets PT midnight)
- Gemini: checks RPM (sliding 60s window) and RPD
- Groq: checks RPM and RPD

On 429 responses: exponential backoff → escalate to next model in chain.

The daily Discord report always includes quota usage so you can see headroom.

---

## Storage

- Database: SQLite exported as `memory/clipbot.sql` (plain text, small git diffs)
- Quota state: `memory/quota_state.json`
- Temp files: downloaded videos and rendered shorts are deleted **immediately** after use
- Weekly cleanup prunes old DB records and vacuums the database

---

## Re-Authentication (Rare)

OAuth tokens stay valid indefinitely when used daily. You only need to re-authenticate if:
- You changed your Google account password
- You manually revoked access in Google account settings
- Google detected unusual access (very rare)

When this happens, the weekly token health check will alert you on Discord.
To re-authenticate: run `python scripts/setup_auth.py` locally and update the `YOUTUBE_CREDENTIALS` secret.

---

## Troubleshooting

**Pipeline runs but no uploads:**
- Check YouTube quota in Discord report — may have hit daily limit
- Check if `CLIPBOT_ENABLED` is `true` in repo variables

**yt-dlp download fails:**
- The pipeline auto-updates yt-dlp and retries once
- If it keeps failing, YouTube may have changed something — wait 24h and retry

**AI returns no clips:**
- Check Gemini and Groq API keys in token health report
- Check if both providers' daily quotas are exhausted (see Discord report)

**Captions look wrong:**
- Check `config/pipeline.yaml` caption settings
- Ensure the font file is in `assets/fonts/Anton-Regular.ttf`

**OAuth token expired:**
- Run `python scripts/setup_auth.py` locally
- Update `YOUTUBE_CREDENTIALS` secret with new JSON

---

## Project Structure

```
clipbot/
├── main.py                    ← Entry point
├── requirements.txt           ← Pinned dependencies
│
├── config/
│   ├── channels.yaml          ← Source creators + upload channel
│   ├── providers.yaml         ← AI models + API limits (update if limits change)
│   ├── pipeline.yaml          ← All tunable pipeline settings
│   └── prompts.yaml           ← All AI prompts
│
├── engine/
│   ├── config_manager.py      ← Loads all YAML configs
│   ├── database.py            ← SQLite + SQL dump persistence
│   ├── quota_manager.py       ← Tracks all API quotas with correct reset timers
│   ├── llm_client.py          ← Unified AI client + fallback chain
│   └── discord_notifier.py    ← Discord webhook notifications
│
├── pipeline/
│   ├── orchestrator.py        ← Master controller — runs the full pipeline
│   ├── fetcher.py             ← yt-dlp video discovery + download
│   ├── transcriber.py         ← faster-whisper transcription
│   ├── clip_selector.py       ← AI clip selection + validation
│   ├── renderer.py            ← FFmpeg rendering (crop, captions, vignette)
│   ├── voiceover.py           ← edge-tts hook generation
│   ├── seo_generator.py       ← AI SEO metadata generation
│   ├── quality_checker.py     ← Technical + metadata QC
│   ├── scheduler.py           ← Dynamic publish time selection
│   └── uploader.py            ← YouTube Data API upload
│
├── scripts/
│   ├── setup_auth.py          ← One-time OAuth setup (run locally)
│   ├── download_font.py       ← Downloads Anton font
│   ├── maintenance.py         ← Weekly DB cleanup
│   ├── token_health.py        ← Weekly API key validation
│   └── post_monitor.py        ← Weekly uploaded shorts status check
│
├── tests/
│   ├── test_clip_selector.py  ← Clip validation unit tests
│   └── test_quota_manager.py  ← Quota tracking unit tests
│
├── assets/fonts/              ← Anton-Regular.ttf (caption font)
├── memory/                    ← clipbot.sql + quota_state.json (auto-generated)
├── temp/                      ← Working directory (auto-cleaned after each run)
│
└── .github/workflows/
    ├── 01_daily_pipeline.yml  ← Main daily run
    ├── 02_weekly_maintenance.yml
    ├── 03_cache_nuke.yml      ← Manual cache purge
    ├── 04_system_control.yml  ← Kill switch
    └── 05_run_tests.yml       ← Test suite on push
```
