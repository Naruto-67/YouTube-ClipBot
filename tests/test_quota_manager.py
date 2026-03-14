# tests/test_quota_manager.py
import time
import pytest
from unittest.mock import patch, MagicMock
from engine.quota_manager import QuotaManager


@pytest.fixture
def qm(tmp_path):
    """Fresh QuotaManager with isolated state file."""
    with patch("engine.quota_manager.STATE_PATH", tmp_path / "quota_state.json"), \
         patch("engine.quota_manager.config_manager") as mock_cfg:

        mock_cfg.providers = {
            "youtube": {
                "daily_units": 10000,
                "reset_timezone": "UTC",
            },
            "gemini": {
                "reset_timezone": "UTC",
                "models": [
                    {"name": "gemini-2.5-flash", "tier": 1, "rpm": 10, "rpd": 250, "stable": True},
                    {"name": "gemini-2.5-flash-lite", "tier": 2, "rpm": 15, "rpd": 1000, "stable": True},
                ],
            },
            "groq": {
                "reset_timezone": "UTC",
                "models": [
                    {"name": "llama-3.3-70b-versatile", "tier": 3, "rpm": 30, "rpd": 14400, "stable": True},
                ],
            },
        }
        mock_cfg.get_yt_unit_cost = MagicMock(return_value=1)

        qm = QuotaManager.__new__(QuotaManager)
        qm._state = {}
        qm._rpm_windows = {}

        with patch.object(qm, "_save_state"):
            yield qm


class TestYouTubeQuota:
    def test_can_use_within_limit(self, qm):
        ok, msg = qm.can_use_youtube(100)
        assert ok is True

    def test_blocked_when_over_limit(self, qm):
        qm._state["youtube:data_api:units"] = {"date": qm._date_key("youtube"), "value": 9950}
        ok, msg = qm.can_use_youtube(100)
        assert ok is False
        assert "quota exhausted" in msg.lower()

    def test_remaining_calculation(self, qm):
        qm._state["youtube:data_api:units"] = {"date": qm._date_key("youtube"), "value": 3000}
        assert qm.youtube_units_remaining() == 7000


class TestAIModelSelection:
    def test_best_model_returned(self, qm):
        result = qm.get_best_available_model()
        assert result is not None
        provider, model_name, cfg = result
        assert provider == "gemini"
        assert model_name == "gemini-2.5-flash"

    def test_falls_back_when_primary_rpd_exhausted(self, qm):
        # Exhaust Gemini 2.5 Flash RPD
        qm._state["gemini:gemini-2.5-flash:rpd"] = {
            "date": qm._date_key("gemini"), "value": 250
        }
        result = qm.get_best_available_model()
        assert result is not None
        _, model_name, _ = result
        assert model_name == "gemini-2.5-flash-lite"

    def test_returns_none_when_all_exhausted(self, qm):
        for provider, model in [
            ("gemini", "gemini-2.5-flash"),
            ("gemini", "gemini-2.5-flash-lite"),
            ("groq", "llama-3.3-70b-versatile"),
        ]:
            limits = {"gemini": 250, "gemini": 1000, "groq": 14400}
            qm._state[f"{provider}:{model}:rpd"] = {
                "date": qm._date_key(provider), "value": 99999
            }
        result = qm.get_best_available_model()
        assert result is None

    def test_rpm_window_respects_limit(self, qm):
        # Fill the RPM window for gemini-2.5-flash (limit=10)
        import time
        wkey = "gemini:gemini-2.5-flash"
        from collections import deque
        qm._rpm_windows[wkey] = deque([time.time()] * 10)

        ok, msg = qm.can_use_model("gemini", "gemini-2.5-flash")
        assert ok is False
        assert "RPM" in msg
