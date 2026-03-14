#!/usr/bin/env python3
# scripts/download_font.py
"""
Downloads Anton-Regular.ttf if not already present.
Called automatically at the start of the render step in GitHub Actions.
Can also be run locally:  python scripts/download_font.py

NOTE: Uses the direct raw TTF from Google's fonts GitHub repo instead of
the Google Fonts zip download endpoint, which now returns an HTML page
instead of a zip file and can no longer be used.
"""
import sys
from pathlib import Path

import requests

FONT_DIR = Path(__file__).parent.parent / "assets" / "fonts"
FONT_PATH = FONT_DIR / "Anton-Regular.ttf"

# Direct raw TTF from Google Fonts GitHub — no unzipping needed
FONT_URLS = [
    "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    "https://github.com/google/fonts/raw/refs/heads/main/ofl/anton/Anton-Regular.ttf",
]


def download():
    if FONT_PATH.exists():
        print(f"✅ Font already present: {FONT_PATH.name}")
        return True

    FONT_DIR.mkdir(parents=True, exist_ok=True)

    for url in FONT_URLS:
        print(f"⬇️  Downloading Anton font from: {url}")
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()

            content = resp.content

            # Sanity check — a real TTF file is always well over 10 KB
            if len(content) < 10_000:
                print(f"⚠️  Response too small ({len(content)} bytes) — "
                      f"likely not a font file, trying next URL...")
                continue

            FONT_PATH.write_bytes(content)
            print(f"✅ Font saved to {FONT_PATH}")
            return True

        except Exception as e:
            print(f"⚠️  Download failed from {url}: {e}")
            continue

    print("❌ All font download attempts failed.")
    print("   Captions will use system fallback font.")
    return False


if __name__ == "__main__":
    ok = download()
    sys.exit(0 if ok else 1)
