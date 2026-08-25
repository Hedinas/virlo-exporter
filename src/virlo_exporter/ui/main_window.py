from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any

from PySide6.QtCore import QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from virlo_exporter.api.billing import BillingSafety
from virlo_exporter.api.client import VirloClient
from virlo_exporter.api.errors import (
    AuthenticationError,
    MalformedResponseError,
    NetworkError,
    PaginationError,
    VirloError,
)
from virlo_exporter.config import AppSettings, SettingsStore
from virlo_exporter.export import report as export_report
from virlo_exporter.export.engine import ExportEngine, ExportResult
from virlo_exporter.models import Agent, Run
from virlo_exporter.services.workers import Worker
from virlo_exporter.storage.database import Database
from virlo_exporter.storage.key_store import ApiKeyStore
from virlo_exporter.utils.files import open_in_explorer, reveal_in_explorer

from .components import (
    AgentEditorDialog,
    CollapsibleSection,
    NewResearchDialog,
    RenameDialog,
    ensure_visible,
)
from .dialogs import ApiKeyDialog, PaidConfirmationDialog, SettingsDialog, show_error
from .export_view import ExportTimelineWidget, build_completion_summary, format_bytes
from .logic import agent_display_status, research_search_text, run_timestamp

logger = logging.getLogger(__name__)

RECENT_RESEARCH_LIMIT = 12


def human_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        return parsed.strftime("%b %d, %Y · %I:%M %p")
    except ValueError:
        return value


def compact_date(value: str | None) -> str:
    if not value:
        return "Date unavailable"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        return parsed.strftime("%b %d · %I:%M %p")
    except ValueError:
        return value


def section_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("eyebrow")
    return label


def card_heading(text: str) -> QLabel:
    """Level-1 heading for a card's own title (e.g. AGENT CONFIGURATION)."""
    label = QLabel(text.upper())
    label.setObjectName("cardHeading")
    return label


def micro_label(text: str) -> QLabel:
    """Level-3 heading for mini-card/metric-card internal titles."""
    label = QLabel(text.upper())
    label.setObjectName("microLabel")
    return label


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    return frame, layout


def pill(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("platformBadge")
    return label


def mini_card(label_text: str, value_text: str, state: str = "neutral") -> QFrame:
    frame = QFrame()
    frame.setObjectName("miniCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(4)
    layout.addWidget(micro_label(label_text))
    value = QLabel(value_text)
    value.setObjectName("miniCardValue")
    value.setProperty("state", state)
    layout.addWidget(value)
    return frame


def status_badge(text: str, state: str = "neutral") -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("statusBadge")
    label.setProperty("state", state)
    return label


class ClickableStatusBadge(QLabel):
    clicked = Signal()

    def __init__(self, text: str, state: str = "neutral") -> None:
        super().__init__(text.upper())
        self.setObjectName("statusBadge")
        self.setProperty("state", state)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: Any) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


RUN_STATUS_STATE = {
    "completed": "completed",
    "partial_failure": "warning",
    "running": "running",
    "pending": "running",
    "processing": "running",
    "failed": "failed",
}


def metric_card(label_text: str, value_text: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("metricCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 11, 14, 11)
    layout.setSpacing(3)
    layout.addWidget(micro_label(label_text))
    value = QLabel(value_text)
    value.setObjectName("metricValue")
    layout.addWidget(value)
    return frame


class NaturalListWidget(QListWidget):
    def __init__(self, parent: QWidget | None = None, *, max_height: int | None = None) -> None:
        super().__init__(parent)
        self._max_height = max_height
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if max_height is None
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSpacing(2)
        self.setMinimumHeight(34)

    def sync_height(self) -> None:
        height = 2 * self.frameWidth() + 6
        for index in range(self.count()):
            if not self.item(index).isHidden():
                height += max(36, self.sizeHintForRow(index)) + self.spacing()
        height = max(34, height)
        if self._max_height is not None:
            height = min(height, self._max_height)
        self.setFixedHeight(height)
        self.verticalScrollBar().setValue(0)
        # sizeHintForRow() can return a stale/incorrect value the first time
        # this runs, before the widget (or an ancestor CollapsibleSection)
        # has ever been shown. Re-measure once the event loop settles so
        # expand/collapse doesn't leave a wrong fixed height behind.
        QTimer.singleShot(0, self._resync_once_shown)

    def _resync_once_shown(self) -> None:
        height = 2 * self.frameWidth() + 6
        for index in range(self.count()):
            if not self.item(index).isHidden():
                height += max(36, self.sizeHintForRow(index)) + self.spacing()
        height = max(34, height)
        if self._max_height is not None:
            height = min(height, self._max_height)
        if height != self.height():
            self.setFixedHeight(height)


class AgentRow(QFrame):
    def __init__(self, agent: Agent, status: str, on_edit: Any, on_rename: Any) -> None:
        super().__init__()
        self.setObjectName("sidebarRow")
        self.setProperty("selected", False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 5, 7)
        layout.setSpacing(2)
        text = QVBoxLayout()
        text.setSpacing(1)
        name = QLabel(agent.name)
        name.setObjectName("rowTitle")
        name.setToolTip(agent.name)
        secondary = QLabel(
            f"{'Recurring' if agent.is_recurring else 'One-time'} · {status}"
        )
        secondary.setObjectName("muted")
        text.addWidget(name)
        text.addWidget(secondary)
        pencil = QToolButton()
        pencil.setObjectName("pencilButton")
        pencil.setText("✎")
        pencil.setToolTip(f"Rename {agent.name}")
        pencil.clicked.connect(on_rename)
        gear = QToolButton()
        gear.setObjectName("gearButton")
        gear.setText("⚙")
        gear.setToolTip(f"Edit {agent.name}")
        gear.clicked.connect(on_edit)
        layout.addLayout(text, 1)
        layout.addWidget(pencil)
        layout.addWidget(gear)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)


class ResearchRow(QFrame):
    def __init__(self, title_text: str, secondary_text: str, on_rename: Any) -> None:
        super().__init__()
        self.setObjectName("sidebarRow")
        self.setProperty("selected", False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 5, 7)
        layout.setSpacing(2)
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(title_text)
        title.setObjectName("rowTitle")
        title.setToolTip(title_text)
        secondary = QLabel(secondary_text)
        secondary.setObjectName("muted")
        text.addWidget(title)
        text.addWidget(secondary)
        pencil = QToolButton()
        pencil.setObjectName("pencilButton")
        pencil.setText("✎")
        pencil.setToolTip("Rename research")
        pencil.clicked.connect(on_rename)
        layout.addLayout(text, 1)
        layout.addWidget(pencil)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)


class ProcessRow(QFrame):
    def __init__(self, title_text: str, secondary_text: str) -> None:
        super().__init__()
        self.setObjectName("sidebarRow")
        self.setProperty("selected", False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(1)
        title = QLabel(f"● {title_text}")
        title.setObjectName("rowTitle")
        title.setToolTip(title_text)
        secondary = QLabel(secondary_text)
        secondary.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(secondary)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings_store: SettingsStore,
        settings: AppSettings,
        key_store: ApiKeyStore,
        database: Database,
    ) -> None:
        super().__init__()
        self.settings_store = settings_store
        self.settings = settings
        self.key_store = key_store
        self.database = database
        self.ui_settings = QSettings()
        self.client: VirloClient | None = None
        self.agents: dict[str, Agent] = {}
        self.runs: dict[str, list[Run]] = {}
        self.selected_agent_id: str | None = None
        self._current_page: tuple[Any, ...] = ("empty",)
        self.active_workers: set[Worker] = set()
        self.export_cancel: Event | None = None
        # Event log per running/finished export process_id, kept independent
        # of whatever page is currently on screen so navigating away and
        # back (or a background refresh) never loses live progress.
        self._live_export_events: dict[str, list[dict[str, Any]]] = {}
        self._active_export_timeline: ExportTimelineWidget | None = None
        self._active_export_process_id: str | None = None
        self._runs_loading = False
        self.setWindowTitle("Virlo Exporter")
        self.setMinimumSize(940, 620)
        self._build_ui()
        self._restore_ui_state()

        key = self.key_store.get()
        if key:
            self._set_client(key)
            QTimer.singleShot(50, self.refresh)
        else:
            self._load_cached_agents()
            QTimer.singleShot(100, self.connect_api)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(60000)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(64)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 0, 18, 0)
        brand = QLabel("Virlo Exporter")
        brand.setObjectName("brand")
        self.balance_label = QLabel("Balance unavailable")
        self.connection_label = QLabel("● Not connected")
        self.connection_label.setObjectName("muted")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        settings = QPushButton("Settings")
        settings.clicked.connect(self.open_settings)
        header_layout.addWidget(brand)
        header_layout.addStretch()
        header_layout.addWidget(self.balance_label)
        header_layout.addSpacing(10)
        header_layout.addWidget(self.connection_label)
        header_layout.addSpacing(10)
        header_layout.addWidget(refresh)
        header_layout.addWidget(settings)
        root.addWidget(header)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("mainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(5)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(245)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 12, 7, 10)
        sidebar_layout.setSpacing(0)
        side_scroll = QScrollArea()
        side_scroll.setObjectName("sidebarScroll")
        side_scroll.setWidgetResizable(True)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_body = QWidget()
        side = QVBoxLayout(side_body)
        side.setContentsMargins(4, 3, 5, 8)
        side.setSpacing(14)

        new_agent = QPushButton("+ New Agent")
        new_agent.clicked.connect(self.show_new_agent)
        self.agents_section = CollapsibleSection("AGENTS", new_agent)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search agents…")
        self.search.textChanged.connect(self._filter_agents)
        self.agent_list = NaturalListWidget()
        self.agent_list.setObjectName("agentSidebarList")
        self.agent_list.currentItemChanged.connect(self._agent_selected)
        self.agent_list.itemClicked.connect(lambda _item: self._sync_agent_row_selection())
        self.agent_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.agent_list.customContextMenuRequested.connect(self._agent_menu)
        self.agents_section.body_layout.addWidget(self.search)
        self.agents_section.body_layout.addWidget(self.agent_list)
        side.addWidget(self.agents_section)

        new_research = QPushButton("+ New Research")
        new_research.clicked.connect(self.show_new_research)
        self.research_section = CollapsibleSection("RESEARCH", new_research)
        self.research_search = QLineEdit()
        self.research_search.setPlaceholderText("Search research…")
        self.research_search.textChanged.connect(self._filter_research)
        self.research_list = NaturalListWidget()
        self.research_list.setObjectName("researchSidebarList")
        self.research_list.itemClicked.connect(self._research_selected)
        self.view_all_research = QPushButton("View all")
        self.view_all_research.setObjectName("linkButton")
        self.view_all_research.clicked.connect(self.show_all_research)
        self.view_all_research.hide()
        self.research_section.body_layout.addWidget(self.research_search)
        self.research_section.body_layout.addWidget(self.research_list)
        self.research_section.body_layout.addWidget(self.view_all_research)
        side.addWidget(self.research_section)

        side.addStretch()
        side_scroll.setWidget(side_body)
        sidebar_layout.addWidget(side_scroll, 1)

        processes_panel = QFrame()
        processes_panel.setObjectName("processesPanel")
        processes_layout = QVBoxLayout(processes_panel)
        processes_layout.setContentsMargins(4, 10, 5, 4)
        processes_layout.setSpacing(6)
        processes_layout.addWidget(section_label("Active Processes"))
        self.process_list = NaturalListWidget(max_height=4 * 66)
        self.process_list.setObjectName("processSidebarList")
        self.process_list.itemClicked.connect(self._process_selected)
        processes_layout.addWidget(self.process_list)
        sidebar_layout.addWidget(processes_panel, 0)
        self.main_splitter.addWidget(sidebar)

        self.detail = QStackedWidget()
        self.placeholder = self._placeholder_page()
        self.detail.addWidget(self.placeholder)
        self.main_splitter.addWidget(self.detail)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([310, 910])
        root.addWidget(self.main_splitter, 1)
        self.statusBar().showMessage("Ready")
        self.setCentralWidget(central)

        # ui/sidebar/processes_expanded is a legacy key from when Active
        # Processes was collapsible; it is no longer read or written.
        section_settings = (
            (self.agents_section, "ui/sidebar/agents_expanded"),
            (self.research_section, "ui/sidebar/research_expanded"),
        )
        for section, key in section_settings:
            section.set_expanded(self.ui_settings.value(key, True, type=bool))
            section.expandedChanged.connect(
                lambda expanded, setting_key=key: self.ui_settings.setValue(
                    setting_key, expanded
                )
            )
        self.main_splitter.splitterMoved.connect(
            lambda _position, _index: self.ui_settings.setValue(
                "ui/main_splitter", self.main_splitter.saveState()
            )
        )

    def _restore_ui_state(self) -> None:
        geometry = self.ui_settings.value("ui/main_window_geometry")
        if geometry is not None and self.restoreGeometry(geometry):
            ensure_visible(self)
        else:
            self.resize(1220, 790)
        state = self.ui_settings.value("ui/main_window_state")
        if state is not None:
            self.restoreState(state)
        splitter = self.ui_settings.value("ui/main_splitter")
        if splitter is not None:
            self.main_splitter.restoreState(splitter)
        if self.ui_settings.value("ui/main_window_maximized", False, type=bool):
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def _placeholder_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(45, 45, 45, 45)
        layout.addStretch()
        title = QLabel("Select an Agent or Research")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        help_text = muted(
            "Manage saved Agent configurations, monitor active work, and export completed research."
        )
        help_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(help_text)
        connect = QPushButton("Connect Virlo API")
        connect.clicked.connect(self.connect_api)
        connect.setMaximumWidth(190)
        layout.addWidget(connect, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        return page

    def _set_client(self, key: str) -> None:
        if self.client:
            self.client.close()
        self.client = VirloClient(
            key,
            base_url=self.settings.api_base_url,
            event_callback=lambda event: logger.info("virlo_api %s", event),
        )

    def _run_worker(
        self,
        function: Any,
        on_result: Any,
        *,
        progress: Any = None,
        label: str = "Working…",
        on_finished: Any = None,
    ) -> None:
        worker = Worker(function)
        self.active_workers.add(worker)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(lambda error, details: self._worker_error(error, details))
        if progress:
            worker.signals.progress.connect(progress)
        worker.signals.finished.connect(lambda: self._worker_finished(worker, on_finished))
        QThreadPool.globalInstance().start(worker)
        self.statusBar().showMessage(label)

    def _worker_finished(self, worker: Worker, callback: Any = None) -> None:
        self.active_workers.discard(worker)
        if callback:
            callback()
        if not self.active_workers:
            self.statusBar().showMessage("Ready")

    def _set_connection_state(self, text: str, style: str) -> None:
        self.connection_label.setText(text)
        self.connection_label.setObjectName(style)
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)

    def _worker_error(self, error: Exception | str, details: str) -> None:
        message = str(error) or "An unexpected error occurred."
        logger.error("background operation failed: %s\n%s", message, details)
        if isinstance(error, AuthenticationError):
            self._set_connection_state("● Authentication failed", "error")
            title = "Authentication error"
        elif isinstance(error, NetworkError):
            self._set_connection_state("● Offline", "muted")
            title = "Network error"
        elif isinstance(error, (PaginationError, MalformedResponseError)):
            self._set_connection_state("● API error", "warning")
            title = "Virlo data error"
        elif isinstance(error, VirloError):
            self._set_connection_state("● API error", "warning")
            title = "Virlo API error"
        else:
            self._set_connection_state("● API error", "warning")
            title = "Operation failed"
        show_error(self, title, message, details)

    def connect_api(self) -> None:
        dialog = ApiKeyDialog(self, existing=self.client is not None)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        key = dialog.api_key()
        candidate = VirloClient(key, base_url=self.settings.api_base_url)

        def test() -> dict[str, Any]:
            try:
                return candidate.test_connection()
            finally:
                candidate.close()

        def connected(_: dict[str, Any]) -> None:
            try:
                self.key_store.set(key)
            except RuntimeError as exc:
                show_error(self, "Could not save API key", str(exc))
                return
            self._set_client(key)
            self._set_connection_state("● Connected", "connected")
            self.refresh()

        self._run_worker(test, connected, label="Testing Virlo connection…")

    def refresh(self) -> None:
        if not self.client:
            return
        client = self.client

        def fetch() -> Any:
            return client.list_agents()

        def loaded(result: Any) -> None:
            records = result.records
            for record in records:
                self.database.cache_agent(record)
            self._populate_agents(records)
            self._set_connection_state("● Connected", "connected")
            if client.last_balance is not None:
                self.balance_label.setText(f"Balance: ${client.last_balance:.2f}")
            else:
                self.balance_label.setText("Balance unavailable")
            active = any(agent.is_processing for agent in self.agents.values())
            self.refresh_timer.setInterval(15000 if active else 60000)
            self._load_all_runs()

        self._run_worker(fetch, loaded, label="Refreshing Agents…")

    def _load_cached_agents(self) -> None:
        cached = self.database.cached_agents()
        if cached:
            self._populate_agents(cached)
            for record in self.database.cached_runs():
                run = Run.from_api(record)
                run.local_number = int(record["local_number"])
                self.runs.setdefault(run.agent_id, []).append(run)
            self._render_agent_list()
            self._populate_research()
            self.statusBar().showMessage("Showing cached data — connect Virlo to refresh")

    def _restore_current_page(self) -> None:
        kind = self._current_page[0]
        if kind == "agent":
            _, agent_id = self._current_page
            if agent_id in self.agents:
                self.show_agent(agent_id)
        elif kind == "run":
            _, agent_id, run_id = self._current_page
            agent = self.agents.get(agent_id)
            run = next((value for value in self.runs.get(agent_id, []) if value.id == run_id), None)
            if agent and run:
                self.show_run(agent, run)

    def _populate_agents(self, records: list[dict[str, Any]]) -> None:
        current = self.selected_agent_id
        self.agents = {
            str(row.get("id")): Agent.from_api(row) for row in records if row.get("id")
        }
        self._render_agent_list(current)
        self._populate_processes()
        self._populate_research()
        self._restore_current_page()

    def _render_agent_list(self, current: str | None = None) -> None:
        current = current or self.selected_agent_id
        self.agent_list.blockSignals(True)
        self.agent_list.clear()
        if not self.agents:
            item = QListWidgetItem("No agents yet\nCreate your first Virlo Agent")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(QSize(220, 64))
            self.agent_list.addItem(item)
        for agent in sorted(self.agents.values(), key=lambda value: value.name.casefold()):
            status = agent_display_status(agent, self.runs.get(agent.id, []))
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, agent.id)
            item.setSizeHint(QSize(230, 64))
            row = AgentRow(
                agent,
                status,
                lambda _=False, value=agent: self.edit_agent(value),
                lambda _=False, value=agent: self.quick_rename_agent(value),
            )
            self.agent_list.addItem(item)
            self.agent_list.setItemWidget(item, row)
            if agent.id == current:
                self.agent_list.setCurrentItem(item)
        self.agent_list.blockSignals(False)
        self._filter_agents(self.search.text())
        self.agent_list.sync_height()
        self._sync_agent_row_selection()

    def _filter_agents(self, text: str) -> None:
        query = text.casefold().strip()
        for index in range(self.agent_list.count()):
            item = self.agent_list.item(index)
            agent_id = item.data(Qt.ItemDataRole.UserRole)
            agent = self.agents.get(str(agent_id))
            item.setHidden(bool(agent) and query not in agent.name.casefold())
        self.agent_list.sync_height()

    def _sync_agent_row_selection(self) -> None:
        current = self.agent_list.currentItem()
        for index in range(self.agent_list.count()):
            item = self.agent_list.item(index)
            row = self.agent_list.itemWidget(item)
            if isinstance(row, AgentRow):
                row.set_selected(item is current)

    def _populate_processes(self) -> None:
        current = self.process_list.currentItem()
        current_key = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.process_list.clear()
        for agent in self.agents.values():
            if agent.is_processing:
                phase = "Processing"
                if agent.pending_jobs:
                    phase = str(agent.pending_jobs[0].get("type") or phase).replace("_", " ").title()
                active_run = max(
                    (
                        run
                        for run in self.runs.get(agent.id, [])
                        if run.status.casefold() in {"pending", "running", "processing"}
                    ),
                    key=run_timestamp,
                    default=None,
                )
                number = (
                    f" #{active_run.local_number:03d}" if active_run and active_run.local_number else ""
                )
                key = {"kind": "server", "agent_id": agent.id}
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setSizeHint(QSize(220, 62))
                row = ProcessRow(f"Research{number} · {agent.name}", phase)
                self.process_list.addItem(item)
                self.process_list.setItemWidget(item, row)
                if key == current_key:
                    self.process_list.setCurrentItem(item)
        for process in self.database.active_processes():
            key = {"kind": "local", "process_id": process["process_id"]}
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, {**key, **process})
            item.setSizeHint(QSize(220, 62))
            payload = process.get("payload") if isinstance(process.get("payload"), dict) else {}
            secondary = str(payload.get("stage") or process["status"]).replace("_", " ").title()
            if isinstance(payload.get("percent"), (int, float)):
                secondary = f"{secondary} · {int(payload['percent'])}%"
            row = ProcessRow(process["label"], secondary)
            self.process_list.addItem(item)
            self.process_list.setItemWidget(item, row)
            if key == current_key:
                self.process_list.setCurrentItem(item)
        if self.process_list.count() == 0:
            item = QListWidgetItem("No active processes")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(QSize(220, 36))
            self.process_list.addItem(item)
        self.process_list.sync_height()
        self._sync_process_row_selection()

    def _sync_process_row_selection(self) -> None:
        current = self.process_list.currentItem()
        for index in range(self.process_list.count()):
            item = self.process_list.item(index)
            row = self.process_list.itemWidget(item)
            if isinstance(row, ProcessRow):
                row.set_selected(item is current)

    def _all_research(self) -> list[tuple[Agent, Run]]:
        values = [
            (agent, run)
            for agent_id, runs in self.runs.items()
            if (agent := self.agents.get(agent_id)) is not None
            for run in runs
        ]
        return sorted(values, key=lambda value: run_timestamp(value[1]), reverse=True)

    def _populate_research(self) -> None:
        current = self.research_list.currentItem()
        current_key = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.research_list.clear()
        research = self._all_research()
        for agent, run in research[:RECENT_RESEARCH_LIMIT]:
            number = run.local_number or 0
            display_name = self.database.research_display_name(agent.id, run.id)
            if display_name:
                title = display_name
                secondary = f"Research #{number:03d} · {agent.name} · {compact_date(run_timestamp(run))}"
            else:
                title = f"Research #{number:03d}"
                secondary = f"{agent.name} · {compact_date(run_timestamp(run))}"
            key = {"agent_id": agent.id, "run_id": run.id}
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setData(Qt.ItemDataRole.UserRole + 1, research_search_text(agent.name, run, display_name))
            item.setSizeHint(QSize(220, 62))
            row = ResearchRow(
                title,
                secondary,
                lambda _=False, a=agent, r=run: self.rename_research(a, r),
            )
            self.research_list.addItem(item)
            self.research_list.setItemWidget(item, row)
            if key == current_key:
                self.research_list.setCurrentItem(item)
        if not research:
            item = QListWidgetItem("No research runs yet")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(QSize(220, 36))
            self.research_list.addItem(item)
        self.view_all_research.setVisible(len(research) > RECENT_RESEARCH_LIMIT)
        self._filter_research(self.research_search.text())
        self.research_list.sync_height()
        self._sync_research_row_selection()

    def _filter_research(self, text: str) -> None:
        query = text.casefold().strip()
        for index in range(self.research_list.count()):
            item = self.research_list.item(index)
            haystack = item.data(Qt.ItemDataRole.UserRole + 1)
            if haystack is None:
                continue
            item.setHidden(bool(query) and query not in haystack)
        self.research_list.sync_height()

    def _sync_research_row_selection(self) -> None:
        current = self.research_list.currentItem()
        for index in range(self.research_list.count()):
            item = self.research_list.item(index)
            row = self.research_list.itemWidget(item)
            if isinstance(row, ResearchRow):
                row.set_selected(item is current)

    def _select_research_item(self, agent_id: str, run_id: str) -> None:
        for index in range(self.research_list.count()):
            item = self.research_list.item(index)
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict) and data.get("agent_id") == agent_id and data.get("run_id") == run_id:
                self.research_list.blockSignals(True)
                self.research_list.setCurrentItem(item)
                self.research_list.blockSignals(False)
                self._sync_research_row_selection()
                return
        self.research_list.blockSignals(True)
        self.research_list.setCurrentItem(None)
        self.research_list.blockSignals(False)
        self._sync_research_row_selection()

    def _select_process_item(self, key: dict[str, Any] | None) -> None:
        self.process_list.blockSignals(True)
        if key is None:
            self.process_list.setCurrentItem(None)
        else:
            for index in range(self.process_list.count()):
                item = self.process_list.item(index)
                data = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(data, dict) and data.get("kind") == key.get("kind") and (
                    data.get("agent_id") == key.get("agent_id")
                    or data.get("process_id") == key.get("process_id")
                ):
                    self.process_list.setCurrentItem(item)
                    break
            else:
                self.process_list.setCurrentItem(None)
        self.process_list.blockSignals(False)
        self._sync_process_row_selection()

    def _clear_agent_selection(self) -> None:
        self.agent_list.blockSignals(True)
        self.agent_list.setCurrentItem(None)
        self.agent_list.blockSignals(False)
        self._sync_agent_row_selection()

    def _clear_research_selection(self) -> None:
        self.research_list.blockSignals(True)
        self.research_list.setCurrentItem(None)
        self.research_list.blockSignals(False)
        self._sync_research_row_selection()

    def _clear_process_selection(self) -> None:
        self._select_process_item(None)

    def _clear_active_export_view(self) -> None:
        """Detach from whichever export process view is on screen. The event
        log itself is untouched, so returning to it later just replays it."""
        self._active_export_timeline = None
        self._active_export_process_id = None

    def _load_all_runs(self) -> None:
        if not self.client or self._runs_loading or not self.agents:
            return
        self._runs_loading = True
        client = self.client
        agent_ids = list(self.agents)

        def fetch() -> dict[str, list[dict[str, Any]]]:
            return {agent_id: client.list_runs(agent_id).records for agent_id in agent_ids}

        def loaded(results: dict[str, list[dict[str, Any]]]) -> None:
            for agent_id, records in results.items():
                mapping = self.database.assign_runs(agent_id, records)
                values: list[Run] = []
                for record in records:
                    run = Run.from_api(record)
                    run.local_number = mapping.get(run.id)
                    values.append(run)
                self.runs[agent_id] = values
            self._render_agent_list()
            self._populate_research()
            self._restore_current_page()

        self._run_worker(
            fetch,
            loaded,
            label="Loading recent research…",
            on_finished=lambda: setattr(self, "_runs_loading", False),
        )

    def _load_runs(self, agent_id: str) -> None:
        if not self.client:
            self.runs[agent_id] = []
            return
        client = self.client

        def fetch() -> Any:
            return client.list_runs(agent_id)

        def loaded(result: Any) -> None:
            mapping = self.database.assign_runs(agent_id, result.records)
            values = []
            for record in result.records:
                run = Run.from_api(record)
                run.local_number = mapping.get(run.id)
                values.append(run)
            self.runs[agent_id] = values
            self._render_agent_list()
            self._populate_research()
            self._restore_current_page()

        self._run_worker(fetch, loaded, label="Loading research runs…")

    def _agent_selected(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        self._sync_agent_row_selection()
        if current:
            agent_id = current.data(Qt.ItemDataRole.UserRole)
            if agent_id:
                self.show_agent(str(agent_id))

    def _research_selected(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        agent_id = str(data.get("agent_id"))
        agent = self.agents.get(agent_id)
        run = next(
            (value for value in self.runs.get(agent_id, []) if value.id == str(data.get("run_id"))),
            None,
        )
        if agent and run:
            self.show_run(agent, run)

    def _select_agent_item(self, agent_id: str) -> None:
        for index in range(self.agent_list.count()):
            item = self.agent_list.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole)) == agent_id:
                self.agent_list.blockSignals(True)
                self.agent_list.setCurrentItem(item)
                self.agent_list.blockSignals(False)
                self._sync_agent_row_selection()
                return

    def show_agent(self, agent_id: str) -> None:
        self.selected_agent_id = agent_id
        self._current_page = ("agent", agent_id)
        self._clear_active_export_view()
        self._select_agent_item(agent_id)
        self._clear_research_selection()
        self._clear_process_selection()
        agent = self.agents[agent_id]
        known_runs = self.runs.get(agent_id)
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(28, 24, 28, 24)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(14)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel(agent.name)
        title.setObjectName("title")
        status = agent_display_status(agent, known_runs or [])
        mode = "Recurring" if agent.is_recurring else "One-time"
        title_box.addWidget(title)
        title_box.addWidget(muted(f"{mode} · {status}"))
        latest = max(known_runs or [], key=run_timestamp, default=None)
        title_box.addWidget(
            muted(f"Last Research: {human_date(run_timestamp(latest) if latest else agent.last_run_at)}")
        )
        header.addLayout(title_box, 1)
        more = QToolButton()
        more.setText("•••")
        more.setToolTip("More Agent actions")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        rename_action = QAction("Rename Agent", menu)
        rename_action.triggered.connect(lambda: self.quick_rename_agent(agent))
        menu.addAction(rename_action)
        copy_id = QAction("Copy Agent ID", menu)
        copy_id.triggered.connect(lambda: QApplication.clipboard().setText(agent.id))
        menu.addAction(copy_id)
        open_folder = QAction("Open Export Folder", menu)
        open_folder.triggered.connect(lambda: open_in_explorer(Path(self.settings.export_folder)))
        menu.addAction(open_folder)
        more.setMenu(menu)
        header.addWidget(more)
        layout.addLayout(header)

        overview, overview_layout = card()
        overview_layout.addWidget(card_heading("Agent configuration"))
        config_splitter = QSplitter(Qt.Orientation.Horizontal)
        config_splitter.setObjectName("configurationSplitter")
        config_splitter.setChildrenCollapsible(False)
        left = QWidget()
        left.setObjectName("configurationMain")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 5, 12, 0)
        left_layout.setSpacing(9)
        left_layout.addWidget(section_label("Intent"))
        intent_box = QFrame()
        intent_box.setObjectName("intentBox")
        intent_box_layout = QVBoxLayout(intent_box)
        intent_box_layout.setContentsMargins(14, 12, 14, 12)
        intent = QLabel(agent.intent or "No intent returned")
        intent.setWordWrap(True)
        intent.setObjectName("bodyText")
        intent_box_layout.addWidget(intent)
        left_layout.addWidget(intent_box)
        left_layout.addWidget(section_label("Sources"))
        platform_row = QHBoxLayout()
        platform_row.setSpacing(6)
        for value in agent.platforms:
            label_text = "Meta Ads" if value == "meta_ads" else value.title()
            platform_row.addWidget(pill(label_text))
        platform_row.addStretch()
        platform_host = QWidget()
        platform_host.setLayout(platform_row)
        left_layout.addWidget(platform_host)
        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        di_enabled = agent.data_intelligence_enabled
        params = [
            ("Language", "English only" if agent.english_only else "All languages", "neutral"),
            ("Type", mode, "neutral"),
            ("Data Intelligence", "● ON" if di_enabled else "● OFF", "on" if di_enabled else "off"),
            (
                "Meta Ads",
                "● ON" if agent.meta_ads_enabled else "● OFF",
                "on" if agent.meta_ads_enabled else "off",
            ),
            ("Cadence", agent.cadence or "—", "neutral"),
            (
                "Last Research",
                human_date(run_timestamp(latest) if latest else agent.last_run_at),
                "neutral",
            ),
        ]
        for index, (label_text, value_text, state) in enumerate(params):
            grid.addWidget(mini_card(label_text, value_text, state), index // 2, index % 2)
        grid_host = QWidget()
        grid_host.setLayout(grid)
        left_layout.addWidget(grid_host)
        actions = QHBoxLayout()
        new_research = QPushButton("New Research")
        new_research.setObjectName("primary")
        new_research.clicked.connect(lambda: self.show_new_research(agent.id))
        edit = QPushButton("Edit Agent")
        edit.clicked.connect(lambda: self.edit_agent(agent))
        actions.addWidget(new_research)
        actions.addWidget(edit)
        if agent.is_recurring:
            toggle = QPushButton("Pause" if agent.active else "Resume")
            toggle.clicked.connect(lambda: self.toggle_agent(agent))
            actions.addWidget(toggle)
        actions.addStretch()
        left_layout.addLayout(actions)
        left_layout.addStretch()
        config_splitter.addWidget(left)

        keywords_panel = QFrame()
        keywords_panel.setObjectName("keywordsPanel")
        keyword_layout = QVBoxLayout(keywords_panel)
        keyword_layout.setContentsMargins(13, 12, 13, 12)
        keyword_header = QHBoxLayout()
        keyword_header.addWidget(section_label("Keywords"))
        keyword_header.addStretch()
        keyword_header.addWidget(muted(f"{len(agent.keywords)} / 50"))
        keyword_layout.addLayout(keyword_header)
        keyword_list = QListWidget()
        keyword_list.setObjectName("keywordDetailList")
        keyword_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        keyword_list.addItems(agent.keywords or ["No keywords returned"])
        keyword_layout.addWidget(keyword_list)
        config_splitter.addWidget(keywords_panel)
        config_splitter.setStretchFactor(0, 2)
        config_splitter.setStretchFactor(1, 1)
        saved_splitter = self.ui_settings.value("ui/agent_configuration_splitter")
        if saved_splitter is not None:
            config_splitter.restoreState(saved_splitter)
        else:
            config_splitter.setSizes([680, 320])
        config_splitter.splitterMoved.connect(
            lambda _position, _index: self.ui_settings.setValue(
                "ui/agent_configuration_splitter", config_splitter.saveState()
            )
        )
        overview_layout.addWidget(config_splitter)
        layout.addWidget(overview)
        layout.addWidget(card_heading("Research Runs"))
        if known_runs is None:
            layout.addWidget(muted("Loading research runs…"))
            self._load_runs(agent_id)
        elif not known_runs:
            layout.addWidget(muted("No research runs yet"))
        else:
            for run in sorted(known_runs, key=run_timestamp, reverse=True):
                layout.addWidget(self._run_card(agent, run))
        layout.addStretch()
        scroll.setWidget(body)
        page_layout.addWidget(scroll)
        self._show_page(page)

    def _run_card(self, agent: Agent, run: Run) -> QFrame:
        frame, layout = card()
        number = run.local_number or 0
        display_name = self.database.research_display_name(agent.id, run.id)
        top = QHBoxLayout()
        title = QLabel(display_name or f"Research #{number:03d}")
        title.setObjectName("cardTitle")
        top.addWidget(title)
        top.addStretch()
        top.addWidget(
            status_badge(run.status.replace("_", " "), RUN_STATUS_STATE.get(run.status.casefold(), "neutral"))
        )
        layout.addLayout(top)
        subtitle = f"Research #{number:03d} · {human_date(run_timestamp(run))}"
        if display_name:
            subtitle = f"Research #{number:03d} · {agent.name} · {human_date(run_timestamp(run))}"
        layout.addWidget(muted(subtitle))

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(8)
        for label_text, value_text in (
            ("Videos", f"{run.videos_linked:,}"),
            ("Slideshows", f"{run.slideshows_linked:,}"),
            ("Meta Ads", f"{run.meta_ads_linked:,}"),
            ("Outliers", f"{run.outliers_identified:,}"),
        ):
            metrics_row.addWidget(metric_card(label_text, value_text))
        layout.addLayout(metrics_row)

        actions = QHBoxLayout()
        open_button = QPushButton("Open Research")
        open_button.clicked.connect(lambda: self.show_run(agent, run))
        actions.addWidget(open_button)
        actions.addStretch()
        export = QPushButton("Export for AI")
        export.setObjectName("primary")
        export.setEnabled(run.status in {"completed", "partial_failure"})
        export.clicked.connect(lambda: self.start_export(agent, run))
        actions.addWidget(export)
        layout.addLayout(actions)
        return frame

    @staticmethod
    def _read_export_summary(export_dir: str) -> dict[str, Any]:
        path = Path(export_dir) / export_report.REPORT_FILENAME
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        summary = payload.get("summary")
        return summary if isinstance(summary, dict) else {}

    def reveal_export_report(
        self, agent: Agent, run: Run, export_record: dict[str, Any]
    ) -> None:
        export_dir = Path(export_record["path"])
        if not export_dir.exists():
            show_error(self, "Export folder missing", "This export's folder no longer exists on disk.")
            return
        path = export_report.ensure_report(
            export_dir,
            export_row=export_record,
            stages=self.database.export_stages(export_record["id"]),
            agent_name=agent.name,
        )
        reveal_in_explorer(path)

    def _export_card(self, agent: Agent, run: Run, export_record: dict[str, Any]) -> QFrame:
        frame, layout = card()
        status = str(export_record["status"])
        state = RUN_STATUS_STATE.get(status.casefold(), "neutral")
        top = QHBoxLayout()
        title = QLabel(f"Export #{export_record['export_number']:03d}")
        title.setObjectName("cardTitle")
        top.addWidget(title)
        top.addStretch()
        badge = ClickableStatusBadge(status.replace("_", " "), state)
        if status in {"failed", "complete_with_warnings"}:
            badge.setToolTip("Open EXPORT_REPORT.json")
            badge.clicked.connect(
                lambda _=False, record=export_record: self.reveal_export_report(agent, run, record)
            )
        top.addWidget(badge)
        layout.addLayout(top)
        layout.addWidget(
            muted(human_date(export_record.get("completed_at") or export_record.get("started_at")))
        )

        summary = self._read_export_summary(export_record["path"])
        metrics: list[tuple[str, str]] = []
        if "dataset_bytes" in summary:
            metrics.append(("AI Dataset", format_bytes(summary["dataset_bytes"])))
        if "raw_bytes" in summary:
            metrics.append(("RAW Data", format_bytes(summary["raw_bytes"])))
        if "videos" in summary:
            metrics.append(("Videos", f"{summary['videos']:,}"))
        metrics.append(("Warnings", str(summary.get("warnings", 0))))
        if metrics:
            metrics_row = QHBoxLayout()
            metrics_row.setSpacing(8)
            for label_text, value_text in metrics:
                metrics_row.addWidget(metric_card(label_text, value_text))
            layout.addLayout(metrics_row)

        actions = QHBoxLayout()
        view_button = QPushButton("View Process")
        view_button.clicked.connect(
            lambda _=False, record=export_record: self.open_export_history(agent, run, record)
        )
        actions.addWidget(view_button)
        open_button = QPushButton("Open Folder")
        open_button.clicked.connect(
            lambda _=False, path=export_record["path"]: open_in_explorer(Path(path))
        )
        actions.addWidget(open_button)
        actions.addStretch()
        report_button = QPushButton("Report")
        report_button.clicked.connect(
            lambda _=False, record=export_record: self.reveal_export_report(agent, run, record)
        )
        actions.addWidget(report_button)
        layout.addLayout(actions)
        return frame

    def show_run(self, agent: Agent, run: Run) -> None:
        self.selected_agent_id = agent.id
        self._current_page = ("run", agent.id, run.id)
        self._clear_active_export_view()
        self._clear_agent_selection()
        self._select_research_item(agent.id, run.id)
        self._clear_process_selection()
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(28, 24, 28, 24)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(14)
        number = run.local_number or 0
        display_name = self.database.research_display_name(agent.id, run.id)
        header_box = QVBoxLayout()
        header_box.setSpacing(2)
        title_row = QHBoxLayout()
        title = QLabel(display_name or f"Research #{number:03d}")
        title.setObjectName("title")
        title_row.addWidget(title)
        rename_button = QToolButton()
        rename_button.setObjectName("pencilButton")
        rename_button.setText("✎")
        rename_button.setToolTip("Rename research")
        rename_button.clicked.connect(lambda: self.rename_research(agent, run))
        title_row.addWidget(rename_button)
        title_row.addStretch()
        status_state = RUN_STATUS_STATE.get(run.status.casefold(), "neutral")
        title_row.addWidget(status_badge(run.status.replace("_", " "), status_state))
        header_box.addLayout(title_row)
        if display_name:
            header_box.addWidget(muted(f"Research #{number:03d} · {agent.name}"))
        else:
            header_box.addWidget(muted(agent.name))
        header_box.addWidget(muted(human_date(run_timestamp(run))))
        layout.addLayout(header_box)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(10)
        for label_text, value_text in (
            ("Videos", f"{run.videos_linked:,}"),
            ("Slideshows", f"{run.slideshows_linked:,}"),
            ("Meta Ads", f"{run.meta_ads_linked:,}"),
            ("Outliers", f"{run.outliers_identified:,}"),
        ):
            metrics_row.addWidget(metric_card(label_text, value_text))
        layout.addLayout(metrics_row)

        raw = run.raw or {}
        platform_counts = [
            (name, raw.get(f"{name}_count"))
            for name in ("youtube", "tiktok", "instagram")
            if raw.get(f"{name}_count") is not None
        ]
        if platform_counts:
            breakdown = "   ·   ".join(f"{name.title()} {count:,}" for name, count in platform_counts)
            layout.addWidget(muted(breakdown))

        run_info, run_info_layout = card()
        run_info_layout.addWidget(card_heading("Run info"))
        duration = "—"
        if run.execution_time_ms:
            total_seconds = int(run.execution_time_ms / 1000)
            minutes, seconds = divmod(total_seconds, 60)
            duration = f"{minutes}m {seconds:02d}s"
        run_info_grid = QGridLayout()
        run_info_grid.setSpacing(8)
        run_info_grid.setColumnStretch(0, 1)
        run_info_grid.setColumnStretch(1, 1)
        run_info_fields = [
            ("Started", compact_date(run.started_at)),
            ("Completed", compact_date(run.completed_at)),
            ("Duration", duration),
            ("Keywords", str(len(agent.keywords))),
            ("Status", run.status.replace("_", " ").title()),
            ("Cadence", agent.cadence or "—"),
        ]
        for index, (field_label, field_value) in enumerate(run_info_fields):
            run_info_grid.addWidget(mini_card(field_label, field_value), index // 2, index % 2)
        run_info_grid_host = QWidget()
        run_info_grid_host.setLayout(run_info_grid)
        run_info_layout.addWidget(run_info_grid_host)
        run_info_layout.addWidget(section_label("Platforms"))
        run_platform_row = QHBoxLayout()
        run_platform_row.setSpacing(6)
        for value in agent.platforms:
            run_platform_row.addWidget(pill("Meta Ads" if value == "meta_ads" else value.title()))
        run_platform_row.addStretch()
        run_platform_host = QWidget()
        run_platform_host.setLayout(run_platform_row)
        run_info_layout.addWidget(run_platform_host)
        layout.addWidget(run_info)

        intelligence, intelligence_layout = card()
        intelligence_layout.addWidget(card_heading("Intelligence"))
        analysis_data = agent.raw.get("analysis_data")
        analysis_ready = bool(analysis_data)
        theme_count = len(analysis_data.get("themes", [])) if isinstance(analysis_data, dict) else 0
        intelligence_grid = QGridLayout()
        intelligence_grid.setSpacing(8)
        intelligence_grid.setColumnStretch(0, 1)
        intelligence_grid.setColumnStretch(1, 1)
        intelligence_fields = [
            (
                "Data Intelligence",
                "● Enabled" if agent.data_intelligence_enabled else "● Disabled",
                "on" if agent.data_intelligence_enabled else "off",
            ),
            (
                "Meta Ads",
                "● Enabled" if agent.meta_ads_enabled else "● Disabled",
                "on" if agent.meta_ads_enabled else "off",
            ),
            (
                "Analysis",
                f"● Ready · {theme_count} themes" if analysis_ready else "● Not available",
                "on" if analysis_ready else "off",
            ),
            (
                "Hooks",
                "● Available" if agent.data_intelligence_enabled else "● Requires Data Intelligence",
                "on" if agent.data_intelligence_enabled else "off",
            ),
        ]
        for index, (field_label, field_value, field_state) in enumerate(intelligence_fields):
            intelligence_grid.addWidget(
                mini_card(field_label, field_value, field_state), index // 2, index % 2
            )
        intelligence_grid_host = QWidget()
        intelligence_grid_host.setLayout(intelligence_grid)
        intelligence_layout.addWidget(intelligence_grid_host)
        layout.addWidget(intelligence)

        export = QPushButton("Export for AI")
        export.setObjectName("primary")
        export.setMinimumHeight(44)
        export.setEnabled(run.status in {"completed", "partial_failure"})
        export.clicked.connect(lambda: self.start_export(agent, run))
        layout.addWidget(export)
        history = self.database.export_history(agent.id, run.id)
        layout.addWidget(card_heading("Exports"))
        if not history:
            layout.addWidget(muted("No local exports yet."))
        for item in history:
            layout.addWidget(self._export_card(agent, run, item))
        layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll)
        self._show_page(page)

    def show_all_research(self) -> None:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(28, 24, 28, 24)
        title = QLabel("All Research")
        title.setObjectName("title")
        root.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        for agent, run in self._all_research():
            layout.addWidget(self._run_card(agent, run))
        layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll)
        self._show_page(page)

    def show_new_agent(self) -> None:
        if not self.client:
            self.connect_api()
            return
        dialog = AgentEditorDialog(parent=self)
        dialog.suggestRequested.connect(lambda payload: self.suggest_keywords(dialog, payload))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.create_research(dialog.payload())

    def show_new_research(self, selected_agent_id: str | None = None) -> None:
        if not self.client:
            self.connect_api()
            return
        if not self.agents:
            QMessageBox.information(
                self, "No Agents", "Create an Agent before starting new research."
            )
            return
        dialog = NewResearchDialog(
            self.agents.values(), self, selected_agent_id=selected_agent_id
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.create_research(dialog.payload())

    def suggest_keywords(
        self, editor: AgentEditorDialog, payload: dict[str, Any]
    ) -> None:
        if not self.client:
            return
        editor.set_suggest_enabled(False)
        client = self.client

        def fetch() -> Any:
            return client.suggest_keywords(payload)[0]

        def loaded(result: dict[str, Any]) -> None:
            data = result.get("data", result)
            editor.apply_suggestion(data)

        self._run_worker(
            fetch,
            loaded,
            label="Suggesting keywords (free)…",
            on_finished=lambda: editor.set_suggest_enabled(True),
        )

    def create_research(self, payload: dict[str, Any]) -> None:
        if not self.client:
            return
        estimate = BillingSafety.estimate_agent(
            data_intelligence=bool(payload.get("data_intelligence_enabled"))
        )
        confirmation = PaidConfirmationDialog(estimate, self.client.last_balance, self)
        if confirmation.exec() != QDialog.DialogCode.Accepted:
            return
        client = self.client

        def create() -> Any:
            return client.create_agent(payload)

        def created(result: Any) -> None:
            response, headers = result
            data = response.get("data", response)
            cost, balance = BillingSafety.response_cost(headers)
            if balance is not None:
                self.balance_label.setText(f"Balance: ${balance:.2f}")
            actual = "not reported" if cost is None else f"${cost:.2f}"
            self.statusBar().showMessage(
                f"Research started · actual Virlo charge: {actual}", 10000
            )
            if isinstance(data, dict) and data.get("id"):
                self.database.cache_agent(data)
            self.refresh()
            self.detail.setCurrentWidget(self.placeholder)

        self._run_worker(create, created, label="Starting paid Virlo research…")

    def rerun_agent(self, agent: Agent) -> None:
        self.show_new_research(agent.id)

    def toggle_agent(self, agent: Agent) -> None:
        if not self.client:
            return
        action = "pause" if agent.active else "resume"
        question = (
            "Pause future scheduled runs? A run already in progress may continue."
            if agent.active
            else "Resume future scheduled runs?"
        )
        if (
            QMessageBox.question(self, f"{action.title()} Agent", question)
            != QMessageBox.StandardButton.Yes
        ):
            return
        client = self.client
        self._run_worker(
            lambda: client.update_agent(agent.id, {"active": not agent.active}),
            lambda _result: self.refresh(),
            label=f"{action.title()}ing Agent…",
        )

    def quick_rename_agent(self, agent: Agent) -> None:
        if not self.client:
            return
        dialog = RenameDialog("Rename Agent", agent.name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = dialog.value()
        client = self.client
        self._run_worker(
            lambda: client.update_agent(agent.id, {"name": new_name}),
            lambda _result: self.refresh(),
            label="Renaming Agent…",
        )

    def rename_research(self, agent: Agent, run: Run) -> None:
        current_name = self.database.research_display_name(agent.id, run.id) or (
            f"Research #{(run.local_number or 0):03d}"
        )
        dialog = RenameDialog(
            "Rename Research", current_name, self, context=f"{agent.name} · local name only"
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.database.rename_research(agent.id, run.id, dialog.value())
        self._populate_research()
        if self._current_page[:1] == ("run",) and self._current_page[1:] == (agent.id, run.id):
            self.show_run(agent, run)

    def edit_agent(self, agent: Agent) -> None:
        if not self.client:
            return
        dialog = AgentEditorDialog(agent, self)
        dialog.suggestRequested.connect(lambda payload: self.suggest_keywords(dialog, payload))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        client = self.client
        self._run_worker(
            lambda: client.update_agent(agent.id, dialog.payload()),
            lambda _result: self.refresh(),
            label="Updating Agent…",
        )

    def delete_agent(self, agent: Agent) -> None:
        if not self.client:
            return
        answer = QMessageBox.warning(
            self,
            "Delete Agent",
            "Soft-delete this Agent? Future recurring runs will stop. Previously collected data remains available until purged.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        client = self.client
        self._run_worker(
            lambda: client.delete_agent(agent.id),
            lambda _result: self.refresh(),
            label="Deleting Agent…",
        )

    def _agent_menu(self, point: Any) -> None:
        item = self.agent_list.itemAt(point)
        if not item:
            return
        agent = self.agents.get(str(item.data(Qt.ItemDataRole.UserRole)))
        if not agent:
            return
        menu = QMenu(self)
        copy_action = menu.addAction("Copy Agent ID")
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(agent.id))
        if agent.is_recurring:
            toggle = menu.addAction("Pause" if agent.active else "Resume")
            toggle.triggered.connect(lambda: self.toggle_agent(agent))
        folder_action = menu.addAction("Open Export Folder")
        folder_action.triggered.connect(lambda: open_in_explorer(Path(self.settings.export_folder)))
        menu.addSeparator()
        delete_action = menu.addAction("Delete Agent…")
        delete_action.triggered.connect(lambda: self.delete_agent(agent))
        menu.exec(self.agent_list.mapToGlobal(point))

    def _process_selected(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        self._current_page = ("process", data.get("kind"), data.get("agent_id"), data.get("process_id"))
        self._clear_active_export_view()
        self._clear_agent_selection()
        self._clear_research_selection()
        self._select_process_item(data)
        if data.get("kind") == "server":
            agent = self.agents.get(str(data.get("agent_id")))
            if not agent:
                return
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(35, 30, 35, 30)
            layout.addWidget(section_label("Research Process"))
            title = QLabel(agent.name)
            title.setObjectName("title")
            layout.addWidget(title)
            layout.addWidget(
                muted("Virlo is processing this research. No synthetic percentage is shown.")
            )
            bar = QProgressBar()
            bar.setRange(0, 0)
            layout.addWidget(bar)
            for pending in agent.pending_jobs:
                layout.addWidget(
                    QLabel(f"● {str(pending.get('type', 'Pending job')).replace('_', ' ').title()}")
                )
            layout.addStretch()
            self._show_page(page)
        elif self._open_export_process(data):
            return
        else:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(35, 30, 35, 30)
            layout.addWidget(section_label("Local Process"))
            title = QLabel(str(data.get("label") or "Export"))
            title.setObjectName("title")
            layout.addWidget(title)
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
            layout.addWidget(
                muted(
                    f"Status: {str(data.get('status', 'running')).title()} · "
                    f"Stage: {str(payload.get('stage', 'working')).title()}"
                )
            )
            if "percent" in payload:
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(int(payload["percent"]))
                layout.addWidget(bar)
            layout.addStretch()
            self._show_page(page)

    def start_export(self, agent: Agent, run: Run) -> None:
        if not self.client:
            return
        self.export_cancel = Event()
        process_id = f"export:{agent.id}:{run.id}"
        number = run.local_number or 0
        label = f"Export Research #{number:03d}"
        self.database.upsert_process(
            process_id, "export", label, "running", {"stage": "starting"}
        )
        self._live_export_events[process_id] = []
        self._populate_processes()
        self._show_live_export_view(process_id, agent, run)
        client = self.client

        def do_export(progress: Any = None) -> ExportResult:
            engine = ExportEngine(
                client,
                self.database,
                Path(self.settings.export_folder),
                baseline_sample_size=self.settings.baseline_sample_size,
                progress=progress,
                cancel_event=self.export_cancel,
            )
            return engine.export(agent.id, run.id)

        worker = Worker(do_export, progress=None)
        self.active_workers.add(worker)

        def progress(event: dict[str, Any]) -> None:
            self._live_export_events[process_id].append(event)
            if self._active_export_process_id == process_id and self._active_export_timeline:
                self._active_export_timeline.apply_event(event)
            stage_label = str(event.get("label", "Working"))
            payload: dict[str, Any] = {"stage": stage_label}
            current = event.get("current")
            total = event.get("total")
            if isinstance(current, int) and isinstance(total, int) and total > 0:
                payload["percent"] = min(100, round(current * 100 / total))
            self.database.upsert_process(process_id, "export", label, "running", payload)
            self._populate_processes()

        worker.signals.progress.connect(progress)
        worker.signals.result.connect(
            lambda result: self._export_done(process_id, result, agent, run)
        )
        worker.signals.error.connect(
            lambda error, details: self._export_failed(process_id, error, details)
        )
        worker.signals.finished.connect(lambda: self._worker_finished(worker))
        QThreadPool.globalInstance().start(worker)

    def _current_export_timeline(self, process_id: str) -> ExportTimelineWidget | None:
        if self._active_export_process_id == process_id:
            return self._active_export_timeline
        return None

    def _export_done(
        self, process_id: str, result: ExportResult, agent: Agent, run: Run
    ) -> None:
        self.database.upsert_process(
            process_id, "export", "Export", "complete", {"path": str(result.path)}
        )
        self._live_export_events.pop(process_id, None)
        self._populate_processes()
        timeline = self._current_export_timeline(process_id)
        if timeline is None:
            return
        timeline.stop_timer()
        has_warnings = bool(result.warnings)
        timeline.set_overall_status(
            "Complete with warnings" if has_warnings else "Complete",
            "warning" if has_warnings else "completed",
        )
        summary = build_completion_summary(
            status_text="Export complete with warnings" if has_warnings else "Export complete",
            state="warning" if has_warnings else "completed",
            stats=result.statistics,
            warnings=result.warnings,
        )
        actions = QHBoxLayout()
        open_button = QPushButton("Open Folder")
        open_button.setObjectName("primary")
        open_button.clicked.connect(lambda: open_in_explorer(result.path))
        copy = QPushButton("Copy Dataset Path")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(str(result.dataset_path)))
        report_button = QPushButton("Report")
        report_button.clicked.connect(
            lambda: self.reveal_export_report(
                agent, run, self.database.export_history(agent.id, run.id)[0]
            )
        )
        back = QPushButton("Back to Research")
        back.clicked.connect(lambda: self.show_run(agent, run))
        actions.addWidget(open_button)
        actions.addWidget(copy)
        actions.addWidget(report_button)
        actions.addWidget(back)
        actions.addStretch()
        summary.layout().addLayout(actions)
        timeline.layout().addWidget(summary)
        if self.settings.open_folder_after_export:
            open_in_explorer(result.path)

    def _export_failed(
        self, process_id: str, error: Exception | str, details: str
    ) -> None:
        cancelled = "ExportCancelled" in details
        status = "cancelled" if cancelled else "failed"
        self.database.upsert_process(process_id, "export", "Export", status, {})
        self._live_export_events.pop(process_id, None)
        self._populate_processes()
        if not cancelled:
            logger.error("export failed: %s\n%s", error, details)
        timeline = self._current_export_timeline(process_id)
        if timeline is not None:
            timeline.stop_timer()
            timeline.set_overall_status(
                "Cancelled" if cancelled else "Failed", "neutral" if cancelled else "failed"
            )
        if cancelled:
            self.statusBar().showMessage("Export cancelled", 5000)
        else:
            self.statusBar().showMessage("Export failed — see process view for details", 8000)

    def _open_export_process(self, data: dict[str, Any]) -> bool:
        process_id = str(data.get("process_id") or "")
        if not process_id.startswith("export:"):
            return False
        _, agent_id, run_id = process_id.split(":", 2)
        agent = self.agents.get(agent_id)
        run = next((value for value in self.runs.get(agent_id, []) if value.id == run_id), None)
        if not agent or not run:
            return False
        if str(data.get("status")) == "running":
            self._show_live_export_view(process_id, agent, run)
            return True
        history = self.database.export_history(agent_id, run_id)
        if not history:
            return False
        self.open_export_history(agent, run, history[0])
        return True

    def open_export_history(self, agent: Agent, run: Run, export_record: dict[str, Any]) -> None:
        self._clear_active_export_view()
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(28, 24, 28, 24)
        timeline = ExportTimelineWidget(live=False)
        number = run.local_number or 0
        timeline.set_header(
            f"EXPORT #{export_record['export_number']:03d}", f"Research #{number:03d} · {agent.name}"
        )
        state = RUN_STATUS_STATE.get(str(export_record.get("status", "")).casefold(), "neutral")
        timeline.set_overall_status(str(export_record.get("status", "")).replace("_", " "), state)
        timeline.load_history(self.database.export_stages(export_record["id"]))
        page_layout.addWidget(timeline)
        actions = QHBoxLayout()
        open_button = QPushButton("Open Folder")
        open_button.clicked.connect(
            lambda: open_in_explorer(Path(export_record["path"]))
        )
        actions.addWidget(open_button)
        report_button = QPushButton("Report")
        report_button.clicked.connect(
            lambda: self.reveal_export_report(agent, run, export_record)
        )
        actions.addWidget(report_button)
        actions.addStretch()
        back = QPushButton("Back to Research")
        back.clicked.connect(lambda: self.show_run(agent, run))
        actions.addWidget(back)
        page_layout.addLayout(actions)
        self._show_page(page)

    def _show_live_export_view(self, process_id: str, agent: Agent, run: Run) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(28, 24, 28, 24)
        timeline = ExportTimelineWidget(live=True)
        number = run.local_number or 0
        display_name = self.database.research_display_name(agent.id, run.id)
        subtitle = display_name or f"Research #{number:03d}"
        timeline.set_header(f"EXPORT · RESEARCH #{number:03d}", f"{subtitle} · {agent.name}")
        for event in self._live_export_events.get(process_id, []):
            timeline.apply_event(event)
        if self.export_cancel is not None:
            timeline.cancelRequested.connect(self.export_cancel.set)
        page_layout.addWidget(timeline)
        self._show_page(page)
        self._active_export_timeline = timeline
        self._active_export_process_id = process_id

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.apply_to(self.settings)
        self.settings_store.save(self.settings)
        Path(self.settings.export_folder).mkdir(parents=True, exist_ok=True)
        if dialog.should_replace_key():
            self.connect_api()

    def _show_page(self, page: QWidget) -> None:
        self.detail.addWidget(page)
        self.detail.setCurrentWidget(page)
        for index in range(self.detail.count() - 1, -1, -1):
            widget = self.detail.widget(index)
            if widget not in {self.placeholder, page}:
                self.detail.removeWidget(widget)
                widget.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.ui_settings.setValue("ui/main_window_geometry", self.saveGeometry())
        self.ui_settings.setValue("ui/main_window_state", self.saveState())
        self.ui_settings.setValue("ui/main_splitter", self.main_splitter.saveState())
        self.ui_settings.setValue("ui/main_window_maximized", self.isMaximized())
        self.ui_settings.sync()
        if self.export_cancel:
            self.export_cancel.set()
        if self.client:
            self.client.close()
        super().closeEvent(event)
