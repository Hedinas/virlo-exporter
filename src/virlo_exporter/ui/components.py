from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from PySide6.QtCore import QPoint, QRect, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QResizeEvent, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from virlo_exporter.api.billing import BillingSafety
from virlo_exporter.models import Agent

from .logic import (
    INTENT_LIMIT,
    INTENT_NEAR_LIMIT,
    KEYWORD_LIMIT,
    KEYWORD_NEAR_LIMIT,
    add_keyword,
    clamp_intent,
    counter_state,
)
from .theme import install_dark_title_bar


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _visible_on_screen(widget: QWidget) -> bool:
    frame = widget.frameGeometry()
    return any(screen.availableGeometry().intersects(frame) for screen in widget.screen().virtualSiblings())


def ensure_visible(widget: QWidget) -> None:
    if _visible_on_screen(widget):
        return
    screen = widget.screen() or widget.windowHandle().screen()
    available = screen.availableGeometry()
    frame = widget.frameGeometry()
    frame.moveCenter(available.center())
    widget.move(frame.topLeft())


class PersistentDialog(QDialog):
    def __init__(self, settings_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings_key = settings_key
        self._ui_settings = QSettings()
        install_dark_title_bar(self)

    def restore_saved_geometry(self, fallback: QSize) -> None:
        saved = self._ui_settings.value(self._settings_key)
        if saved is not None and self.restoreGeometry(saved):
            ensure_visible(self)
        else:
            self.resize(fallback)

    def _save_geometry(self) -> None:
        self._ui_settings.setValue(self._settings_key, self.saveGeometry())

    def done(self, result: int) -> None:
        self._save_geometry()
        super().done(result)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_geometry()
        super().closeEvent(event)


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, margin: int = 0, spacing: int = 7) -> None:
        super().__init__(parent)
        self._items: list[Any] = []
        self.setContentsMargins(margin, margin, margin, margin)
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
        return self._layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _layout(self, rect: QRect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        area = rect.adjusted(left, top, -right, -bottom)
        x = area.x()
        y = area.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > area.right() and line_height > 0:
                x = area.x()
                y += line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + bottom


class LimitedTextEdit(QTextEdit):
    lengthChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setMinimumHeight(160)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textChanged.connect(self._enforce_limit)

    def _enforce_limit(self) -> None:
        value = self.toPlainText()
        if len(value) > INTENT_LIMIT:
            cursor_position = min(self.textCursor().position(), INTENT_LIMIT)
            self.blockSignals(True)
            self.setPlainText(clamp_intent(value))
            cursor = self.textCursor()
            cursor.setPosition(cursor_position, QTextCursor.MoveMode.MoveAnchor)
            self.setTextCursor(cursor)
            self.blockSignals(False)
            value = self.toPlainText()
        self.lengthChanged.emit(len(value))


class IntentField(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("intentField")
        self.setProperty("limitState", "normal")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 7)
        layout.setSpacing(2)
        self.editor = LimitedTextEdit()
        self.editor.setPlaceholderText(
            "Describe the content, audience, use case, and anything Virlo should exclude…"
        )
        layout.addWidget(self.editor)
        footer = QHBoxLayout()
        footer.setContentsMargins(9, 0, 9, 0)
        self.error = QLabel("Intent is required.")
        self.error.setObjectName("validationError")
        self.error.hide()
        self.counter = QLabel(f"0 / {INTENT_LIMIT}")
        self.counter.setObjectName("limitCounter")
        footer.addWidget(self.error)
        footer.addStretch()
        footer.addWidget(self.counter)
        layout.addLayout(footer)
        self.editor.lengthChanged.connect(self._update_state)

    def text(self) -> str:
        return self.editor.toPlainText()

    def set_text(self, value: str) -> None:
        self.editor.setPlainText(clamp_intent(value))
        self._update_state(len(self.text()))

    def validate(self) -> bool:
        valid = bool(self.text().strip())
        self.error.setVisible(not valid)
        self.setProperty(
            "limitState",
            "error"
            if not valid
            else counter_state(len(self.text()), near=INTENT_NEAR_LIMIT, maximum=INTENT_LIMIT),
        )
        _repolish(self)
        return valid

    def _update_state(self, count: int) -> None:
        self.error.hide()
        state = counter_state(count, near=INTENT_NEAR_LIMIT, maximum=INTENT_LIMIT)
        self.setProperty("limitState", state)
        self.counter.setProperty("limitState", state)
        self.counter.setText(f"{count} / {INTENT_LIMIT}")
        _repolish(self)
        _repolish(self.counter)


class KeywordEditor(QFrame):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("keywordEditor")
        self.setProperty("limitState", "normal")
        self._values: list[str] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self.chip_host = QWidget()
        self.chip_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.flow = FlowLayout(self.chip_host)
        root.addWidget(self.chip_host)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Type a keyword and press Enter")
        self.entry.returnPressed.connect(self._add_entry)
        root.addWidget(self.entry)
        bottom = QHBoxLayout()
        self.message = QLabel("Maximum 50 keywords reached.")
        self.message.setObjectName("warning")
        self.message.hide()
        self.counter = QLabel(f"0 / {KEYWORD_LIMIT}")
        self.counter.setObjectName("limitCounter")
        bottom.addWidget(self.message)
        bottom.addStretch()
        bottom.addWidget(self.counter)
        root.addLayout(bottom)
        self._refresh()

    def keywords(self) -> list[str]:
        return list(self._values)

    def set_keywords(self, values: Iterable[str]) -> None:
        unique: list[str] = []
        for raw in values:
            value = str(raw).strip()
            if value and value not in unique and len(unique) < KEYWORD_LIMIT:
                unique.append(value)
        self._values = unique
        self._refresh()
        self.changed.emit()

    def _add_entry(self) -> None:
        values, result = add_keyword(self._values, self.entry.text())
        if result == "added":
            self._values = values
            self.entry.clear()
            self._refresh()
            self.changed.emit()
        elif result == "limit":
            self.message.show()
        elif result == "duplicate":
            self.entry.selectAll()

    def _remove(self, value: str) -> None:
        self._values.remove(value)
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        while self.flow.count():
            item = self.flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        for value in self._values:
            chip = QToolButton()
            chip.setObjectName("keywordChip")
            chip.setText(f"{value}  ×")
            chip.setToolTip(f"Remove {value}")
            chip.clicked.connect(lambda _checked=False, keyword=value: self._remove(keyword))
            self.flow.addWidget(chip)
        count = len(self._values)
        state = counter_state(count, near=KEYWORD_NEAR_LIMIT, maximum=KEYWORD_LIMIT)
        self.setProperty("limitState", state)
        self.counter.setProperty("limitState", state)
        self.counter.setText(f"{count} / {KEYWORD_LIMIT}")
        self.message.setVisible(count >= KEYWORD_LIMIT)
        self.entry.setEnabled(count < KEYWORD_LIMIT)
        _repolish(self)
        _repolish(self.counter)
        self.chip_host.updateGeometry()
        self.updateGeometry()
        QTimer.singleShot(0, self._update_chip_height)

    def _update_chip_height(self) -> None:
        width = max(180, self.chip_host.width())
        self.chip_host.setFixedHeight(max(1, self.flow.heightForWidth(width)))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._update_chip_height)


class ToggleRow(QFrame):
    toggled = Signal(bool)

    def __init__(self, label: str, caption: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toggleRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(QLabel(label))
        if caption:
            secondary = QLabel(caption)
            secondary.setObjectName("muted")
            text.addWidget(secondary)
        self.switch = QToolButton()
        self.switch.setObjectName("switch")
        self.switch.setCheckable(True)
        self.switch.toggled.connect(self._changed)
        layout.addLayout(text, 1)
        layout.addWidget(self.switch)
        self._changed(False)

    def isChecked(self) -> bool:
        return self.switch.isChecked()

    def setChecked(self, checked: bool) -> None:
        self.switch.setChecked(checked)
        self._changed(checked)

    def _changed(self, checked: bool) -> None:
        self.switch.setText("ON" if checked else "OFF")
        self.toggled.emit(checked)


class CollapsibleSection(QFrame):
    expandedChanged = Signal(bool)

    def __init__(self, title: str, action: QPushButton | None = None) -> None:
        super().__init__()
        self.setObjectName("sidebarSection")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)
        header = QHBoxLayout()
        header.setSpacing(5)
        self.chevron = QToolButton()
        self.chevron.setObjectName("chevron")
        self.chevron.setCheckable(True)
        self.chevron.setChecked(True)
        self.chevron.clicked.connect(self.set_expanded)
        title_button = QToolButton()
        title_button.setObjectName("sectionTitle")
        title_button.setText(title)
        title_button.clicked.connect(lambda: self.set_expanded(not self.is_expanded()))
        header.addWidget(self.chevron)
        header.addWidget(title_button)
        header.addStretch()
        if action:
            action.setObjectName("toolbarAction")
            header.addWidget(action)
        root.addLayout(header)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        root.addWidget(self.body)
        self.set_expanded(True)

    def is_expanded(self) -> bool:
        return self.body.isVisibleTo(self) if self.isVisible() else self.chevron.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.chevron.setChecked(expanded)
        self.chevron.setText("⌄" if expanded else "›")
        self.body.setVisible(expanded)
        self.expandedChanged.emit(expanded)


class AgentEditorDialog(PersistentDialog):
    suggestRequested = Signal(object)

    def __init__(self, agent: Agent | None = None, parent: QWidget | None = None) -> None:
        key = "ui/dialogs/edit_agent_geometry" if agent else "ui/dialogs/new_agent_geometry"
        super().__init__(key, parent)
        self.agent = agent
        self._payload: dict[str, Any] | None = None
        self.setWindowTitle("Edit Agent" if agent else "New Agent")
        self.setMinimumSize(600, 520)
        root = QVBoxLayout(self)
        title = QLabel("Edit Agent" if agent else "New Agent")
        title.setObjectName("title")
        root.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        form = QVBoxLayout(body)
        form.setContentsMargins(4, 6, 12, 8)
        form.setSpacing(13)
        form.addWidget(_section_heading("Agent name"))
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. 3D Collectibles")
        form.addWidget(self.name)
        form.addWidget(_section_heading("Intent"))
        self.intent = IntentField()
        form.addWidget(self.intent)
        keyword_header = QHBoxLayout()
        keyword_header.addWidget(_section_heading("Keywords"))
        keyword_header.addStretch()
        self.suggest = QPushButton("Suggest Keywords · Free")
        self.suggest.clicked.connect(self._suggest)
        keyword_header.addWidget(self.suggest)
        form.addLayout(keyword_header)
        self.keywords = KeywordEditor()
        form.addWidget(self.keywords)
        form.addWidget(_section_heading("Platforms"))
        platform_row = QHBoxLayout()
        self.platforms: dict[str, QToolButton] = {}
        for key_name, text in (
            ("tiktok", "TikTok"),
            ("instagram", "Instagram"),
            ("youtube", "YouTube"),
        ):
            button = QToolButton()
            button.setObjectName("platformPill")
            button.setText(text)
            button.setCheckable(True)
            button.setChecked(True)
            self.platforms[key_name] = button
            platform_row.addWidget(button)
        platform_row.addStretch()
        form.addLayout(platform_row)
        self.meta_ads = ToggleRow("Meta Ads", "Included")
        self.data_intelligence = ToggleRow(
            "Data Intelligence", f"+${BillingSafety.DATA_INTELLIGENCE_ADDON:.2f} / research"
        )
        self.english = ToggleRow("English only")
        self.data_intelligence.toggled.connect(self._update_cost)
        form.addWidget(self.meta_ads)
        form.addWidget(self.data_intelligence)
        form.addWidget(self.english)
        if not agent:
            form.addWidget(_section_heading("Agent type"))
            type_row = QHBoxLayout()
            self.one_time = _choice_button("One-time")
            self.recurring = _choice_button("Recurring")
            group = QButtonGroup(self)
            group.setExclusive(True)
            group.addButton(self.one_time)
            group.addButton(self.recurring)
            self.one_time.setChecked(True)
            self.recurring.toggled.connect(self._type_changed)
            type_row.addWidget(self.one_time)
            type_row.addWidget(self.recurring)
            type_row.addStretch()
            form.addLayout(type_row)
        else:
            self.one_time = _choice_button("One-time")
            self.recurring = _choice_button("Recurring")
            self.recurring.setChecked(agent.is_recurring)
            self.one_time.setChecked(not agent.is_recurring)
        self.cadence = QComboBox()
        self.cadence.addItems(["weekly", "daily", "monthly"])
        self.cadence.setVisible(bool(agent and agent.is_recurring))
        form.addWidget(self.cadence)
        cost_card = QFrame()
        cost_card.setObjectName("costCard")
        cost = QVBoxLayout(cost_card)
        cost.addWidget(_section_heading("Cost per new research"))
        self.base_cost = _cost_row("Base Research", BillingSafety.BASE_AGENT_RUN)
        self.intelligence_cost = _cost_row(
            "Data Intelligence", BillingSafety.DATA_INTELLIGENCE_ADDON
        )
        self.total_cost = _cost_row("Estimated Total", BillingSafety.BASE_AGENT_RUN)
        cost.addLayout(self.base_cost)
        cost.addLayout(self.intelligence_cost)
        cost.addWidget(_muted("Meta Ads · Included"))
        divider = QFrame()
        divider.setObjectName("divider")
        cost.addWidget(divider)
        cost.addLayout(self.total_cost)
        if agent:
            info = QLabel(
                "Editing is free. Paid options apply only to future research; completed research is unchanged."
            )
            info.setObjectName("infoBox")
            info.setWordWrap(True)
            cost.addWidget(info)
        form.addWidget(cost_card)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText("Save Agent" if agent else "Create Agent")
        save.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._load_agent(agent)
        self._update_cost()
        self.restore_saved_geometry(QSize(720, 760))

    def _load_agent(self, agent: Agent | None) -> None:
        if not agent:
            self.meta_ads.setChecked(True)
            self.data_intelligence.setChecked(True)
            self.english.setChecked(True)
            return
        self.name.setText(agent.name)
        self.intent.set_text(agent.intent)
        self.keywords.set_keywords(agent.keywords)
        for name, button in self.platforms.items():
            button.setChecked(name in agent.platforms)
        self.meta_ads.setChecked(agent.meta_ads_enabled)
        self.data_intelligence.setChecked(agent.data_intelligence_enabled)
        self.english.setChecked(agent.english_only)
        self.cadence.setCurrentText(agent.cadence or "weekly")

    def _type_changed(self, recurring: bool) -> None:
        self.cadence.setVisible(recurring)

    def _suggest(self) -> None:
        if not self.intent.validate():
            return
        self.suggestRequested.emit(
            {
                "intent": self.intent.text().strip(),
                "topic_hint": self.name.text().strip(),
                "platforms": self._platform_values(),
                "desired_count": 10,
            }
        )

    def apply_suggestion(self, data: dict[str, Any]) -> None:
        self.keywords.set_keywords(list(data.get("keywords") or []))

    def set_suggest_enabled(self, enabled: bool) -> None:
        self.suggest.setEnabled(enabled)

    def _platform_values(self) -> list[str]:
        return [name for name, button in self.platforms.items() if button.isChecked()]

    def _update_cost(self, _checked: bool | None = None) -> None:
        estimate = BillingSafety.estimate_agent(
            data_intelligence=self.data_intelligence.isChecked()
        )
        self.intelligence_cost.itemAt(2).widget().setText(f"+${estimate.data_intelligence:.2f}")
        self.total_cost.itemAt(2).widget().setText(f"${estimate.total:.2f}")

    def payload(self) -> dict[str, Any]:
        return dict(self._payload or {})

    def accept(self) -> None:
        errors: list[str] = []
        if not self.intent.validate():
            errors.append("Intent is required.")
        if not self.keywords.keywords():
            errors.append("Add at least one keyword.")
        if not self._platform_values():
            errors.append("Select at least one platform.")
        if errors:
            QMessageBox.warning(self, "Check Agent settings", "\n".join(errors))
            return
        payload: dict[str, Any] = {
            "intent": self.intent.text().strip(),
            "keywords": self.keywords.keywords(),
            "platforms": self._platform_values(),
            "name": self.name.text().strip(),
            "meta_ads_enabled": self.meta_ads.isChecked(),
            "data_intelligence_enabled": self.data_intelligence.isChecked(),
            "english_only": self.english.isChecked(),
        }
        if not self.agent:
            payload["is_recurring"] = self.recurring.isChecked()
        if self.recurring.isChecked():
            payload["cadence"] = self.cadence.currentText()
        if not payload["name"]:
            payload.pop("name")
        self._payload = payload
        super().accept()


class NewResearchDialog(PersistentDialog):
    def __init__(
        self,
        agents: Iterable[Agent],
        parent: QWidget | None = None,
        *,
        selected_agent_id: str | None = None,
    ) -> None:
        super().__init__("ui/dialogs/new_research_geometry", parent)
        self.setWindowTitle("New Research")
        self.setMinimumSize(470, 440)
        self._agents = {agent.id: agent for agent in agents}
        layout = QVBoxLayout(self)
        title = QLabel("New Research")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(_muted("Choose an Agent configuration to run again."))
        layout.addWidget(_section_heading("Choose Agent"))
        self.agent_combo = QComboBox()
        for agent in sorted(self._agents.values(), key=lambda item: item.name.casefold()):
            self.agent_combo.addItem(agent.name, agent.id)
        if selected_agent_id:
            index = self.agent_combo.findData(selected_agent_id)
            if index >= 0:
                self.agent_combo.setCurrentIndex(index)
        layout.addWidget(self.agent_combo)
        self.data_intelligence = ToggleRow(
            "Data Intelligence", f"+${BillingSafety.DATA_INTELLIGENCE_ADDON:.2f} / research"
        )
        self.meta_ads = ToggleRow("Meta Ads", "Included")
        layout.addWidget(self.data_intelligence)
        layout.addWidget(self.meta_ads)
        cost = QFrame()
        cost.setObjectName("costCard")
        cost_layout = QVBoxLayout(cost)
        cost_layout.addWidget(_section_heading("Estimated cost"))
        cost_layout.addLayout(_cost_row("Base Research", BillingSafety.BASE_AGENT_RUN))
        self.intelligence_cost = _cost_row(
            "Data Intelligence", BillingSafety.DATA_INTELLIGENCE_ADDON
        )
        cost_layout.addLayout(self.intelligence_cost)
        divider = QFrame()
        divider.setObjectName("divider")
        cost_layout.addWidget(divider)
        self.total_cost = _cost_row("Estimated Total", BillingSafety.BASE_AGENT_RUN)
        cost_layout.addLayout(self.total_cost)
        layout.addWidget(cost)
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        run = buttons.addButton("Run Research", QDialogButtonBox.ButtonRole.AcceptRole)
        run.setObjectName("primary")
        run.setEnabled(bool(self._agents))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.agent_combo.currentIndexChanged.connect(self._agent_changed)
        self.data_intelligence.toggled.connect(self._update_cost)
        self._agent_changed()
        self.restore_saved_geometry(QSize(520, 540))

    def selected_agent(self) -> Agent | None:
        return self._agents.get(str(self.agent_combo.currentData()))

    def payload(self) -> dict[str, Any]:
        agent = self.selected_agent()
        if not agent:
            return {}
        return {
            "is_recurring": False,
            "intent": agent.intent,
            "keywords": list(agent.keywords),
            "platforms": list(agent.platforms),
            "name": f"{agent.name} — new research",
            "meta_ads_enabled": self.meta_ads.isChecked(),
            "data_intelligence_enabled": self.data_intelligence.isChecked(),
            "english_only": agent.english_only,
        }

    def _agent_changed(self, _index: int | None = None) -> None:
        agent = self.selected_agent()
        if agent:
            self.data_intelligence.setChecked(agent.data_intelligence_enabled)
            self.meta_ads.setChecked(agent.meta_ads_enabled)
        self._update_cost()

    def _update_cost(self, _checked: bool | None = None) -> None:
        estimate = BillingSafety.estimate_agent(
            data_intelligence=self.data_intelligence.isChecked()
        )
        self.intelligence_cost.itemAt(2).widget().setText(f"+${estimate.data_intelligence:.2f}")
        self.total_cost.itemAt(2).widget().setText(f"${estimate.total:.2f}")


class RenameDialog(PersistentDialog):
    def __init__(
        self, title: str, current_name: str, parent: QWidget | None = None, *, context: str = ""
    ) -> None:
        super().__init__("ui/dialogs/rename_geometry", parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        if context:
            layout.addWidget(_muted(context))
        self.name_edit = QLineEdit(current_name)
        self.name_edit.selectAll()
        layout.addWidget(self.name_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.restore_saved_geometry(QSize(430, 170))

    def value(self) -> str:
        return self.name_edit.text().strip()

    def accept(self) -> None:
        if not self.value():
            QMessageBox.warning(self, "Name required", "Enter a non-empty name.")
            return
        super().accept()


def _section_heading(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("eyebrow")
    return label


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def _choice_button(text: str) -> QToolButton:
    button = QToolButton()
    button.setObjectName("platformPill")
    button.setText(text)
    button.setCheckable(True)
    return button


def _cost_row(label: str, amount: float) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(QLabel(label))
    row.addStretch()
    value = QLabel(f"${amount:.2f}")
    value.setObjectName("costValue")
    row.addWidget(value)
    return row
