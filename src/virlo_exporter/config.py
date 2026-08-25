from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

APP_NAME = "Virlo Exporter"
APP_AUTHOR = "Virlo Exporter"
DEFAULT_API_BASE = "https://api.virlo.ai/v1"


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    override = os.getenv("VIRLO_EXPORTER_DATA_DIR")
    return Path(override) if override else Path(user_data_dir(APP_NAME, APP_AUTHOR))


@dataclass(slots=True)
class AppSettings:
    api_base_url: str = DEFAULT_API_BASE
    export_folder: str = ""
    open_folder_after_export: bool = True
    baseline_sample_size: int = 150
    refresh_interval: str = "auto"

    @classmethod
    def defaults(cls) -> AppSettings:
        return cls(export_folder=str(project_root() / "exports"))


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "settings.json"

    def load(self) -> AppSettings:
        settings = AppSettings.defaults()
        if not self.path.exists():
            return settings
        try:
            values: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return settings
        for key in asdict(settings):
            if key in values:
                setattr(settings, key, values[key])
        settings.baseline_sample_size = max(0, min(1000, int(settings.baseline_sample_size)))
        return settings

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        temporary.replace(self.path)
