#!/usr/bin/env python3
# scripts/setup_auth.py
"""
ONE-TIME SETUP SCRIPT — Run this locally to generate your YouTube OAuth credentials.

Usage:
  pip install google-auth-oauthlib google-api-python-client
  python scripts/setup_auth.py

Then copy the printed JSON into your GitHub Secret named YOUTUBE_CREDENTIALS.
"""
import json
import os
import sys

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def main():
    print("=" * 60)
    print("ClipBot — YouTube OAuth Setup")
    print("=" * 60)
    print()
    print("You need a Google Cloud project with YouTube Data API v3 enabled.")
    print("Download your OAuth 2.0 Client ID JSON from:")
    print("  https://console.cloud.google.com/apis/credentials")
    print()

    client_id = input("Paste your Client ID: ").strip()
    client_secret = input("Paste your Client Secret: ").strip()

    if not client_id or not client_secret:
        print("❌ Client ID and Client Secret are required.")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=SCOPES,
        )

        print()
        print("🌐 A browser window will open. Log into the YouTube account")
        print("   you want to upload to and grant the requested permissions.")
        print()

        creds = flow.run_local_server(port=0)

        output = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": creds.refresh_token,
        }

        print()
        print("=" * 60)
        print("✅ SUCCESS! Copy this JSON into your GitHub Secret")
        print('   Secret name: YOUTUBE_CREDENTIALS')
        print("=" * 60)
        print()
        print(json.dumps(output, indent=2))
        print()
        print("=" * 60)

    except ImportError:
        print("❌ Missing dependency. Run:")
        print("   pip install google-auth-oauthlib google-api-python-client")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Auth failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
