#!/usr/bin/env python3
# scripts/download_font.py
"""
Downloads Anton-Regular.ttf from Google Fonts if not already present.
Called automatically at the start of the render step in GitHub Actions.
Can also be run locally:  python scripts/download_font.py
"""
import io
import sys
import zipfile
from pathlib import Path

import requests

FONT_DIR = Path(__file__).parent.parent / "assets" / "fonts"
FONT_PATH = FONT_DIR / "Anton-Regular.ttf"
# Direct download URL for Anton font zip from Google Fonts
FONT_URL = "https://fonts.google.com/download?family=Anton"


def download():
    if FONT_PATH.exists():
        print(f"✅ Font already present: {FONT_PATH.name}")
        return True

    FONT_DIR.mkdir(parents=True, exist_ok=True)

    print("⬇️  Downloading Anton font from Google Fonts...")
    try:
        resp = requests.get(FONT_URL, timeout=30)
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            for name in z.namelist():
                if name.endswith("Anton-Regular.ttf"):
                    FONT_PATH.write_bytes(z.read(name))
                    print(f"✅ Font saved to {FONT_PATH}")
                    return True

        print("❌ Anton-Regular.ttf not found in downloaded zip")
        return False

    except Exception as e:
        print(f"⚠️  Font download failed: {e}")
        print("   Captions will use system fallback font.")
        return False


if __name__ == "__main__":
    ok = download()
    sys.exit(0 if ok else 1)
