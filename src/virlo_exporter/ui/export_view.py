from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from virlo_exporter.export.watchdog import StallWatchdog

STAGE_ICONS = {
    "running": "",
    "complete": "✓",
    "warning": "⚠",
    "failed": "✕",
    "skipped": "⊘",
    "cancelled": "⊘",
}

# (fill, border) colors per visual state, used by StageBlock's custom painting.
BLOCK_PALETTE = {
    "running": ("#12151A", "#3B4655"),
    "complete": ("#12241A", "#2FA66C"),
    "warning": ("#2A2210", "#D69632"),
    "failed": ("#2A1416", "#EF4444"),
    "skipped": ("#15181D", "#3B4655"),
    "cancelled": ("#15181D", "#3B4655"),
}

PROGRESS_COLOR = QColor("#22C55E")


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class StageBlock(QFrame):
    """A single compact stage box in the export snake. Paints its own
    perimeter progress border rather than using a stylesheet border, since
    the border itself carries live progress information."""

    WIDTH = 176
    HEIGHT = 104

    def __init__(self, stage: str, label: str) -> None:
        super().__init__()
        self.stage = stage
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._status = "running"
        self._percent: float | None = None
        self._offset = 0.0
        self._progress_text = ""
        self._watchdog = StallWatchdog()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.timeout.connect(self._check_stall)
        self._watchdog_timer.start(5000)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(3)
        self.title_label = QLabel(label.upper())
        self.title_label.setObjectName("stageBlockTitle")
        self.title_label.setWordWrap(True)
        self.percent_label = QLabel("")
        self.percent_label.setObjectName("stageBlockPercent")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("stageBlockDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addStretch()
        layout.addWidget(self.percent_label)
        layout.addWidget(self.detail_label)

    def _advance(self) -> None:
        self._offset = (self._offset + 0.015) % 1.0
        self.update()

    def apply(self, event: dict[str, Any]) -> None:
        status = str(event.get("status", "running"))
        self._status = status
        if label := event.get("label"):
            self.title_label.setText(str(label).upper())

        if status == "running":
            self._watchdog.record_progress(time.time())
            if not self._watchdog_timer.isActive():
                self._watchdog_timer.start(5000)
            current = event.get("current")
            total = event.get("total")
            message = event.get("message")
            if isinstance(current, int) and isinstance(total, int) and total > 0:
                # `total` can be an early, unreliable estimate: some stages
                # discover more pages as they go (total grows -- current/total
                # would otherwise dip backward) and some estimates start too
                # low (current reaches total before the stage is genuinely
                # done -- a fake premature 100%). Capping below 100% while
                # still running, and never letting the displayed value drop,
                # keeps the bar reading as "still working" and moving forward
                # no matter how `total` itself moves between events.
                raw_percent = min(99.0, current * 100 / total)
                self._percent = max(self._percent or 0.0, raw_percent)
                self.percent_label.setText(f"{self._percent:.0f}%")
                self._progress_text = f"{current:,} / {total:,}"
                self._timer.stop()
            else:
                self._percent = None
                self.percent_label.setText("")
                self._progress_text = f"{current:,} records" if isinstance(current, int) else "Running"
                if not self._timer.isActive():
                    self._timer.start(50)
            if message:
                self._progress_text = (
                    f"{self._progress_text}\n{message}" if self._progress_text else str(message)
                )
            self.detail_label.setText(self._progress_text)
        else:
            self._timer.stop()
            self._watchdog_timer.stop()
            self.percent_label.setText(STAGE_ICONS.get(status, ""))
            summary = event.get("summary")
            self.detail_label.setText(str(summary) if summary else status.replace("_", " ").title())
        self.update()

    def _check_stall(self) -> None:
        if self._status != "running":
            return
        message = self._watchdog.status_message(time.time())
        self.detail_label.setText(message if message else self._progress_text)

    def paintEvent(self, event: Any) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect().adjusted(2, 2, -2, -2))
        fill, border = BLOCK_PALETTE.get(self._status, BLOCK_PALETTE["running"])
        painter.setBrush(QColor(fill))
        border_width = 3.0 if self._status == "running" else 1.5
        painter.setPen(QPen(QColor(border), border_width))
        painter.drawRoundedRect(rect, 10, 10)

        if self._status != "running":
            return
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        total_length = path.length()
        if total_length <= 0:
            return
        pen = QPen(PROGRESS_COLOR, 3.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._percent is not None:
            self._stroke_partial(painter, path, 0.0, self._percent / 100)
        else:
            segment = 0.16
            start = self._offset
            end = start + segment
            if end <= 1.0:
                self._stroke_partial(painter, path, start, end)
            else:
                self._stroke_partial(painter, path, start, 1.0)
                self._stroke_partial(painter, path, 0.0, end - 1.0)

    @staticmethod
    def _stroke_partial(painter: QPainter, path: QPainterPath, t0: float, t1: float) -> None:
        if t1 <= t0:
            return
        samples = max(2, int((t1 - t0) * 90))
        polygon = QPolygonF()
        for index in range(samples + 1):
            t = t0 + (t1 - t0) * index / samples
            polygon.append(path.pointAtPercent(min(1.0, max(0.0, t))))
        painter.drawPolyline(polygon)


class SnakeLayout(QLayout):
    """Lays out fixed-size stage blocks left-to-right, then right-to-left on
    the next row, and so on -- a boustrophedon ("snake") flow so following
    the export's progress reads as one continuous path."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 16) -> None:
        super().__init__(parent)
        self._items: list[Any] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item: Any) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Any:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Any:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> Any:
        return self.minimumSize()

    def minimumSize(self) -> Any:
        from PySide6.QtCore import QSize

        if not self._items:
            return QSize(0, 0)
        item_size = self._items[0].sizeHint()
        margins = self.contentsMargins()
        return QSize(
            item_size.width() + margins.left() + margins.right(),
            item_size.height() + margins.top() + margins.bottom(),
        )

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        area = rect.adjusted(left, top, -right, -bottom)
        spacing = self.spacing()
        if not self._items:
            return top + bottom
        block_size = self._items[0].sizeHint()
        block_w, block_h = block_size.width(), block_size.height()
        columns = max(1, (area.width() + spacing) // (block_w + spacing))

        rows: list[list[Any]] = []
        for index in range(0, len(self._items), columns):
            rows.append(self._items[index : index + columns])

        y = area.y()
        for row_index, row_items in enumerate(rows):
            reversed_row = row_index % 2 == 1
            ordered = list(reversed(row_items)) if reversed_row else row_items
            start_x = (
                area.x() + (columns - len(row_items)) * (block_w + spacing)
                if reversed_row
                else area.x()
            )
            x = start_x
            for item in ordered:
                if not test_only:
                    item.setGeometry(QRect(QPoint(int(x), int(y)), block_size))
                x += block_w + spacing
            y += block_h + spacing
        return int(y - rect.y() + bottom - spacing)


class ExportTimelineWidget(QWidget):
    """Live or replayed export process view: a snake of stage blocks that
    appear one at a time as the export actually reaches them."""

    cancelRequested = Signal()

    def __init__(self, *, live: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._live = live
        self._blocks: dict[str, StageBlock] = {}
        self._order: list[str] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self.title_label = QLabel("")
        self.title_label.setObjectName("title")
        self.subtitle_label = _muted("")
        self.status_row = QHBoxLayout()
        self.status_badge_label = QLabel("")
        self.status_badge_label.setObjectName("statusBadge")
        self.status_badge_label.setProperty("state", "running" if live else "neutral")
        self.elapsed_label = _muted("")
        self.status_row.addWidget(self.status_badge_label)
        self.status_row.addWidget(self.elapsed_label)
        self.status_row.addStretch()
        if live:
            self.cancel_button = QPushButton("Cancel Export")
            self.cancel_button.setObjectName("danger")
            self.cancel_button.clicked.connect(self.cancelRequested.emit)
            self.status_row.addWidget(self.cancel_button)
        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)
        root.addLayout(self.status_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._snake_host = QWidget()
        self._snake_layout = SnakeLayout(self._snake_host)
        scroll.setWidget(self._snake_host)
        root.addWidget(scroll, 1)

        self._failure_panel, self._failure_layout = self._build_failure_panel()
        self._failure_panel.hide()
        root.addWidget(self._failure_panel)

        self._elapsed_timer: QTimer | None = None
        self._elapsed_seconds = 0
        if live:
            self._elapsed_timer = QTimer(self)
            self._elapsed_timer.timeout.connect(self._tick)
            self._elapsed_timer.start(1000)
            self._update_elapsed()

    def _build_failure_panel(self) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        self._failure_summary = _muted("")
        layout.addWidget(self._failure_summary)
        actions = QHBoxLayout()
        self._show_details_button = QPushButton("Show technical details")
        self._show_details_button.clicked.connect(self._toggle_technical)
        self._copy_details_button = QPushButton("Copy error details")
        self._copy_details_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self._technical_text)
        )
        actions.addWidget(self._show_details_button)
        actions.addWidget(self._copy_details_button)
        actions.addStretch()
        layout.addLayout(actions)
        self._technical_view = QTextEdit()
        self._technical_view.setReadOnly(True)
        self._technical_view.setVisible(False)
        self._technical_view.setMinimumHeight(140)
        layout.addWidget(self._technical_view)
        self._technical_text = ""
        return panel, layout

    def _toggle_technical(self) -> None:
        visible = not self._technical_view.isVisible()
        self._technical_view.setVisible(visible)
        self._show_details_button.setText(
            "Hide technical details" if visible else "Show technical details"
        )

    def set_header(self, title: str, subtitle: str) -> None:
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)

    def _tick(self) -> None:
        self._elapsed_seconds += 1
        self._update_elapsed()

    def _update_elapsed(self) -> None:
        minutes, seconds = divmod(self._elapsed_seconds, 60)
        self.elapsed_label.setText(f"Elapsed {minutes:02d}:{seconds:02d}")

    def stop_timer(self) -> None:
        if self._elapsed_timer:
            self._elapsed_timer.stop()

    @property
    def elapsed_seconds(self) -> int:
        return self._elapsed_seconds

    def set_overall_status(self, text: str, state: str) -> None:
        self.status_badge_label.setText(text.upper())
        self.status_badge_label.setProperty("state", state)
        self.status_badge_label.style().unpolish(self.status_badge_label)
        self.status_badge_label.style().polish(self.status_badge_label)
        if hasattr(self, "cancel_button"):
            self.cancel_button.setVisible(state == "running")

    def stage_order(self) -> list[str]:
        """Stages in the order their blocks appeared -- used by tests."""
        return list(self._order)

    def stage_status(self, stage: str) -> str | None:
        block = self._blocks.get(stage)
        return block._status if block else None  # noqa: SLF001 - test/inspection accessor

    def apply_event(self, event: dict[str, Any]) -> None:
        stage = str(event.get("stage"))
        block = self._blocks.get(stage)
        if block is None:
            block = StageBlock(stage, str(event.get("label", stage)))
            self._blocks[stage] = block
            self._order.append(stage)
            self._snake_layout.addWidget(block)
        block.apply(event)

        status = str(event.get("status", "running"))
        if status == "failed":
            self._failure_summary.setText(
                f"{block.title_label.text().title()}: {event.get('summary') or 'This stage failed.'}"
            )
            self._technical_text = str(event.get("detail") or event.get("summary") or "")
            has_detail = bool(event.get("detail"))
            self._show_details_button.setVisible(has_detail)
            self._technical_view.setPlainText(self._technical_text)
            self._failure_panel.show()

    def load_history(self, rows: list[dict[str, Any]]) -> None:
        for record in rows:
            self.apply_event(
                {
                    "stage": record.get("stage"),
                    "label": record.get("label"),
                    "status": record.get("status"),
                    "summary": record.get("summary"),
                    "detail": record.get("detail"),
                }
            )


def format_bytes(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024 or unit == "GB":
            return f"{number:.0f} {unit}" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} GB"


