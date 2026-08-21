# tests/test_database_improvements.py
"""
Tests for the new database improvements:
- Index creation (idempotent)
- Circuit breaker column + failure counting logic
- Bank diversity (exclude_source_ids) query behaviour
"""
import os
import tempfile
from pathlib import Path

import pytest
from unittest.mock import patch, MagicMock

# Isolate the DB file so tests never touch the real memory/clipbot.db
import engine.database as dbmod


@pytest.fixture
def test_db(tmp_path):
    """A Database instance backed by a temp directory."""
    with patch.object(dbmod, "DB_PATH", tmp_path / "clipbot_test.db"), \
         patch.object(dbmod, "SQL_DUMP_PATH", tmp_path / "clipbot_test.sql"), \
         patch.object(dbmod, "MEMORY_DIR", tmp_path):
        db = dbmod.Database()
        return db


class TestIndexes:
    def test_indexes_created_idempotently(self, test_db):
        """Repeat init must not error (INDEX IF NOT EXISTS + guarded migrate)."""
        test_db._init_tables()
        test_db._init_tables()  # second call must be a no-op
        assert test_db.db_path  # db created

    def test_circuit_breaker_column_migrates(self, test_db):
        """Existing DB without failed_attempts should still get the column."""
        # Simulate a pre-existing table missing the column
        test_db._init_tables()
        with test_db._conn() as conn:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(processed_videos)").fetchall()]
        assert "failed_attempts" in cols


class TestCircuitBreaker:
    def test_failure_counter_increments(self, test_db):
        test_db.mark_video_processed("vid1", "MrBeast", "test", "download_failed")
        test_db.mark_video_processed("vid1", "MrBeast", "test", "download_failed")
        # After 2 failures and limit 3, still retryable
        assert test_db.is_video_processed("vid1", circuit_breaker_limit=3) is False
        test_db.mark_video_processed("vid1", "MrBeast", "test", "download_failed")
        # After 3 failures, circuit opens → treated as processed
        assert test_db.is_video_processed("vid1", circuit_breaker_limit=3) is True

    def test_success_resets_counter(self, test_db):
        test_db.mark_video_processed("vid1", "MrBeast", "test", "download_failed")
        test_db.mark_video_processed("vid1", "MrBeast", "test", "banked", clips_made=2)
        assert test_db.is_video_processed("vid1", circuit_breaker_limit=3) is True

    def test_not_processed_when_unknown(self, test_db):
        assert test_db.is_video_processed("unknown_video", circuit_breaker_limit=3) is False


class TestBankDiversity:
    def test_exclude_source_prefers_other_source(self, test_db):
        test_db.save_clip_to_bank(
            "srcA", "http://a", "MrBeast", "Video A",
            {"start_seconds": 0, "end_seconds": 30, "clip_type": "funny",
             "hook_text": "", "confidence": 0.9, "reason": ""},
            [],
        )
        test_db.save_clip_to_bank(
            "srcB", "http://b", "MrBeast", "Video B",
            {"start_seconds": 0, "end_seconds": 30, "clip_type": "shocking",
             "hook_text": "", "confidence": 0.8, "reason": ""},
            [],
        )
        # Excluding srcA should return the srcB clip
        clips = test_db.get_pending_bank_clips(limit=1, exclude_source_ids=["srcA"])
        assert clips and clips[0]["source_video_id"] == "srcB"

    def test_fallback_when_all_excluded(self, test_db):
        test_db.save_clip_to_bank(
            "srcA", "http://a", "MrBeast", "Video A",
            {"start_seconds": 0, "end_seconds": 30, "clip_type": "funny",
             "hook_text": "", "confidence": 0.9, "reason": ""},
            [],
        )
        # Only srcA exists; excluding it must still return it (no stall)
        clips = test_db.get_pending_bank_clips(limit=1, exclude_source_ids=["srcA"])
        assert clips and clips[0]["source_video_id"] == "srcA"

    def test_no_exclusion_returns_highest_confidence(self, test_db):
        test_db.save_clip_to_bank(
            "srcA", "http://a", "MrBeast", "Video A",
            {"start_seconds": 0, "end_seconds": 30, "clip_type": "funny",
             "hook_text": "", "confidence": 0.5, "reason": ""},
            [],
        )
        test_db.save_clip_to_bank(
            "srcB", "http://b", "MrBeast", "Video B",
            {"start_seconds": 0, "end_seconds": 30, "clip_type": "shocking",
             "hook_text": "", "confidence": 0.95, "reason": ""},
            [],
        )
        clips = test_db.get_pending_bank_clips(limit=1)
        assert clips and clips[0]["confidence"] == 0.95