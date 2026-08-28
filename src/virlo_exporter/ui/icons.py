"""Theme-aware icons built from the approved Virlo monochrome masks."""

from __future__ import annotations

import sys
from functools import cache
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

SIZE = 18
NORMAL_COLOR = "#AAB4C2"
ACTIVE_COLOR = "#EDF4FF"
DISABLED_COLOR = "#4A515C"

_MASK_FILES = {
    "gear": "gear.png",
    "folder": "folder.png",
    "copy": "copy.png",
    "pencil": "pencil.png",
    "workflow": "workflow.png",
    "document": "report.png",
    "report": "report.png",
    "trash": "trash.png",
    "warning": "report.png",
}


def _asset_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets" / "icons"
    return Path(__file__).resolve().parents[3] / "assets" / "icons"


@cache
def mask_path(name: str) -> Path:
    return _asset_root() / _MASK_FILES[name]


def _tinted_pixmap(name: str, size: int, color: str) -> QPixmap:
    source = QPixmap(str(mask_path(name))).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(color))
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawPixmap(0, 0, source)
    painter.end()
    return pixmap


@cache
def icon(name: str, size: int = SIZE) -> QIcon:
    result = QIcon()
    result.addPixmap(_tinted_pixmap(name, size, NORMAL_COLOR), QIcon.Mode.Normal)
    result.addPixmap(_tinted_pixmap(name, size, ACTIVE_COLOR), QIcon.Mode.Active)
    result.addPixmap(_tinted_pixmap(name, size, ACTIVE_COLOR), QIcon.Mode.Selected)
    result.addPixmap(_tinted_pixmap(name, size, DISABLED_COLOR), QIcon.Mode.Disabled)
    return result
