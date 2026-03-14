# scripts/token_health.py
"""
Checks YouTube OAuth token validity and API key connectivity.
Run via: python scripts/token_health.py
Triggered by weekly GitHub Actions workflow.
"""
import os

from engine.discord_notifier import notifier


def check_youtube_token() -> bool:
    """Try a lightweight YouTube API call to verify the token works."""
    try:
        from pipeline.fetcher import get_youtube_service
        yt, creds = get_youtube_service()
        resp = yt.channels().list(part="snippet", mine=True).execute()
        name = resp["items"][0]["snippet"]["title"] if resp.get("items") else "Unknown"
        print(f"✅ YouTube token valid — channel: {name}")
        notifier.send_token_health(True, f"YouTube OAuth: ✅ healthy (channel: `{name}`)")
        return True
    except Exception as e:
        msg = f"YouTube OAuth: ❌ FAILED — {e}"
        print(f"❌ {msg}")
        notifier.send_token_health(False, msg)
        return False


def check_gemini_key() -> bool:
    try:
        from google import genai
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        # List models as a lightweight connectivity check
        list(client.models.list())
        print("✅ Gemini API key valid")
        return True
    except Exception as e:
        print(f"⚠️  Gemini API key check failed: {e}")
        return False


def check_groq_key() -> bool:
    try:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        client.models.list()
        print("✅ Groq API key valid")
        return True
    except Exception as e:
        print(f"⚠️  Groq API key check failed: {e}")
        return False


def run():
    print("🔑 Running token health checks...")
    yt_ok = check_youtube_token()
    gemini_ok = check_gemini_key()
    groq_ok = check_groq_key()

    all_ok = yt_ok and gemini_ok and groq_ok
    if not all_ok:
        issues = []
        if not yt_ok:
            issues.append("YouTube OAuth expired/invalid")
        if not gemini_ok:
            issues.append("Gemini API key invalid")
        if not groq_ok:
            issues.append("Groq API key invalid")
        notifier.send_error(
            "Token Health Issues",
            "\n".join(f"• {i}" for i in issues),
        )
    else:
        print("✅ All tokens healthy")


if __name__ == "__main__":
    run()
