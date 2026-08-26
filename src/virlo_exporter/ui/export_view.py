from __future__ import annotations

import re
import time
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
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
    "cancelled": "⏸",
}

# (fill, border) colors per visual state, used by StageBlock's custom painting.
# "cancelled" (user-facing: Interrupted) gets its own amber/yellow -- distinct
# from warning's orange -- never reusing another state's color.
BLOCK_PALETTE = {
    "running": ("#12151A", "#3B4655"),
    "complete": ("#12241A", "#2FA66C"),
    "warning": ("#2A2210", "#D69632"),
    "failed": ("#2A1416", "#EF4444"),
    "skipped": ("#15181D", "#3B4655"),
    "cancelled": ("#2A2712", "#D6C632"),
}

# Status-box text/state per terminal status -- the single place a stage's
# outcome is shown, replacing the old separately-placed checkmark/icon.
STATUS_BOX_TEXT = {
    "complete": "✓",
    "warning": "!",
    "failed": "×",
    "skipped": "⊘",
    "cancelled": "⏸",
}
STATUS_BOX_STATE = {
    "complete": "complete",
    "warning": "warning",
    "failed": "failed",
    "skipped": "neutral",
    "cancelled": "cancelled",
}
STATUS_BOX_TOOLTIP = {
    "complete": "Complete",
    "skipped": "Skipped",
    "cancelled": "Interrupted by user",
}

SPINNER_FRAMES = ["◜", "◠", "◝", "◞", "◡", "◟"]

PROGRESS_COLOR = QColor("#22C55E")

# How many pages make up one visual chunk of a long paginated stage (e.g.
# Videos). Purely a display grouping -- backend retrieval is unchanged and
# never fetches or waits differently because of this constant.
PAGES_PER_CHUNK = 20

_PAGE_COUNT_PATTERN = re.compile(r"(\d+)\s+page\(s\)")


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def stroke_partial_path(painter: QPainter, path: QPainterPath, t0: float, t1: float) -> None:
    """Stroke the [t0, t1] fraction of `path`'s perimeter. Shared by
    StageBlock's progress border and the sidebar's Active Process perimeter
    animation so both read as the same visual language."""
    if t1 <= t0:
        return
    samples = max(2, int((t1 - t0) * 90))
    polygon = QPolygonF()
    for index in range(samples + 1):
        t = t0 + (t1 - t0) * index / samples
        polygon.append(path.pointAtPercent(min(1.0, max(0.0, t))))
    painter.drawPolyline(polygon)


def stroke_indeterminate_segment(
    painter: QPainter, path: QPainterPath, offset: float, segment: float = 0.16
) -> None:
    """Draw a single moving segment along `path`'s perimeter at `offset`,
    wrapping around the start when it would run past the end."""
    start = offset
    end = start + segment
    if end <= 1.0:
        stroke_partial_path(painter, path, start, end)
    else:
        stroke_partial_path(painter, path, start, 1.0)
        stroke_partial_path(painter, path, 0.0, end - 1.0)


class ClickableStatusBox(QLabel):
    """The corner status box becomes clickable only for states that have
    something worth explaining (warning/interrupted/failed) -- set via
    set_clickable() rather than always-on, so it doesn't invite clicks on a
    plain running percent or a clean completion."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self._clickable = False

    def set_clickable(self, clickable: bool) -> None:
        self._clickable = clickable
        self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event: Any) -> None:
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class StageBlock(QFrame):
    """A single compact stage box in the export snake. Paints its own
    perimeter progress border rather than using a stylesheet border, since
    the border itself carries live progress information. A small square
    status box floats over the bottom-right corner -- the single place a
    percent, spinner, checkmark, warning, or failure icon is ever shown."""

    WIDTH = 176
    HEIGHT = 104
    STATUS_BOX_SIZE = 26
    STATUS_BOX_MARGIN = 8
    CLICKABLE_STATES = {"warning", "cancelled", "failed"}

    diagnosticsRequested = Signal(str)

    def __init__(self, stage: str, label: str, *, page_range: tuple[int, int] | None = None) -> None:
        super().__init__()
        self.stage = stage
        self.page_range = page_range
        self._last_event: dict[str, Any] = {}
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._status = "running"
        self._percent: float | None = None
        self._offset = 0.0
        self._spinner_frame = 0
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
        layout.addWidget(self.title_label)
        self.range_label = QLabel("")
        self.range_label.setObjectName("stageBlockRange")
        self.range_label.setVisible(False)
        layout.addWidget(self.range_label)
        if page_range is not None:
            self.set_page_range(page_range)
        layout.addStretch()
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("stageBlockDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setContentsMargins(0, 0, self.STATUS_BOX_SIZE + 4, 0)
        layout.addWidget(self.detail_label)

        self.status_box = ClickableStatusBox(self)
        self.status_box.setObjectName("stageStatusBox")
        self.status_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_box.setProperty("state", "running")
        self.status_box.clicked.connect(lambda: self.diagnosticsRequested.emit(self.stage))
        self.status_box.setGeometry(
            self.WIDTH - self.STATUS_BOX_MARGIN - self.STATUS_BOX_SIZE,
            self.HEIGHT - self.STATUS_BOX_MARGIN - self.STATUS_BOX_SIZE,
            self.STATUS_BOX_SIZE,
            self.STATUS_BOX_SIZE,
        )
        self.status_box.raise_()

    def set_title(self, label: str) -> None:
        self.title_label.setText(label.upper())

    def set_page_range(self, page_range: tuple[int, int] | None) -> None:
        """A block can start out unchunked (its first event is always a
        page-less "running" transition, before pagination has reported a
        page number) and only later turn out to be page 1 of a chunk --
        this lets the timeline retarget it once that's known, rather than
        needing to know upfront whether a stage will end up chunked."""
        self.page_range = page_range
        if page_range is not None:
            self.range_label.setText(f"Pages {page_range[0]}–{page_range[1]}")
            self.range_label.setVisible(True)
        else:
            self.range_label.setVisible(False)

    def _advance(self) -> None:
        self._offset = (self._offset + 0.015) % 1.0
        if self._percent is None:
            self._spinner_frame = (self._spinner_frame + 1) % len(SPINNER_FRAMES)
            self.status_box.setText(SPINNER_FRAMES[self._spinner_frame])
        self.update()

    def _chunk_percent(self, page: int) -> float | None:
        if self.page_range is None:
            return None
        start, end = self.page_range
        span = max(1, end - start + 1)
        within = max(1, min(page - start + 1, span))
        return min(99.0, within * 100 / span)

    def apply(self, event: dict[str, Any]) -> None:
        status = str(event.get("status", "running"))
        self._status = status
        self._last_event = dict(event)
        if label := event.get("label"):
            self.title_label.setText(str(label).upper())

        if status == "running":
            self._watchdog.record_progress(time.time())
            if not self._watchdog_timer.isActive():
                self._watchdog_timer.start(5000)
            current = event.get("current")
            total = event.get("total")
            page = event.get("page")
            message = event.get("message")
            chunk_percent = self._chunk_percent(page) if isinstance(page, int) else None
            if chunk_percent is not None:
                # A chunk's own percent tracks its position within its own
                # page range -- the stage's overall current/total (record
                # counts for the *whole* resource) would be identical across
                # every chunk block and wouldn't mean "this chunk is done".
                self._percent = max(self._percent or 0.0, chunk_percent)
                self._progress_text = f"Page {page}"
                if isinstance(current, int):
                    self._progress_text = f"{self._progress_text} · {current:,} records"
            elif isinstance(current, int) and isinstance(total, int) and total > 0:
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
                self._progress_text = f"{current:,} / {total:,}"
            else:
                self._percent = None
                self._progress_text = f"{current:,} records" if isinstance(current, int) else "Running"
            if self._percent is not None:
                self._timer.stop()
            elif not self._timer.isActive():
                self._timer.start(50)
            if message and chunk_percent is None:
                self._progress_text = (
                    f"{self._progress_text}\n{message}" if self._progress_text else str(message)
                )
            self.detail_label.setText(self._progress_text)
        else:
            self._timer.stop()
            self._watchdog_timer.stop()
            summary = event.get("summary")
            self.detail_label.setText(str(summary) if summary else status.replace("_", " ").title())
        self._update_status_box()
        self.update()

    def _status_box_tooltip(self) -> str:
        if self._status == "running":
            return "Running"
        if self._status in self.CLICKABLE_STATES:
            return "Diagnostics"
        return STATUS_BOX_TOOLTIP.get(self._status, self._status.replace("_", " ").title())

    def _update_status_box(self) -> None:
        if self._status == "running":
            state = "running"
            text = f"{self._percent:.0f}%" if self._percent is not None else SPINNER_FRAMES[self._spinner_frame]
        else:
            state = STATUS_BOX_STATE.get(self._status, "neutral")
            text = STATUS_BOX_TEXT.get(self._status, STAGE_ICONS.get(self._status, ""))
        self.status_box.setText(text)
        self.status_box.setProperty("state", state)
        self.status_box.setToolTip(self._status_box_tooltip())
        self.status_box.set_clickable(self._status in self.CLICKABLE_STATES)
        self.status_box.style().unpolish(self.status_box)
        self.status_box.style().polish(self.status_box)

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
        if path.length() <= 0:
            return
        pen = QPen(PROGRESS_COLOR, 3.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._percent is not None:
            stroke_partial_path(painter, path, 0.0, self._percent / 100)
        else:
            stroke_indeterminate_segment(painter, path, self._offset)


class SnakeLayout(QLayout):
    """Lays out fixed-size stage blocks left-to-right, then right-to-left on
    the next row, and so on -- a boustrophedon ("snake") flow so following
    the export's progress reads as one continuous path."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 16) -> None:
        super().__init__(parent)
        self._items: list[Any] = []
        self._last_rows: list[list[QWidget]] = []
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
        if not self._items:
            return QSize(0, 0)
        item_size = self._items[0].sizeHint()
        margins = self.contentsMargins()
        return QSize(
            item_size.width() + margins.left() + margins.right(),
            item_size.height() + margins.top() + margins.bottom(),
        )

    def rows_in_display_order(self) -> list[list[QWidget]]:
        """The blocks grouped into rows, in the exact left-to-right order
        they were actually placed on screen (already reversed for odd
        rows) -- used by SnakeCanvas to draw connector arrows between
        geometrically (and sequentially) adjacent blocks."""
        return self._last_rows

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        area = rect.adjusted(left, top, -right, -bottom)
        spacing = self.spacing()
        if not self._items:
            if not test_only:
                self._last_rows = []
            return top + bottom
        block_size = self._items[0].sizeHint()
        block_w, block_h = block_size.width(), block_size.height()
        columns = max(1, (area.width() + spacing) // (block_w + spacing))

        rows: list[list[Any]] = []
        for index in range(0, len(self._items), columns):
            rows.append(self._items[index : index + columns])

        y = area.y()
        display_rows: list[list[QWidget]] = []
        for row_index, row_items in enumerate(rows):
            reversed_row = row_index % 2 == 1
            ordered = list(reversed(row_items)) if reversed_row else row_items
            start_x = (
                area.x() + (columns - len(row_items)) * (block_w + spacing)
                if reversed_row
                else area.x()
            )
            x = start_x
            display_row: list[QWidget] = []
            for item in ordered:
                if not test_only:
                    item.setGeometry(QRect(QPoint(int(x), int(y)), block_size))
                display_row.append(item.widget())
                x += block_w + spacing
            display_rows.append(display_row)
            y += block_h + spacing
        if not test_only:
            self._last_rows = display_rows
        return int(y - rect.y() + bottom - spacing)


CONNECTOR_COLOR = QColor("#4B5563")


def _draw_horizontal_arrowhead(painter: QPainter, x: int, y: int, *, pointing_right: bool) -> None:
    size = 4
    if pointing_right:
        points = [QPointF(x, y), QPointF(x - size * 2, y - size), QPointF(x - size * 2, y + size)]
    else:
        points = [QPointF(x, y), QPointF(x + size * 2, y - size), QPointF(x + size * 2, y + size)]
    painter.drawPolygon(QPolygonF(points))


def _draw_down_arrowhead(painter: QPainter, x: int, y: int) -> None:
    size = 4
    points = [QPointF(x, y), QPointF(x - size, y - size * 2), QPointF(x + size, y - size * 2)]
    painter.drawPolygon(QPolygonF(points))


class SnakeCanvas(QWidget):
    """Hosts the SnakeLayout and paints light connector arrows between
    consecutive stage blocks, in sequence order -- drawn in the canvas's
    own paintEvent, which Qt runs before it paints the child blocks on top,
    so the arrows never sit over any block's text."""

    def __init__(self, snake_layout: SnakeLayout) -> None:
        super().__init__()
        self.setLayout(snake_layout)
        self._snake_layout = snake_layout

    @staticmethod
    def _sequence_first(display_row: list[QWidget], reversed_row: bool) -> QWidget:
        return display_row[-1] if reversed_row else display_row[0]

    @staticmethod
    def _sequence_last(display_row: list[QWidget], reversed_row: bool) -> QWidget:
        return display_row[0] if reversed_row else display_row[-1]

    def paintEvent(self, event: Any) -> None:  # noqa: ARG002
        rows = self._snake_layout.rows_in_display_order()
        if not rows:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        line_pen = QPen(CONNECTOR_COLOR, 1.6)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        for row_index, row in enumerate(rows):
            reversed_row = row_index % 2 == 1
            for left_widget, right_widget in zip(row, row[1:], strict=False):
                a_rect, b_rect = left_widget.geometry(), right_widget.geometry()
                y = a_rect.center().y()
                x0, x1 = a_rect.right(), b_rect.left()
                if x1 <= x0:
                    continue
                arrow_len = 10
                painter.setPen(line_pen)
                painter.setBrush(CONNECTOR_COLOR)
                if reversed_row:
                    painter.drawLine(x0 + arrow_len, y, x1, y)
                    _draw_horizontal_arrowhead(painter, x0, y, pointing_right=False)
                else:
                    painter.drawLine(x0, y, x1 - arrow_len, y)
                    _draw_horizontal_arrowhead(painter, x1, y, pointing_right=True)

            if row_index + 1 >= len(rows) or not row or not rows[row_index + 1]:
                continue
            next_row = rows[row_index + 1]
            next_reversed = (row_index + 1) % 2 == 1
            from_widget = self._sequence_last(row, reversed_row)
            to_widget = self._sequence_first(next_row, next_reversed)
            from_rect, to_rect = from_widget.geometry(), to_widget.geometry()
            x0, y0 = from_rect.center().x(), from_rect.bottom()
            x1, y1 = to_rect.center().x(), to_rect.top()
            arrow_len = 8
            painter.setPen(line_pen)
            painter.setBrush(CONNECTOR_COLOR)
            if x0 == x1:
                painter.drawLine(x0, y0, x1, y1 - arrow_len)
            else:
                mid_y = (y0 + y1) // 2
                painter.drawLine(x0, y0, x0, mid_y)
                painter.drawLine(x0, mid_y, x1, mid_y)
                painter.drawLine(x1, mid_y, x1, y1 - arrow_len)
            _draw_down_arrowhead(painter, x1, y1)


class ExportTimelineWidget(QWidget):
    """Live or replayed export process view: a snake of stage blocks that
    appear one at a time as the export actually reaches them."""

    cancelRequested = Signal()
    diagnosticsRequested = Signal(dict)

    def __init__(self, *, live: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._live = live
        self._blocks: dict[str, StageBlock] = {}
        self._order: list[str] = []
        self._split_stages: set[str] = set()
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
        self._snake_layout = SnakeLayout()
        self._snake_host = SnakeCanvas(self._snake_layout)
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

    def mark_cancelling(self) -> None:
        """Called synchronously the instant Cancel is clicked -- the actual
        worker thread may take a moment longer to notice cancel_event and
        unwind, but the user must never wait for that to see a reaction.
        Disables the button (a second click is now impossible), stops
        whichever stage is currently running, and freezes it into the
        Interrupted state immediately."""
        if hasattr(self, "cancel_button"):
            self.cancel_button.setEnabled(False)
        for block in self._blocks.values():
            if block._status == "running":  # noqa: SLF001
                block.apply(
                    {
                        "stage": block.stage,
                        "label": block.title_label.text(),
                        "status": "cancelled",
                        "summary": "Interrupted by user",
                    }
                )
        self.set_overall_status("Interrupted", "cancelled")

    def _on_stage_diagnostics_requested(self, stage: str) -> None:
        block = self._blocks.get(stage)
        if block is not None:
            self.diagnosticsRequested.emit(dict(block._last_event))  # noqa: SLF001

    def stage_order(self) -> list[str]:
        """Stages/chunks in the order their blocks appeared -- used by
        tests. A chunked stage contributes one entry per chunk key
        (e.g. "videos:1", "videos:2")."""
        return list(self._order)

    def _chunk_keys_for(self, stage: str) -> list[str]:
        return [key for key in self._order if key == stage or key.startswith(f"{stage}:")]

    def stage_status(self, stage: str) -> str | None:
        keys = self._chunk_keys_for(stage)
        block = self._blocks.get(keys[-1]) if keys else None
        return block._status if block else None  # noqa: SLF001 - test/inspection accessor

    def _page_range_for_chunk(self, chunk: int) -> tuple[int, int]:
        start = (chunk - 1) * PAGES_PER_CHUNK + 1
        return start, chunk * PAGES_PER_CHUNK

    def _rekey_block(self, old_key: str, new_key: str) -> None:
        block = self._blocks.pop(old_key)
        self._blocks[new_key] = block
        self._order[self._order.index(old_key)] = new_key
        block.stage = new_key

    def _running_block_key_and_label(self, stage: str, label: str, page: int | None) -> tuple[str, str, tuple[int, int] | None]:
        if page is None:
            return stage, label, None
        chunk = (page - 1) // PAGES_PER_CHUNK + 1
        key = f"{stage}:{chunk}"
        if key not in self._blocks:
            if chunk == 1 and stage in self._blocks:
                # A paginated stage's very first event is always the
                # page-less "running" transition (pagination hasn't reported
                # a page number yet) -- adopt that existing block as chunk 1
                # instead of creating a second, duplicate block.
                self._rekey_block(stage, key)
                self._blocks[key].set_page_range(self._page_range_for_chunk(1))
            elif chunk > 1:
                # A new chunk starting means the previous one is done -- by
                # construction its PAGES_PER_CHUNK pages were already
                # consumed. Future chunks are never pre-created; this is the
                # only place a new chunk key is minted, and only once its
                # first page starts.
                previous_block = self._blocks.get(f"{stage}:{chunk - 1}")
                if previous_block is not None and previous_block._status == "running":  # noqa: SLF001
                    previous_block.apply({"status": "complete"})
                if stage not in self._split_stages:
                    self._split_stages.add(stage)
                    if previous_block is not None:
                        previous_block.set_title(f"{label} 1")
        display_label = f"{label} {chunk}" if stage in self._split_stages else label
        page_range = self._page_range_for_chunk(chunk)
        return key, display_label, page_range

    def apply_event(self, event: dict[str, Any]) -> None:
        stage = str(event.get("stage"))
        label = str(event.get("label", stage))
        status = str(event.get("status", "running"))
        page = event.get("page") if status == "running" and isinstance(event.get("page"), int) else None

        if status == "running":
            key, display_label, page_range = self._running_block_key_and_label(stage, label, page)
        else:
            # A terminal event always names the whole (possibly chunked)
            # resource, never a specific chunk -- route it to whichever
            # chunk is currently the latest for this stage.
            existing = self._chunk_keys_for(stage)
            key = existing[-1] if existing else stage
            page_range = self._blocks[key].page_range if key in self._blocks else None
            if stage in self._split_stages and ":" in key:
                display_label = f"{label} {key.rsplit(':', 1)[1]}"
            else:
                display_label = label

        block = self._blocks.get(key)
        if block is None:
            block = StageBlock(key, display_label, page_range=page_range)
            block.diagnosticsRequested.connect(self._on_stage_diagnostics_requested)
            self._blocks[key] = block
            self._order.append(key)
            self._snake_layout.addWidget(block)
        # The block re-derives its own title from event["label"] on every
        # apply() -- pass the chunk-numbered label through so "VIDEOS 2"
        # doesn't get silently overwritten back to plain "VIDEOS".
        block.apply({**event, "page": page, "label": display_label})

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
            stage = record.get("stage")
            label = record.get("label")
            summary = record.get("summary") or ""
            match = _PAGE_COUNT_PATTERN.search(summary)
            page_count = int(match.group(1)) if match else None
            if page_count and page_count > PAGES_PER_CHUNK:
                # Page-level progress is never persisted (it's UI-only, and
                # export_stages only stores stage start/finish rows), but the
                # finished page count survives inside the plain "N page(s)"
                # summary text -- reconstruct every chunk this stage would
                # have passed through (each already complete) from that,
                # rather than replaying the live process.
                total_chunks = (page_count - 1) // PAGES_PER_CHUNK + 1
                for chunk in range(1, total_chunks + 1):
                    self.apply_event(
                        {
                            "stage": stage,
                            "label": label,
                            "status": "running",
                            "page": min(chunk * PAGES_PER_CHUNK, page_count),
                        }
                    )
            self.apply_event(
                {
                    "stage": stage,
                    "label": label,
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


