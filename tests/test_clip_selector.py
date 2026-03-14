# tests/test_clip_selector.py
import pytest
from pipeline.clip_selector import _validate_clip, _remove_overlaps, _clips_overlap


class TestValidateClip:
    def test_valid_clip_passes(self):
        clip = {
            "start_seconds": 10.0,
            "end_seconds": 55.0,
            "clip_type": "funny",
            "hook_text": "This is hilarious",
            "confidence": 0.85,
            "reason": "Great reaction",
        }
        result = _validate_clip(clip, video_duration=120.0, min_sec=30, max_sec=60)
        assert result is not None
        assert result["start_seconds"] == 10.0
        assert result["clip_type"] == "funny"

    def test_negative_start_rejected(self):
        clip = {"start_seconds": -5.0, "end_seconds": 40.0, "clip_type": "funny",
                "hook_text": "", "confidence": 0.8, "reason": ""}
        assert _validate_clip(clip, 120.0, 30, 60) is None

    def test_start_beyond_duration_rejected(self):
        clip = {"start_seconds": 130.0, "end_seconds": 160.0, "clip_type": "funny",
                "hook_text": "", "confidence": 0.8, "reason": ""}
        assert _validate_clip(clip, 120.0, 30, 60) is None

    def test_end_clamped_to_duration(self):
        clip = {"start_seconds": 80.0, "end_seconds": 150.0, "clip_type": "funny",
                "hook_text": "", "confidence": 0.8, "reason": ""}
        result = _validate_clip(clip, 120.0, 30, 70)
        assert result is not None
        assert result["end_seconds"] == 120.0

    def test_too_short_rejected(self):
        clip = {"start_seconds": 10.0, "end_seconds": 20.0, "clip_type": "funny",
                "hook_text": "", "confidence": 0.8, "reason": ""}
        assert _validate_clip(clip, 120.0, 30, 60) is None

    def test_too_long_trimmed(self):
        clip = {"start_seconds": 10.0, "end_seconds": 85.0, "clip_type": "funny",
                "hook_text": "", "confidence": 0.8, "reason": ""}
        result = _validate_clip(clip, 200.0, 30, 60)
        assert result is not None
        assert result["end_seconds"] == 10.0 + 60

    def test_invalid_clip_type_defaults(self):
        clip = {"start_seconds": 10.0, "end_seconds": 50.0, "clip_type": "INVALID_TYPE",
                "hook_text": "", "confidence": 0.8, "reason": ""}
        result = _validate_clip(clip, 120.0, 30, 60)
        assert result is not None
        assert result["clip_type"] == "engaging"

    def test_hook_text_truncated_to_10_words(self):
        clip = {"start_seconds": 10.0, "end_seconds": 50.0, "clip_type": "funny",
                "hook_text": "one two three four five six seven eight nine ten eleven",
                "confidence": 0.8, "reason": ""}
        result = _validate_clip(clip, 120.0, 30, 60)
        assert result is not None
        assert len(result["hook_text"].split()) == 10

    def test_confidence_clamped(self):
        clip = {"start_seconds": 10.0, "end_seconds": 50.0, "clip_type": "funny",
                "hook_text": "", "confidence": 1.5, "reason": ""}
        result = _validate_clip(clip, 120.0, 30, 60)
        assert result["confidence"] == 1.0


class TestOverlaps:
    def test_overlapping_clips_removed(self):
        clips = [
            {"start_seconds": 10.0, "end_seconds": 55.0, "confidence": 0.9,
             "clip_type": "funny", "hook_text": "", "reason": "", "duration": 45},
            {"start_seconds": 40.0, "end_seconds": 80.0, "confidence": 0.7,
             "clip_type": "shocking", "hook_text": "", "reason": "", "duration": 40},
        ]
        result = _remove_overlaps(clips)
        assert len(result) == 1
        assert result[0]["confidence"] == 0.9  # Higher confidence kept

    def test_non_overlapping_clips_both_kept(self):
        clips = [
            {"start_seconds": 10.0, "end_seconds": 50.0, "confidence": 0.9,
             "clip_type": "funny", "hook_text": "", "reason": "", "duration": 40},
            {"start_seconds": 60.0, "end_seconds": 100.0, "confidence": 0.8,
             "clip_type": "shocking", "hook_text": "", "reason": "", "duration": 40},
        ]
        result = _remove_overlaps(clips)
        assert len(result) == 2


class TestClipsOverlap:
    def test_overlap_detected(self):
        a = {"start_seconds": 10.0, "end_seconds": 55.0}
        b = {"start_seconds": 40.0, "end_seconds": 80.0}
        assert _clips_overlap(a, b) is True

    def test_no_overlap(self):
        a = {"start_seconds": 10.0, "end_seconds": 50.0}
        b = {"start_seconds": 60.0, "end_seconds": 100.0}
        assert _clips_overlap(a, b) is False

    def test_adjacent_clips_no_overlap(self):
        a = {"start_seconds": 10.0, "end_seconds": 50.0}
        b = {"start_seconds": 50.0, "end_seconds": 90.0}
        assert _clips_overlap(a, b) is False
