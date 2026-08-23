# tests/test_dedup_and_coherence.py
"""
Tests for the new dedup and narrative-coherence features:
- Sentence boundary snapping
- Banked range exclusion
- Model discovery scoring
- Database dedup helpers
"""
import pytest
from unittest.mock import patch, MagicMock

from pipeline.clip_selector import (
    _snap_to_sentence_boundaries,
    _overlaps_any_banked,
    _clips_overlap,
)
from engine.model_discovery import _score_gemini_model, _score_groq_model


# ── Sentence boundary snapping ────────────────────────────────────────────

class TestSnapToSentenceBoundaries:
    def _make_words(self):
        """Build a word list with clear sentence boundaries."""
        return [
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "world.", "start": 0.5, "end": 1.0},
            {"word": "This", "start": 1.0, "end": 1.5},
            {"word": "is", "start": 1.5, "end": 2.0},
            {"word": "amazing!", "start": 2.0, "end": 2.5},
            {"word": "Next", "start": 2.5, "end": 3.0},
            {"word": "sentence.", "start": 3.0, "end": 3.5},
            {"word": "More", "start": 3.5, "end": 4.0},
            {"word": "words", "start": 4.0, "end": 4.5},
            {"word": "here.", "start": 4.5, "end": 5.0},
        ]

    def test_start_snaps_forward_to_sentence_start(self):
        """Clip starting mid-sentence snaps forward to next sentence start."""
        words = self._make_words()
        clip = {"start_seconds": 0.7, "end_seconds": 3.0,
                "clip_type": "funny", "hook_text": "", "confidence": 0.8,
                "reason": "", "duration": 2.3}
        with patch("engine.config_manager.ConfigManager.pipeline", new_callable=patch.PropertyMock) as mock_pipe:
            mock_pipe.return_value = {"min_clip_seconds": 1, "max_clip_seconds": 60}
            result = _snap_to_sentence_boundaries(clip, words)
        assert result is not None
        # Should snap to "This" at 1.0 (start of new sentence)
        assert result["start_seconds"] == 1.0

    def test_end_snaps_backward_to_sentence_end(self):
        """Clip ending mid-sentence snaps backward to last sentence end."""
        words = self._make_words()
        clip = {"start_seconds": 0.0, "end_seconds": 2.8,
                "clip_type": "funny", "hook_text": "", "confidence": 0.8,
                "reason": "", "duration": 2.8}
        with patch("engine.config_manager.ConfigManager.pipeline", new_callable=patch.PropertyMock) as mock_pipe:
            mock_pipe.return_value = {"min_clip_seconds": 1, "max_clip_seconds": 60}
            result = _snap_to_sentence_boundaries(clip, words)
        assert result is not None
        # Should snap to "amazing!" at 2.5 (end of sentence)
        assert result["end_seconds"] == 2.5

    def test_clip_too_short_after_snapping_rejected(self):
        """If snapping makes clip too short, it's rejected."""
        words = self._make_words()
        # Start at 0.7, end at 1.2 — after snapping start to 1.0, only 0.2s left
        clip = {"start_seconds": 0.7, "end_seconds": 1.2,
                "clip_type": "funny", "hook_text": "", "confidence": 0.8,
                "reason": "", "duration": 0.5}
        with patch("engine.config_manager.ConfigManager.pipeline", new_callable=patch.PropertyMock) as mock_pipe:
            mock_pipe.return_value = {"min_clip_seconds": 30, "max_clip_seconds": 60}
            result = _snap_to_sentence_boundaries(clip, words)
        assert result is None

    def test_clip_too_long_after_snapping_trimmed(self):
        """If snapping makes clip too long, it's trimmed to max_sec."""
        words = self._make_words()
        clip = {"start_seconds": 0.0, "end_seconds": 5.0,
                "clip_type": "funny", "hook_text": "", "confidence": 0.8,
                "reason": "", "duration": 5.0}
        with patch("engine.config_manager.ConfigManager.pipeline", new_callable=patch.PropertyMock) as mock_pipe:
            mock_pipe.return_value = {"min_clip_seconds": 1, "max_clip_seconds": 3}
            result = _snap_to_sentence_boundaries(clip, words)
        assert result is not None
        assert result["end_seconds"] == 3.0  # trimmed to max_sec

    def test_no_words_returns_original(self):
        """Empty word list returns clip unchanged."""
        clip = {"start_seconds": 10.0, "end_seconds": 50.0,
                "clip_type": "funny", "hook_text": "", "confidence": 0.8,
                "reason": "", "duration": 40.0}
        result = _snap_to_sentence_boundaries(clip, [])
        assert result == clip


# ── Banked range exclusion ────────────────────────────────────────────────

class TestOverlapsAnyBanked:
    def test_overlap_detected(self):
        clip = {"start_seconds": 10.0, "end_seconds": 50.0}
        banked = [{"start": 40.0, "end": 80.0}]
        assert _overlaps_any_banked(clip, banked) is True

    def test_no_overlap(self):
        clip = {"start_seconds": 10.0, "end_seconds": 50.0}
        banked = [{"start": 60.0, "end": 100.0}]
        assert _overlaps_any_banked(clip, banked) is False

    def test_adjacent_no_overlap(self):
        clip = {"start_seconds": 10.0, "end_seconds": 50.0}
        banked = [{"start": 50.0, "end": 90.0}]
        assert _overlaps_any_banked(clip, banked) is False

    def test_empty_banked_list(self):
        clip = {"start_seconds": 10.0, "end_seconds": 50.0}
        assert _overlaps_any_banked(clip, []) is False


# ── Model discovery scoring ───────────────────────────────────────────────

class TestModelScoring:
    def test_newer_model_scores_higher(self):
        assert _score_gemini_model("gemini-3.0-flash") > _score_gemini_model("gemini-2.5-flash")
        assert _score_gemini_model("gemini-2.5-flash") > _score_gemini_model("gemini-2.0-flash")
        assert _score_gemini_model("gemini-2.0-flash") > _score_gemini_model("gemini-1.5-flash")

    def test_non_text_models_excluded(self):
        assert _score_gemini_model("gemini-2.5-flash-vision") == -1
        assert _score_gemini_model("gemini-2.5-flash-audio") == -1
        assert _score_gemini_model("gemini-2.5-flash-tts") == -1
        assert _score_gemini_model("gemini-2.5-flash-embedding") == -1

    def test_unknown_format_scores_zero(self):
        assert _score_gemini_model("some-random-model") == 0

    def test_lite_variant_scores_same_as_base(self):
        # gemini-2.5-flash-lite should score same as gemini-2.5-flash
        assert _score_gemini_model("gemini-2.5-flash-lite") == _score_gemini_model("gemini-2.5-flash")


# ── Groq model discovery scoring ──────────────────────────────────────────

class TestGroqModelScoring:
    def test_preference_ladder_order(self):
        """Known-good models score higher than unknown ones."""
        known = _score_groq_model("llama-3.3-70b-versatile")
        unknown = _score_groq_model("brand-new-future-model")
        assert known > unknown
        assert known > 0

    def test_text_model_preferred_over_nontext(self):
        """Whisper/TTS/PlayAI models are excluded from text generation scoring."""
        assert _score_groq_model("whisper-large-v3") == -1
        assert _score_groq_model("playai-tts") == -1

    def test_unknown_model_is_usable(self):
        """Unknown Groq models still get a usable (>=0) score so they're picked up."""
        assert _score_groq_model("some-new-groq-model") >= 0