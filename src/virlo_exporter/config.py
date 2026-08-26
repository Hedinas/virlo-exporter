from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

logger = logging.getLogger(__name__)

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


def legacy_export_root() -> Path:
    """Where exports used to default to: inside the app/build directory.

    For a frozen build this is next to the .exe -- i.e. inside PyInstaller's
    own dist output, which gets wiped on every `--clean` rebuild. Kept only
    so a running app can detect and migrate away from it.
    """
    return project_root() / "exports"


def documents_export_root() -> Path:
    """User-facing exports always live under Documents, never inside the
    frozen app/build directory (see legacy_export_root)."""
    return Path.home() / "Documents" / APP_NAME / "Exports"


@dataclass(slots=True)
class AppSettings:
    api_base_url: str = DEFAULT_API_BASE
    export_folder: str = ""
    open_folder_after_export: bool = True
    baseline_sample_size: int = 150
    refresh_interval: str = "auto"

    @classmethod
    def defaults(cls) -> AppSettings:
        return cls(export_folder=str(documents_export_root()))


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
        if settings.export_folder == str(legacy_export_root()):
            # A persisted export_folder that still matches the old unsafe
            # default -- inside the app/build directory -- is silently
            # redirected forward. Existing export records keep working:
            # they store their own absolute path, so nothing already on
            # disk needs to move for this alone.
            settings.export_folder = str(documents_export_root())
        return settings

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        temporary.replace(self.path)


def migrate_legacy_exports(settings: AppSettings) -> list[str]:
    """Copy (never move/delete) any export folders still sitting in the old
    in-app-directory location into the current export_folder. Existing
    files are never overwritten or removed either way, so this is safe to
    run on every startup."""
    legacy_root = legacy_export_root()
    target_root = Path(settings.export_folder)
    migrated: list[str] = []
    if not legacy_root.exists() or legacy_root == target_root:
        return migrated
    try:
        target_root.mkdir(parents=True, exist_ok=True)
        for entry in legacy_root.iterdir():
            destination = target_root / entry.name
            if destination.exists():
                continue
            if entry.is_dir():
                shutil.copytree(entry, destination)
            else:
                shutil.copy2(entry, destination)
            migrated.append(entry.name)
    except OSError:
        logger.exception("Failed to migrate legacy exports from %s", legacy_root)
    return migrated
