from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from virlo_exporter.api.billing import PriceEstimate
from virlo_exporter.config import AppSettings

from .components import PersistentDialog


class ApiKeyDialog(PersistentDialog):
    def __init__(self, parent: QWidget | None = None, *, existing: bool = False) -> None:
        super().__init__("ui/dialogs/api_key_geometry", parent)
        self.setWindowTitle("Connect Virlo")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        title = QLabel("CONNECT VIRLO" if not existing else "REPLACE VIRLO API KEY")
        title.setObjectName("title")
        help_text = QLabel(
            "Paste the API key from dev.virlo.ai/dashboard. It will be stored in Windows Credential Manager."
        )
        help_text.setWordWrap(True)
        help_text.setObjectName("subtitle")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("virlo_tkn_…")
        self.show_key = QCheckBox("Show key")
        self.show_key.toggled.connect(
            lambda visible: self.key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
            )
        )
        self.validation_error = QLabel("Virlo API keys begin with virlo_tkn_.")
        self.validation_error.setObjectName("validationError")
        self.validation_error.hide()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(title)
        layout.addWidget(help_text)
        layout.addSpacing(8)
        layout.addWidget(self.key_edit)
        layout.addWidget(self.show_key)
        layout.addWidget(self.validation_error)
        layout.addWidget(buttons)
        self.restore_saved_geometry(self.minimumSizeHint())

    def api_key(self) -> str:
        return self.key_edit.text().strip()

    def accept(self) -> None:
        if not self.api_key().startswith("virlo_tkn_"):
            self.validation_error.show()
            self.key_edit.setFocus()
            return
        super().accept()


class PaidConfirmationDialog(PersistentDialog):
    def __init__(
        self,
        estimate: PriceEstimate,
        balance: float | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("ui/dialogs/paid_confirmation_geometry", parent)
        self.setWindowTitle("Confirm paid research")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        title = QLabel("START VIRLO RESEARCH")
        title.setObjectName("title")
        layout.addWidget(title)
        form = QFormLayout()
        form.addRow("Base research", QLabel(f"${estimate.base:.2f}"))
        form.addRow("Data Intelligence", QLabel(f"${estimate.data_intelligence:.2f}"))
        form.addRow("Meta Ads", QLabel("Included"))
        total = QLabel(f"${estimate.total:.2f}")
        total.setStyleSheet("font-weight: 700")
        form.addRow("Estimated total", total)
        form.addRow(
            "Current balance", QLabel("Unavailable" if balance is None else f"${balance:.2f}")
        )
        if balance is not None:
            form.addRow("Balance after run", QLabel(f"${balance - estimate.total:.2f}"))
        layout.addLayout(form)
        note = QLabel(
            "Virlo charges recurring research per scheduled run, including the first. Reads and exports are free."
        )
        note.setWordWrap(True)
        note.setObjectName("subtitle")
        layout.addWidget(note)
        buttons = QDialogButtonBox()
        run = buttons.addButton(
            f"RUN — ${estimate.total:.2f}", QDialogButtonBox.ButtonRole.AcceptRole
        )
        run.setObjectName("primary")
        buttons.addButton("CANCEL", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.restore_saved_geometry(self.minimumSizeHint())


class SettingsDialog(PersistentDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__("ui/dialogs/settings_geometry", parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(520, 300)
        self._settings = settings
        layout = QVBoxLayout(self)
        title = QLabel("SETTINGS")
        title.setObjectName("title")
        layout.addWidget(title)
        form = QFormLayout()
        folder_row = QHBoxLayout()
        self.folder = QLineEdit(settings.export_folder)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        form.addRow("Export folder", folder_row)
        self.open_after = QCheckBox("Open folder after export")
        self.open_after.setChecked(settings.open_folder_after_export)
        form.addRow("", self.open_after)
        self.baseline = QSpinBox()
        self.baseline.setRange(0, 1000)
        self.baseline.setValue(settings.baseline_sample_size)
        form.addRow("Baseline sample size", self.baseline)
        refresh = QLabel("Auto — 15s while active, 60s while idle")
        refresh.setObjectName("muted")
        form.addRow("Refresh interval", refresh)
        self.replace_key = QCheckBox("Replace Virlo API key after saving")
        form.addRow("API connection", self.replace_key)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.restore_saved_geometry(self.minimumSizeHint())

    def _browse(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "Choose export folder", self.folder.text())
        if value:
            self.folder.setText(value)

    def apply_to(self, settings: AppSettings) -> None:
        settings.export_folder = str(Path(self.folder.text()).expanduser())
        settings.open_folder_after_export = self.open_after.isChecked()
        settings.baseline_sample_size = self.baseline.value()

    def should_replace_key(self) -> bool:
        return self.replace_key.isChecked()


class ErrorDialog(PersistentDialog):
    def __init__(
        self,
        title: str,
        message: str,
        technical: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("ui/dialogs/error_geometry", parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        heading = QLabel("ERROR")
        heading.setObjectName("error")
        heading.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(heading)
        summary = QLabel(message or "An unexpected error occurred.")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText(technical)
        self.details.setMinimumHeight(190)
        self.details.setVisible(False)
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.toggle = QPushButton("Show Details")
        self.toggle.setVisible(bool(technical))
        self.toggle.clicked.connect(self._toggle_details)
        copy = QPushButton("Copy Details")
        copy.setVisible(bool(technical))
        copy.clicked.connect(lambda: QApplication.clipboard().setText(technical))
        ok = QPushButton("OK")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        actions.addWidget(self.toggle)
        actions.addWidget(copy)
        actions.addStretch()
        actions.addWidget(ok)
        layout.addLayout(actions)
        self.restore_saved_geometry(self.minimumSizeHint())

    def _toggle_details(self) -> None:
        visible = not self.details.isVisible()
        self.details.setVisible(visible)
        self.toggle.setText("Hide Details" if visible else "Show Details")
        self.adjustSize()


def show_error(parent: QWidget, title: str, message: str, technical: str = "") -> None:
    ErrorDialog(title, message, technical, parent).exec()


class ExportDiagnosticsDialog(PersistentDialog):
    """Dark, safe-technical-detail view of one export's warnings/errors,
    surfaced from a click on a stage block or a failed/warning status
    badge. The primary next step it offers is always the full report."""

    openReportRequested = Signal()

    def __init__(
        self,
        export_number: int,
        errors: list[dict[str, object]],
        warnings: list[dict[str, object]],
        notices: list[dict[str, object]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("ui/dialogs/export_diagnostics_geometry", parent)
        self.setWindowTitle(f"Export #{export_number:03d} diagnostics")
        self.setMinimumSize(480, 300)
        layout = QVBoxLayout(self)
        title = QLabel(f"EXPORT #{export_number:03d}")
        title.setObjectName("title")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(120)
        scroll.setMaximumHeight(330)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        for heading, entries in (("Errors", errors), ("Warnings", warnings), ("Notices", notices)):
            if not entries:
                continue
            section = QLabel(f"{heading.upper()} ({len(entries)})")
            section.setObjectName("eyebrow")
            body_layout.addWidget(section)
            for entry in entries:
                body_layout.addWidget(self._entry_row(entry))
        if not (errors or warnings or notices):
            empty = QLabel("No warnings, errors, or notices for this export.")
            empty.setObjectName("muted")
            body_layout.addWidget(empty)
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        actions = QHBoxLayout()
        open_report = QPushButton("Report")
        open_report.setObjectName("primary")
        open_report.clicked.connect(self.openReportRequested.emit)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions.addWidget(open_report)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)
        entry_count = len(errors) + len(warnings) + len(notices)
        target_height = 330 + max(0, min(entry_count, 3) - 1) * 65
        self.restore_saved_geometry(QSize(560, target_height))
        if entry_count <= 3 and self.height() > target_height:
            self.resize(self.width(), target_height)

    @staticmethod
    def _entry_row(entry: dict[str, object]) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        row = QVBoxLayout(frame)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(2)
        for key in ("stage", "resource", "endpoint", "http_status", "error_code", "message"):
            value = entry.get(key)
            if value in (None, ""):
                continue
            field = QLabel(f"{key.replace('_', ' ').title()}: {value}")
            field.setWordWrap(True)
            field.setObjectName("bodyText" if key == "message" else "muted")
            row.addWidget(field)
        return frame


class StageDiagnosticsDialog(PersistentDialog):
    """Compact per-stage diagnostics, opened by clicking a warning/
    interrupted/failed status box in the live or historical snake view --
    a human-readable reason plus a safe technical-details block the user
    can copy and hand to an AI assistant without leaking credentials."""

    openReportRequested = Signal()

    HEADINGS = {"warning": "WARNING", "cancelled": "INTERRUPTED", "failed": "FAILED"}

    def __init__(self, event: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__("ui/dialogs/stage_diagnostics_geometry", parent)
        from virlo_exporter.export.report import redact_secrets

        status = str(event.get("status", ""))
        self.setWindowTitle(self.HEADINGS.get(status, status.upper() or "Diagnostics"))
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)

        title = QLabel(self.HEADINGS.get(status, status.upper() or "DIAGNOSTICS"))
        title.setObjectName("title")
        layout.addWidget(title)

        stage = str(event.get("stage") or "")
        label = str(event.get("label") or stage.split(":", 1)[0].replace("_", " ").title())
        layout.addWidget(QLabel(f"Stage: {label}"))
        page = event.get("page")
        if isinstance(page, int):
            layout.addWidget(QLabel(f"Page: {page}"))

        reason_heading = QLabel("REASON")
        reason_heading.setObjectName("eyebrow")
        layout.addWidget(reason_heading)
        reason_text = redact_secrets(str(event.get("summary") or "No summary available."))
        reason_label = QLabel(reason_text)
        reason_label.setWordWrap(True)
        reason_label.setObjectName("bodyText")
        layout.addWidget(reason_label)

        detail = event.get("detail")
        technical_lines = [f"status: {status}", f"stage: {stage}"]
        if isinstance(page, int):
            technical_lines.append(f"page: {page}")
        for key in ("current", "total"):
            if event.get(key) is not None:
                technical_lines.append(f"{key}: {event[key]}")
        if detail:
            technical_lines.append(f"detail: {redact_secrets(str(detail))}")
        self._technical_text = redact_secrets("\n".join(technical_lines))

        technical_heading = QLabel("TECHNICAL DETAILS")
        technical_heading.setObjectName("eyebrow")
        layout.addWidget(technical_heading)
        technical_view = QTextEdit()
        technical_view.setReadOnly(True)
        technical_view.setPlainText(self._technical_text)
        technical_view.setMinimumHeight(110)
        layout.addWidget(technical_view)

        actions = QHBoxLayout()
        copy_button = QPushButton("Copy Details")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self._technical_text)
        )
        report_button = QPushButton("Report")
        report_button.clicked.connect(self.openReportRequested.emit)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        actions.addWidget(copy_button)
        actions.addWidget(report_button)
        actions.addStretch()
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self.restore_saved_geometry(QSize(480, 380))
