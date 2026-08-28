from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QImage

from virlo_exporter.ui import icons


def _average_visible_rgb(icon: QIcon, mode: QIcon.Mode) -> tuple[float, float, float]:
    image = icon.pixmap(QSize(32, 32), mode).toImage().convertToFormat(
        QImage.Format.Format_RGBA8888
    )
    pixels = bytes(image.bits())
    visible = [
        pixels[index : index + 3]
        for index in range(0, len(pixels), 4)
        if pixels[index + 3]
    ]
    return tuple(
        sum(pixel[channel] for pixel in visible) / len(visible) for channel in range(3)
    )


def test_every_approved_icon_mask_exists() -> None:
    for name in ("gear", "folder", "copy", "pencil", "workflow", "report", "trash"):
        assert icons.mask_path(name).is_file()


def test_icon_modes_have_distinct_foreground_brightness(qapp) -> None:
    report = icons.icon("report", 32)
    disabled = sum(_average_visible_rgb(report, QIcon.Mode.Disabled))
    normal = sum(_average_visible_rgb(report, QIcon.Mode.Normal))
    active = sum(_average_visible_rgb(report, QIcon.Mode.Active))

    assert disabled < normal < active


def test_report_alias_uses_the_canonical_report_mask(qapp) -> None:
    assert icons.icon("document", 24).pixmap(24, 24).toImage() == icons.icon(
        "report", 24
    ).pixmap(24, 24).toImage()
