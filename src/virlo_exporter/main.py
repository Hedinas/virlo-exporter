from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from virlo_exporter.config import SettingsStore, app_data_dir, project_root
from virlo_exporter.storage.database import Database
from virlo_exporter.storage.key_store import ApiKeyStore
from virlo_exporter.ui.main_window import MainWindow
from virlo_exporter.ui.theme import apply_dark_palette, install_dark_title_bar
from virlo_exporter.utils.logging import configure_logging


def main() -> int:
    QCoreApplication.setOrganizationName("Virlo Exporter")
    QCoreApplication.setApplicationName("Virlo Exporter")
    app = QApplication(sys.argv)
    app.setApplicationDisplayName("Virlo Exporter")
    app.setStyle("Fusion")
    apply_dark_palette(app)
    icon = project_root() / "assets" / "app_icon.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    data_dir = app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(data_dir / "logs")
    settings_store = SettingsStore(data_dir / "settings.json")
    settings = settings_store.load()
    Path(settings.export_folder).mkdir(parents=True, exist_ok=True)
    database = Database(data_dir / "virlo-exporter.db")
    window = MainWindow(settings_store, settings, ApiKeyStore(), database)
    install_dark_title_bar(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
