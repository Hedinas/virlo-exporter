from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
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
        layout.addWidget(buttons)
        self.restore_saved_geometry(self.minimumSizeHint())

    def api_key(self) -> str:
        return self.key_edit.text().strip()

    def accept(self) -> None:
        if not self.api_key().startswith("virlo_tkn_"):
            QMessageBox.warning(self, "Invalid API key", "Virlo API keys begin with virlo_tkn_.")
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
