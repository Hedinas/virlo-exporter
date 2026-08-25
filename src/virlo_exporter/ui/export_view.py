from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

STAGE_ICONS = {
    "pending": "○",
    "running": "▶",
    "complete": "✓",
    "warning": "⚠",
    "failed": "✕",
    "skipped": "⊘",
    "cancelled": "⊘",
}

STAGE_STATE = {
    "pending": "neutral",
    "running": "running",
    "complete": "completed",
    "warning": "warning",
    "failed": "failed",
    "skipped": "neutral",
    "cancelled": "neutral",
}


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class StageRow(QFrame):
    """One row of the live/replayed export timeline."""

    def __init__(self, stage: str, label: str) -> None:
        super().__init__()
        self.stage = stage
        self.setObjectName("stageRow")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 9, 12, 9)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.icon = QLabel(STAGE_ICONS["pending"])
        self.icon.setObjectName("stageIcon")
        self.icon.setProperty("state", "neutral")
        self.title = QLabel(label)
        self.title.setObjectName("stageTitle")
        self.status_text = QLabel("Pending")
        self.status_text.setObjectName("stageStatus")
        self.status_text.setProperty("state", "neutral")
        header.addWidget(self.icon)
        header.addWidget(self.title, 1)
        header.addWidget(self.status_text)
        root.addLayout(header)

        self.detail = QWidget()
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(24, 0, 0, 0)
        detail_layout.setSpacing(4)
        self.message_label = _muted("")
        self.message_label.hide()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        detail_layout.addWidget(self.message_label)
        detail_layout.addWidget(self.progress_bar)

        self.technical_text: str = ""
        actions = QHBoxLayout()
        self.show_details_button = QPushButton("Show technical details")
        self.show_details_button.setVisible(False)
        self.show_details_button.clicked.connect(self._toggle_technical)
        self.copy_details_button = QPushButton("Copy error details")
        self.copy_details_button.setVisible(False)
        self.copy_details_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self.technical_text)
        )
        actions.addWidget(self.show_details_button)
        actions.addWidget(self.copy_details_button)
        actions.addStretch()
        detail_layout.addLayout(actions)
        self.technical_view = QTextEdit()
        self.technical_view.setReadOnly(True)
        self.technical_view.setVisible(False)
        self.technical_view.setMinimumHeight(120)
        detail_layout.addWidget(self.technical_view)

        root.addWidget(self.detail)
        self.set_expanded(False)

    def _toggle_technical(self) -> None:
        visible = not self.technical_view.isVisible()
        self.technical_view.setVisible(visible)
        self.show_details_button.setText("Hide technical details" if visible else "Show technical details")

    def set_expanded(self, expanded: bool) -> None:
        self.detail.setVisible(expanded)

    def apply(self, event: dict[str, Any]) -> None:
        status = str(event.get("status", "pending"))
        state = STAGE_STATE.get(status, "neutral")
        self.icon.setText(STAGE_ICONS.get(status, "○"))
        self.icon.setProperty("state", state)
        self.icon.style().unpolish(self.icon)
        self.icon.style().polish(self.icon)
        self.status_text.setText(status.replace("_", " ").upper())
        self.status_text.setProperty("state", state)
        self.status_text.style().unpolish(self.status_text)
        self.status_text.style().polish(self.status_text)
        if label := event.get("label"):
            self.title.setText(str(label))

        if status == "running":
            current = event.get("current")
            total = event.get("total")
            message = event.get("message")
            text_parts = []
            if isinstance(current, int) and isinstance(total, int) and total > 0:
                text_parts.append(f"{current:,} / {total:,}")
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(min(current, total))
            elif isinstance(current, int):
                text_parts.append(f"{current:,} records downloaded")
                self.progress_bar.setRange(0, 0)
            else:
                self.progress_bar.setRange(0, 0)
            if message:
                text_parts.append(str(message))
            self.message_label.setText("   ·   ".join(text_parts))
            self.message_label.setVisible(bool(text_parts))
            self.progress_bar.setVisible(True)
            self.show_details_button.setVisible(False)
            self.copy_details_button.setVisible(False)
            self.set_expanded(True)
        elif status == "failed":
            summary = event.get("summary") or "This stage failed."
            self.message_label.setText(str(summary))
            self.message_label.setVisible(True)
            self.progress_bar.setVisible(False)
            detail = event.get("detail")
            self.technical_text = str(detail or summary)
            has_detail = bool(detail)
            self.show_details_button.setVisible(has_detail)
            self.copy_details_button.setVisible(True)
            self.technical_view.setPlainText(self.technical_text)
            self.set_expanded(True)
        elif status == "warning":
            summary = event.get("summary") or "Completed with a warning."
            self.message_label.setText(str(summary))
            self.message_label.setVisible(True)
            self.progress_bar.setVisible(False)
            self.show_details_button.setVisible(False)
            self.copy_details_button.setVisible(False)
            self.set_expanded(False)
        elif status in {"complete", "skipped", "cancelled"}:
            summary = event.get("summary")
            self.message_label.setText(str(summary) if summary else "")
            self.message_label.setVisible(bool(summary))
            self.progress_bar.setVisible(False)
            self.show_details_button.setVisible(False)
            self.copy_details_button.setVisible(False)
            self.set_expanded(False)
        else:
            self.set_expanded(False)


class ExportTimelineWidget(QWidget):
    """Live or replayed stage-by-stage export timeline."""

    cancelRequested = Signal()

    def __init__(self, *, live: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._live = live
        self._rows: dict[str, StageRow] = {}
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
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setSpacing(6)
        self._body_layout.addStretch()
        scroll.setWidget(self._body)
        root.addWidget(scroll, 1)

        self._elapsed_timer: QTimer | None = None
        self._elapsed_seconds = 0
        if live:
            self._elapsed_timer = QTimer(self)
            self._elapsed_timer.timeout.connect(self._tick)
            self._elapsed_timer.start(1000)
            self._update_elapsed()

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

    def set_overall_status(self, text: str, state: str) -> None:
        self.status_badge_label.setText(text.upper())
        self.status_badge_label.setProperty("state", state)
        self.status_badge_label.style().unpolish(self.status_badge_label)
        self.status_badge_label.style().polish(self.status_badge_label)
        if hasattr(self, "cancel_button"):
            self.cancel_button.setVisible(state == "running")

    def apply_event(self, event: dict[str, Any]) -> None:
        stage = str(event.get("stage"))
        row = self._rows.get(stage)
        if row is None:
            row = StageRow(stage, str(event.get("label", stage)))
            self._rows[stage] = row
            self._order.append(stage)
            self._body_layout.insertWidget(self._body_layout.count() - 1, row)
        if event.get("status") == "running":
            for other_stage, other_row in self._rows.items():
                if other_stage != stage:
                    other_row.set_expanded(False)
        row.apply(event)

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


def build_completion_summary(
    *, status_text: str, state: str, stats: dict[str, Any], warnings: list[str]
) -> QFrame:
    from .main_window import card, metric_card, section_label  # local import avoids a cycle

    frame, layout = card()
    layout.addWidget(section_label("Export result"))
    badge = QLabel(status_text.upper())
    badge.setObjectName("statusBadge")
    badge.setProperty("state", state)
    layout.addWidget(badge)

    def size(value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "—"
        for unit in ("B", "KB", "MB", "GB"):
            if number < 1024 or unit == "GB":
                return f"{number:.0f} {unit}" if unit == "B" else f"{number:.1f} {unit}"
            number /= 1024
        return f"{number:.1f} GB"

    metrics_row = QHBoxLayout()
    metrics_row.setSpacing(10)
    for label_text, value_text in (
        ("RAW Data", size(stats.get("raw_bytes"))),
        ("AI Dataset", size(stats.get("dataset_bytes"))),
        ("Raw Videos", f"{stats.get('videos', 0):,}"),
        ("High-signal Videos", f"{stats.get('high_signal', 0):,}"),
        ("Baseline Videos", f"{stats.get('baseline', 0):,}"),
        ("Warnings", str(len(warnings))),
        ("Paid API Calls", str(stats.get("paid_api_calls", 0))),
    ):
        metrics_row.addWidget(metric_card(label_text, value_text))
    layout.addLayout(metrics_row)
    if warnings:
        warning_box, warning_layout = card()
        warning_layout.addWidget(section_label("Warnings"))
        for message in warnings:
            warning_layout.addWidget(_muted(f"⚠ {message}"))
        layout.addWidget(warning_box)
    return frame
