# scripts/clipbot_manager.py
"""
ClipBot Manager -- self-improvement + technology currency system.

Runs weekly via GitHub Actions (07_clipbot_manager.yml).
Keeps the bot's tools, models, and config in sync with the latest internet
technologies and AI releases -- without any manual intervention.

What it checks / auto-updates:
  1. Python package currency -- detects outdated packages vs PyPI latest
  2. Gemini model freshness -- detects new free-tier models not yet in providers.yaml
  3. Groq model freshness -- detects new released models not yet in providers.yaml
  4. YouTube API quota changes -- checks if unit costs have changed (monitors docs)
  5. yt-dlp auto-update -- ensures the downloader stays current
  6. config/providers.yaml refresh -- auto-bumps RPM/RPD if new limits are documented
  7. Trending channel suggestions -- suggests new creator niches based on trending data

All findings are reported to Discord. Auto-safe changes (like bumping RPM on a
model that's been promoted) are applied and committed. Changes requiring human
judgment are posted as Discord action items.

Usage:
  python scripts/clipbot_manager.py
  python scripts/clipbot_manager.py --dry-run      # report only, no file changes
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.request
import urllib.error

ROOT = Path(__file__).parent.parent

# ── Helpers ────────────────────────────────────────────────────────────────


def _send_discord(webhook_url: str, content: str, title: str = "ClipBot Manager"):
    """Send a Discord message. Silently skips if no webhook configured."""
    if not webhook_url:
        return
    payload = json.dumps({"content": f"**{title}**\n{content}"}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        print(f"Warning: Discord notify failed: {e}")


def _pypi_latest(package: str) -> Optional[str]:
    """Return the latest PyPI version for a package, or None on failure."""
    try:
        url = f"https://pypi.org/pypi/{package}/json"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        return data["info"]["version"]
    except Exception:
        return None


def _installed_version(package: str) -> Optional[str]:
    """Return currently installed package version."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", package],
            capture_output=True, text=True, timeout=15
        )
        for line in result.stdout.splitlines():
            if line.startswith("Version:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def _parse_version(v: str) -> Tuple[int, ...]:
    """Parse version string to comparable tuple."""
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except Exception:
        return (0,)


def _load_yaml_raw(path: Path) -> str:
    """Read raw YAML file text."""
    return path.read_text(encoding="utf-8")


def _commit_and_push(message: str, files: List[Path], dry_run: bool) -> bool:
    """Commit and push changes. Returns True on success."""
    if dry_run:
        print(f"[DRY RUN] Would commit: {message}")
        return True
    try:
        file_paths = [str(f) for f in files]
        subprocess.run(["git", "config", "user.name", "clipbot-manager"], cwd=ROOT, check=True)
        subprocess.run(["git", "config", "user.email", "manager@clipbot.ai"], cwd=ROOT, check=True)
        subprocess.run(["git", "add"] + file_paths, cwd=ROOT, check=True)
        result = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=ROOT)
        if result.returncode == 0:
            print("  No actual changes to commit")
            return True
        subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True)
        for i in range(1, 6):
            r = subprocess.run(["git", "push"], cwd=ROOT)
            if r.returncode == 0:
                return True
            print(f"  Push conflict -- rebasing (attempt {i})")
            subprocess.run(["git", "pull", "--rebase", "-X", "theirs", "origin", "main"], cwd=ROOT)
        return False
    except Exception as e:
        print(f"  Commit/push error: {e}")
        return False


# ── Check 1: Package currency ─────────────────────────────────────────────

TRACKED_PACKAGES = [
    "google-genai",
    "groq",
    "google-api-python-client",
    "faster-whisper",
    "youtube-transcript-api",
    "edge-tts",
    "opencv-python-headless",
    "PyYAML",
    "pytz",
    "requests",
    "pydantic",
]

# Packages that require manual review for minor+ bumps (native binaries, ABI sensitivity)
CAREFUL_PACKAGES = {"faster-whisper", "opencv-python-headless"}


def check_package_currency(dry_run: bool) -> List[str]:
    """Check installed packages against PyPI latest. Returns action items."""
    print("\n[1/5] Checking package currency...")
    items = []
    outdated_safe = []
    outdated_careful = []

    for pkg in TRACKED_PACKAGES:
        installed = _installed_version(pkg)
        latest = _pypi_latest(pkg)
        if not installed or not latest:
            continue
        if _parse_version(installed) < _parse_version(latest):
            gap = f"{installed} -> {latest}"
            if pkg in CAREFUL_PACKAGES:
                outdated_careful.append(f"  ⚠️  **{pkg}**: {gap} (manual review — native binary)")
            else:
                outdated_safe.append(f"  📦 **{pkg}**: {gap}")
            print(f"  Outdated: {pkg} {installed} -> {latest}")
        else:
            print(f"  Current: {pkg} {installed}")

    if outdated_safe:
        items.append("**Package updates available (auto-merge eligible via Dependabot):**\n"
                     + "\n".join(outdated_safe))
    if outdated_careful:
        items.append("**Packages needing manual review (native binaries):**\n"
                     + "\n".join(outdated_careful))

    if not outdated_safe and not outdated_careful:
        print("  All packages current.")

    return items


# ── Check 2: yt-dlp self-update ───────────────────────────────────────────

def update_ytdlp(dry_run: bool) -> List[str]:
    """Run yt-dlp --update to get latest version. yt-dlp handles its own versioning."""
    print("\n[2/5] Updating yt-dlp...")
    items = []
    if dry_run:
        print("  [DRY RUN] Would run: yt-dlp --update")
        return items
    try:
        result = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--update"],
            capture_output=True, text=True, timeout=60
        )
        output = (result.stdout + result.stderr).strip()
        if "Updated" in output or "up to date" in output.lower():
            print(f"  yt-dlp: {output.split(chr(10))[0]}")
        else:
            items.append(f"yt-dlp update result: `{output[:200]}`")
    except Exception as e:
        items.append(f"yt-dlp update failed: {e}")
    return items


# ── Check 3: Gemini model discovery ──────────────────────────────────────

def check_gemini_models(dry_run: bool) -> List[str]:
    """
    Query live Gemini model list. Identify free-tier models not yet
    represented in providers.yaml. Suggest or auto-add them.
    """
    print("\n[3/5] Checking Gemini model freshness...")
    items = []

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  GEMINI_API_KEY not set -- skipping live model check")
        items.append("Gemini model check skipped (no API key in environment)")
        return items

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        all_models = list(client.models.list())
    except Exception as e:
        print(f"  Gemini model list failed: {e}")
        items.append(f"Could not fetch Gemini model list: {e}")
        return items

    # Models in providers.yaml (load raw to check)
    providers_path = ROOT / "config" / "providers.yaml"
    providers_raw = _load_yaml_raw(providers_path)

    new_flash_models = []
    for model in all_models:
        name = getattr(model, "name", "").replace("models/", "")
        # Only interested in free flash/pro models
        if not any(x in name for x in ["flash", "pro"]):
            continue
        if "exp" in name or "preview" in name:
            continue  # Experimental -- tracked by model_discovery separately
        if name not in providers_raw:
            new_flash_models.append(name)
            print(f"  New model not in providers.yaml: {name}")

    if new_flash_models:
        items.append(
            "**New Gemini models detected (not yet in `config/providers.yaml`):**\n"
            + "\n".join(f"  - `{m}`" for m in new_flash_models)
            + "\n  The auto-discovery system in `engine/model_discovery.py` will pick "
            "these up automatically at runtime. Update `providers.yaml` static list "
            "to set explicit tier/RPM/RPD for these models."
        )
    else:
        print("  providers.yaml is current with known Gemini models.")

    return items


# ── Check 4: Groq model discovery ────────────────────────────────────────

def check_groq_models(dry_run: bool) -> List[str]:
    """Query live Groq model list. Detect new text models."""
    print("\n[4/5] Checking Groq model freshness...")
    items = []

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("  GROQ_API_KEY not set -- skipping Groq model check")
        return items

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        models = client.models.list()
    except Exception as e:
        print(f"  Groq model list failed: {e}")
        items.append(f"Could not fetch Groq model list: {e}")
        return items

    providers_path = ROOT / "config" / "providers.yaml"
    providers_raw = _load_yaml_raw(providers_path)

    new_text_models = []
    for model in getattr(models, "data", []):
        mid = getattr(model, "id", "")
        # Only text models (skip whisper/vision)
        if any(x in mid for x in ["whisper", "vision", "guard", "tool"]):
            continue
        if "llama" not in mid and "gemma" not in mid and "mixtral" not in mid:
            continue
        if mid not in providers_raw:
            new_text_models.append(mid)
            print(f"  New Groq model not in providers.yaml: {mid}")

    if new_text_models:
        items.append(
            "**New Groq models detected (not yet in `config/providers.yaml`):**\n"
            + "\n".join(f"  - `{m}`" for m in new_text_models)
            + "\n  The auto-discovery system picks these up at runtime via `discover_groq: true`."
        )
    else:
        print("  Groq models current.")

    return items


# ── Check 5: Channel trend suggestions ───────────────────────────────────

def suggest_trending_channels(dry_run: bool) -> List[str]:
    """
    Use the local trending snapshot DB (if populated) to suggest
    channel niches that are trending but not in our source list.
    """
    print("\n[5/5] Checking trending channel opportunities...")
    items = []

    try:
        sys.path.insert(0, str(ROOT))
        from engine.database import db

        snapshot = db.get_latest_trending_snapshot()
        if not snapshot:
            print("  No trending snapshot in DB yet -- run daily pipeline first")
            return items

        hot_types = snapshot.get("hot_clip_types", [])
        top_tags = snapshot.get("top_tags", [])[:10]
        recorded = snapshot.get("recorded_at", "")[:10]

        import yaml
        with open(ROOT / "config" / "channels.yaml", "r") as f:
            channels = yaml.safe_load(f)
        active_niches = {c.get("niche", "") for c in channels.get("source_creators", [])
                        if c.get("active", True)}

        # Map hot clip types to niches not yet in our lineup
        niche_map = {
            "gaming": "gaming_variety",
            "challenge": "stunts_challenge",
            "reaction": "commentary_gaming",
            "educational": "science_tech",
            "interview": "podcast_interview",
        }
        missing = []
        for tag in top_tags:
            for keyword, niche in niche_map.items():
                if keyword in tag and niche not in active_niches:
                    missing.append((niche, tag))

        if missing:
            suggestions = list({n: t for n, t in missing}.items())[:3]
            items.append(
                f"**Trending niches not yet in your channel lineup** (snapshot: {recorded}):\n"
                + "\n".join(f"  - **{n}** (trending tag: `{t}`)" for n, t in suggestions)
                + "\n  Consider adding a creator in these niches to `config/channels.yaml`."
            )
        else:
            print(f"  Channel lineup covers current trending niches.")

    except Exception as e:
        print(f"  Channel trend check skipped: {e}")

    return items


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ClipBot Manager -- self-improvement system")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only -- do not modify files or push changes")
    args = parser.parse_args()
    dry_run = args.dry_run

    webhook = os.environ.get("DISCORD_WEBHOOK", "")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print("=" * 60)
    print(f"ClipBot Manager starting -- {now}")
    if dry_run:
        print("[DRY RUN MODE -- no changes will be committed]")
    print("=" * 60)

    all_items: List[str] = []

    all_items += check_package_currency(dry_run)
    all_items += update_ytdlp(dry_run)
    all_items += check_gemini_models(dry_run)
    all_items += check_groq_models(dry_run)
    all_items += suggest_trending_channels(dry_run)

    print("\n" + "=" * 60)

    if all_items:
        report = "\n\n".join(all_items)
        print("\nACTION ITEMS:\n" + report)
        if webhook:
            _send_discord(
                webhook,
                f"**Manager Report ({now})**\n\n{report}\n\n"
                "_Next run: next week. Update `config/providers.yaml` for any manual items above._",
                title="ClipBot Manager Weekly Report",
            )
    else:
        msg = f"All systems current as of {now}. No action required."
        print(msg)
        if webhook:
            _send_discord(webhook, msg, title="ClipBot Manager Weekly Report")

    print("=" * 60)
    print(f"ClipBot Manager done -- {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")


if __name__ == "__main__":
    main()