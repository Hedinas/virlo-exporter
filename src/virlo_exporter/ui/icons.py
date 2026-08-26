"""A small set of hand-drawn line icons, all sharing the same stroke
width/weight/size/padding -- used instead of mixing Unicode glyphs and
emoji (pencil, gear, folder emoji, ...), which render with inconsistent
weight and color depending on the system font/emoji substitution and
don't respect the app's theme color at all.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

SIZE = 18
STROKE_WIDTH = 1.6
NORMAL_COLOR = "#B7BEC9"
ACTIVE_COLOR = "#DCE9FF"


def _pixmap(size: int, color: str) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), STROKE_WIDTH)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    return pixmap, painter


def _icon(draw, size: int = SIZE) -> QIcon:
    icon = QIcon()
    for mode, color in ((QIcon.Mode.Normal, NORMAL_COLOR), (QIcon.Mode.Active, ACTIVE_COLOR)):
        pixmap, painter = _pixmap(size, color)
        draw(painter, size)
        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon


def _pencil(painter: QPainter, size: int) -> None:
    # Diagonal shaft from the writing tip (bottom-left) to the eraser end
    # (top-right), a small V mark at the tip, and a ferrule cross-line.
    x0, y0 = size * 0.22, size * 0.82
    x1, y1 = size * 0.78, size * 0.26
    painter.drawLine(int(x0), int(y0), int(x1), int(y1))
    painter.drawLine(int(x0), int(y0), int(x0 + size * 0.12), int(y0 - size * 0.02))
    painter.drawLine(int(x0), int(y0), int(x0 + size * 0.02), int(y0 - size * 0.12))
    dx, dy = x1 - x0, y1 - y0
    length = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    cx, cy = x1 - ux * size * 0.14, y1 - uy * size * 0.14
    half = size * 0.07
    painter.drawLine(
        int(cx - px * half), int(cy - py * half), int(cx + px * half), int(cy + py * half)
    )


def _gear(painter: QPainter, size: int) -> None:
    center = size / 2
    radius = size * 0.24
    painter.drawEllipse(QRectF(center - radius, center - radius, radius * 2, radius * 2))
    painter.drawEllipse(QRectF(center - 1.6, center - 1.6, 3.2, 3.2))
    # Eight short, thick teeth blocks around the ring -- reads clearly as a
    # gear/settings cog rather than a sun/burst of thin radiating lines.
    tooth_pen = QPen(painter.pen())
    tooth_pen.setWidthF(STROKE_WIDTH * 1.8)
    painter.setPen(tooth_pen)
    for angle_deg in range(0, 360, 45):
        angle = math.radians(angle_deg)
        x0 = center + radius * 1.05 * math.cos(angle)
        y0 = center + radius * 1.05 * math.sin(angle)
        x1 = center + radius * 1.42 * math.cos(angle)
        y1 = center + radius * 1.42 * math.sin(angle)
        painter.drawLine(int(x0), int(y0), int(x1), int(y1))


def _copy(painter: QPainter, size: int) -> None:
    # Two slightly overlapping outline sheets/rectangles.
    back = QRectF(size * 0.32, size * 0.16, size * 0.52, size * 0.56)
    front = QRectF(size * 0.16, size * 0.32, size * 0.52, size * 0.56)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(back, 2, 2)
    painter.drawRoundedRect(front, 2, 2)


def _folder(painter: QPainter, size: int) -> None:
    # A body rectangle with a smaller tab notched into its top-left corner
    # -- plain rectangle edges read more clearly at small sizes than a
    # single elaborate polygon path.
    left, top, right, bottom = size * 0.14, size * 0.34, size * 0.86, size * 0.78
    tab_right = size * 0.46
    tab_top = size * 0.22
    path = QPainterPath()
    path.moveTo(left, bottom)
    path.lineTo(left, tab_top)
    path.lineTo(tab_right, tab_top)
    path.lineTo(tab_right + size * 0.08, top)
    path.lineTo(right, top)
    path.lineTo(right, bottom)
    path.closeSubpath()
    painter.drawPath(path)


def _workflow(painter: QPainter, size: int) -> None:
    # Three small filled node blocks connected by lines -- reads as a
    # workflow/timeline, not a media Play triangle.
    points = [
        (size * 0.2, size * 0.76),
        (size * 0.5, size * 0.28),
        (size * 0.8, size * 0.76),
    ]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        painter.drawLine(int(x0), int(y0), int(x1), int(y1))
    node_r = size * 0.11
    painter.setBrush(painter.pen().color())
    for x, y in points:
        painter.drawEllipse(QRectF(x - node_r, y - node_r, node_r * 2, node_r * 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _document(painter: QPainter, size: int) -> None:
    rect = QRectF(size * 0.24, size * 0.14, size * 0.52, size * 0.72)
    path = QPainterPath()
    fold = size * 0.14
    path.moveTo(rect.left(), rect.top())
    path.lineTo(rect.right() - fold, rect.top())
    path.lineTo(rect.right(), rect.top() + fold)
    path.lineTo(rect.right(), rect.bottom())
    path.lineTo(rect.left(), rect.bottom())
    path.closeSubpath()
    painter.drawPath(path)
    for i in range(3):
        y = rect.top() + fold + i * size * 0.14
        painter.drawLine(int(rect.left() + 4), int(y), int(rect.right() - 4), int(y))


def _trash(painter: QPainter, size: int) -> None:
    top, bottom = size * 0.28, size * 0.82
    left, right = size * 0.26, size * 0.74
    painter.drawLine(int(size * 0.18), int(top), int(size * 0.82), int(top))
    painter.drawLine(int(left), int(top), int(left), int(bottom))
    painter.drawLine(int(right), int(top), int(right), int(bottom))
    painter.drawLine(int(left), int(bottom), int(right), int(bottom))
    painter.drawLine(int(size * 0.38), int(size * 0.28), int(size * 0.38), int(size * 0.16))
    painter.drawLine(int(size * 0.62), int(size * 0.28), int(size * 0.62), int(size * 0.16))
    painter.drawLine(int(size * 0.38), int(size * 0.16), int(size * 0.62), int(size * 0.16))
    for x in (0.4, 0.5, 0.6):
        painter.drawLine(int(size * x), int(top + 3), int(size * x), int(bottom - 3))


def _warning(painter: QPainter, size: int) -> None:
    path = QPainterPath()
    path.moveTo(size * 0.5, size * 0.14)
    path.lineTo(size * 0.88, size * 0.82)
    path.lineTo(size * 0.12, size * 0.82)
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawLine(int(size * 0.5), int(size * 0.38), int(size * 0.5), int(size * 0.6))
    painter.drawEllipse(QRectF(size * 0.5 - 1.4, size * 0.68, 2.8, 2.8))


_DRAWERS = {
    "pencil": _pencil,
    "gear": _gear,
    "copy": _copy,
    "folder": _folder,
    "workflow": _workflow,
    "document": _document,
    "trash": _trash,
    "warning": _warning,
}


def icon(name: str, size: int = SIZE) -> QIcon:
    return _icon(_DRAWERS[name], size)
