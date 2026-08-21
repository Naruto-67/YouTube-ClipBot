# engine/logger.py — structured console logging for ClipBot
from datetime import datetime


class StructuredLogger:
    """Structured, timestamped console logger with module tags and levels.

    Mirrors Ghost Engine's logger so ClipBot has consistent, greppable
    output across the pipeline, scripts, and GitHub Actions logs.
    """

    _ICONS = {
        "SUCCESS": "✅",
        "WARN": "⚠️",
        "ERROR": "🚨",
        "INFO": "⚙️",
    }

    @staticmethod
    def _log(tag: str, message: str, level: str = "INFO"):
        timestamp = datetime.utcnow().isoformat() + "Z"
        icon = StructuredLogger._ICONS.get(level, "⚙️")
        print(f"{icon} [{timestamp}] [{tag}] [{level}] {message}")

    @classmethod
    def engine(cls, msg: str, level: str = "INFO"):
        cls._log("ENGINE", msg, level)

    @classmethod
    def discovery(cls, msg: str, level: str = "INFO"):
        cls._log("DISCOVERY", msg, level)

    @classmethod
    def transcribe(cls, msg: str, level: str = "INFO"):
        cls._log("TRANSCRIBE", msg, level)

    @classmethod
    def select(cls, msg: str, level: str = "INFO"):
        cls._log("CLIP_SELECT", msg, level)

    @classmethod
    def render(cls, msg: str, level: str = "INFO"):
        cls._log("RENDER", msg, level)

    @classmethod
    def upload(cls, msg: str, level: str = "INFO"):
        cls._log("UPLOAD", msg, level)

    @classmethod
    def quota(cls, msg: str, level: str = "INFO"):
        cls._log("QUOTA", msg, level)

    @classmethod
    def error(cls, msg: str):
        cls._log("SYSTEM", msg, "ERROR")

    @classmethod
    def success(cls, msg: str):
        cls._log("SYSTEM", msg, "SUCCESS")


logger = StructuredLogger()