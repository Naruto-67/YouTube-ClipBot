# engine/config_manager.py
import yaml
import copy
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent


class ConfigManager:
    """
    Loads all YAML config files. Every setting the pipeline uses
    comes from here — nothing is hardcoded in the pipeline code.
    Call reload() to pick up config changes without restarting.
    """

    def __init__(self):
        self._cache: Dict[str, Any] = {}

    def _load(self, name: str) -> Dict:
        path = ROOT / "config" / f"{name}.yaml"
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _get(self, name: str) -> Dict:
        if name not in self._cache:
            self._cache[name] = self._load(name)
        # Return deepcopy so callers can't mutate the cache
        return copy.deepcopy(self._cache[name])

    @property
    def pipeline(self) -> Dict:
        return self._get("pipeline")

    @property
    def providers(self) -> Dict:
        return self._get("providers")

    @property
    def prompts(self) -> Dict:
        return self._get("prompts")

    @property
    def channels(self) -> Dict:
        return self._get("channels")

    def get_upload_channel(self) -> Dict:
        return self.channels["upload_channel"]

    def get_active_source_creators(self) -> List[Dict]:
        return [c for c in self.channels["source_creators"] if c.get("active", True)]

    def get_yt_unit_cost(self, operation: str) -> int:
        return self.providers.get("youtube", {}).get("unit_costs", {}).get(operation, 1)

    def reload(self):
        """Force reload all configs on next access."""
        self._cache.clear()


config_manager = ConfigManager()
