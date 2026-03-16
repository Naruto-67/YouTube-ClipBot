# engine/quota_manager.py
import json
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import pytz

from engine.config_manager import config_manager

ROOT = Path(__file__).parent.parent
STATE_PATH = ROOT / "memory" / "quota_state.json"

PT = pytz.timezone("US/Pacific")
UTC = pytz.utc


class QuotaManager:
    """
    Tracks quotas for YouTube Data API, Gemini, and Groq.

    Key design:
    - YouTube and Gemini reset at PT midnight
    - Groq resets at UTC midnight
    - RPM is tracked via a sliding 60-second window (not per-minute bucket)
    - TPM is tracked per 60-second window as well
    - All counters persist to disk so a crash mid-run doesn't lose state
    """

    def __init__(self):
        self._state: Dict = self._load_state()
        # RPM sliding windows: key = "provider:model" → deque of Unix timestamps
        self._rpm_windows: Dict[str, deque] = {}

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_state(self) -> Dict:
        STATE_PATH.parent.mkdir(exist_ok=True)
        if STATE_PATH.exists():
            try:
                return json.loads(STATE_PATH.read_text())
            except Exception:
                pass
        return {}

    def _save_state(self):
        STATE_PATH.write_text(json.dumps(self._state, indent=2))

    # ── Date keys (provider-specific timezones) ───────────────────────────

    def _date_key(self, provider: str) -> str:
        """Return today's date string in the provider's reset timezone."""
        providers_cfg = config_manager.providers
        tz_name = providers_cfg.get(provider, {}).get("reset_timezone", "UTC")
        try:
            tz = pytz.timezone(tz_name)
            return datetime.now(tz).strftime("%Y-%m-%d")
        except Exception:
            # Fallback to UTC using stdlib only — no pytz dependency
            from datetime import timezone as _tz
            return datetime.now(_tz.utc).strftime("%Y-%m-%d")

    # ── Generic RPD counter ───────────────────────────────────────────────

    def _get_rpd(self, provider: str, model: str) -> int:
        key = f"{provider}:{model}:rpd"
        state = self._state.get(key, {})
        if state.get("date") != self._date_key(provider):
            return 0
        return state.get("value", 0)

    def _inc_rpd(self, provider: str, model: str, amount: int = 1):
        key = f"{provider}:{model}:rpd"
        date = self._date_key(provider)
        state = self._state.get(key, {})
        if state.get("date") != date:
            state = {"date": date, "value": 0}
        state["value"] = state.get("value", 0) + amount
        self._state[key] = state
        self._save_state()

    # ── YouTube quota (units, not RPD) ────────────────────────────────────

    def _get_yt_units(self) -> int:
        key = "youtube:data_api:units"
        state = self._state.get(key, {})
        if state.get("date") != self._date_key("youtube"):
            return 0
        return state.get("value", 0)

    def _inc_yt_units(self, amount: int):
        key = "youtube:data_api:units"
        date = self._date_key("youtube")
        state = self._state.get(key, {})
        if state.get("date") != date:
            state = {"date": date, "value": 0}
        state["value"] = state.get("value", 0) + amount
        self._state[key] = state
        self._save_state()

    # ── RPM sliding window ────────────────────────────────────────────────

    def _rpm_count(self, provider: str, model: str) -> int:
        """Return how many calls have been made in the last 60 seconds."""
        wkey = f"{provider}:{model}"
        now = time.time()
        if wkey not in self._rpm_windows:
            self._rpm_windows[wkey] = deque()
        window = self._rpm_windows[wkey]
        while window and now - window[0] > 60:
            window.popleft()
        return len(window)

    def _rpm_add(self, provider: str, model: str):
        wkey = f"{provider}:{model}"
        if wkey not in self._rpm_windows:
            self._rpm_windows[wkey] = deque()
        self._rpm_windows[wkey].append(time.time())

    # ── Public: YouTube ───────────────────────────────────────────────────

    def can_use_youtube(self, units: int) -> Tuple[bool, str]:
        daily_limit = config_manager.providers.get("youtube", {}).get("daily_units", 10000)
        used = self._get_yt_units()
        if used + units > daily_limit:
            return False, f"YouTube quota exhausted ({used}/{daily_limit} units)"
        return True, "ok"

    def record_youtube(self, units: int, operation: str = ""):
        from engine.database import db
        self._inc_yt_units(units)
        db.log_quota("youtube", units, operation)

    def youtube_units_remaining(self) -> int:
        daily_limit = config_manager.providers.get("youtube", {}).get("daily_units", 10000)
        return max(0, daily_limit - self._get_yt_units())

    # ── Public: AI models ─────────────────────────────────────────────────

    def can_use_model(self, provider: str, model_name: str) -> Tuple[bool, str]:
        models = config_manager.providers.get(provider, {}).get("models", [])
        cfg = next((m for m in models if m["name"] == model_name), None)
        if cfg is None:
            return False, f"Unknown model: {model_name}"

        rpd_limit = cfg.get("rpd", 999999)
        rpm_limit = cfg.get("rpm", 999)

        if self._get_rpd(provider, model_name) >= rpd_limit:
            return False, f"RPD exhausted ({self._get_rpd(provider, model_name)}/{rpd_limit})"

        if self._rpm_count(provider, model_name) >= rpm_limit:
            return False, f"RPM limit reached ({rpm_limit}/min)"

        return True, "ok"

    def record_model_use(self, provider: str, model_name: str):
        from engine.database import db
        self._rpm_add(provider, model_name)
        self._inc_rpd(provider, model_name)
        db.log_quota(f"ai_{provider}", 1, "generate", model_name)

    def mark_model_exhausted(self, provider: str, model_name: str):
        """
        Spike this model's RPD counter to its limit so can_use_model()
        returns False and get_best_available_model() skips it, falling
        through to the next tier (e.g. Groq after Gemini 429s).

        Called when a 429 / RESOURCE_EXHAUSTED is received — the actual
        quota is exhausted on the provider side even if our local counter
        thinks otherwise (e.g. after a DB reset on a fresh runner).
        """
        models = config_manager.providers.get(provider, {}).get("models", [])
        cfg = next((m for m in models if m["name"] == model_name), None)
        if cfg is None:
            return
        rpd_limit = cfg.get("rpd", 999999)
        # Set RPD counter to limit so can_use_model returns False
        key = f"{provider}:{model_name}:rpd"
        self._state[key] = {
            "date": self._date_key(provider),
            "value": rpd_limit,
        }
        self._save_state()
        print(f"   ⚠️  Marked {model_name} as RPD-exhausted — "
              f"will use next model in chain")


        """
        Return (provider, model_name, model_config) for the highest-priority
        model that is currently available (within RPM and RPD limits).
        Returns None if all models are exhausted for today.
        """
        providers_cfg = config_manager.providers
        all_models = []

        for provider in ("gemini", "groq"):
            for m in providers_cfg.get(provider, {}).get("models", []):
                all_models.append((provider, m))

        # Sort by tier ascending (tier 1 = best)
        all_models.sort(key=lambda x: x[1].get("tier", 99))

        for provider, m_cfg in all_models:
            ok, _ = self.can_use_model(provider, m_cfg["name"])
            if ok:
                return provider, m_cfg["name"], m_cfg

        return None

    def wait_for_rpm_if_needed(self, provider: str, model_name: str):
        """Block until the RPM window has capacity."""
        models = config_manager.providers.get(provider, {}).get("models", [])
        cfg = next((m for m in models if m["name"] == model_name), None)
        if cfg is None:
            return
        rpm_limit = cfg.get("rpm", 60)
        wkey = f"{provider}:{model_name}"

        while True:
            now = time.time()
            window = self._rpm_windows.get(wkey, deque())
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) < rpm_limit:
                break
            wait = 61 - (now - window[0])
            if wait > 0:
                print(f"⏳ RPM wait for {model_name}: {wait:.1f}s")
                time.sleep(wait + 0.5)

    # ── Status report ─────────────────────────────────────────────────────

    def get_status_report(self) -> Dict:
        providers_cfg = config_manager.providers
        report: Dict = {}

        yt_limit = providers_cfg.get("youtube", {}).get("daily_units", 10000)
        yt_used = self._get_yt_units()
        report["youtube"] = {
            "used": yt_used,
            "limit": yt_limit,
            "remaining": yt_limit - yt_used,
            "pct_used": round(yt_used / yt_limit * 100, 1),
        }

        report["models"] = {}
        for provider in ("gemini", "groq"):
            for m in providers_cfg.get(provider, {}).get("models", []):
                name = m["name"]
                rpd = m.get("rpd", 0)
                used = self._get_rpd(provider, name)
                report["models"][name] = {
                    "provider": provider,
                    "tier": m.get("tier", 99),
                    "rpd_used": used,
                    "rpd_limit": rpd,
                    "remaining": max(0, rpd - used),
                    "pct_used": round(used / rpd * 100, 1) if rpd > 0 else 0,
                }

        return report


quota_manager = QuotaManager()
