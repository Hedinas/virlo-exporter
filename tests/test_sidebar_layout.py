from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QToolButton

from virlo_exporter.config import AppSettings, SettingsStore
from virlo_exporter.models import Agent
from virlo_exporter.storage.database import Database
from virlo_exporter.ui.components import CollapsibleSection
from virlo_exporter.ui.main_window import AgentRow, MainWindow, ProcessRow, ResearchRow


def test_active_process_row_animates_its_perimeter(qapp) -> None:
    row = ProcessRow("Export #007", "Fetching videos", active=True)
    assert row._timer is not None  # noqa: SLF001
    assert row._timer.isActive()  # noqa: SLF001

    start = row._offset  # noqa: SLF001
    row._advance()  # noqa: SLF001
    assert row._offset != start  # noqa: SLF001
    assert 0.0 <= row._offset < 1.0  # noqa: SLF001


def test_inactive_process_row_does_not_animate(qapp) -> None:
    row = ProcessRow("Research #003 · Raxeko", "Processing", active=False)
    assert row._timer is None  # noqa: SLF001


class NoKeyStore:
    def get(self) -> str | None:
        return None

    def set(self, value: str) -> None:  # pragma: no cover
        raise AssertionError

    def delete(self) -> None:  # pragma: no cover
        pass


def _make_window(tmp_path, qapp) -> MainWindow:
    db = Database(tmp_path / "state.db")
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings = AppSettings.defaults()
    settings.export_folder = str(tmp_path / "exports")
    return MainWindow(settings_store, settings, NoKeyStore(), db)


def test_active_processes_is_pinned_and_not_collapsible(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    assert not hasattr(window, "processes_section")
    # process_list must not live inside any CollapsibleSection.
    parent = window.process_list.parentWidget()
    while parent is not None:
        assert not isinstance(parent, CollapsibleSection)
        parent = parent.parentWidget()


def test_active_processes_panel_is_a_sibling_of_the_scroll_area_not_inside_it(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    # Agents/Research still live inside CollapsibleSections.
    agents_parent = window.agent_list.parentWidget()
    found_section = False
    while agents_parent is not None:
        if isinstance(agents_parent, CollapsibleSection):
            found_section = True
            break
        agents_parent = agents_parent.parentWidget()
    assert found_section


def test_sidebar_collapse_state_persists_across_reconstruction(tmp_path, qapp) -> None:
    settings = QSettings("Virlo Exporter Tests", "test_sidebar_layout")
    settings.setValue("ui/sidebar/agents_expanded", False)
    settings.setValue("ui/sidebar/research_expanded", True)
    settings.sync()
    original_org = qapp.organizationName()
    original_app = qapp.applicationName()
    qapp.setOrganizationName("Virlo Exporter Tests")
    qapp.setApplicationName("test_sidebar_layout")
    try:
        window = _make_window(tmp_path, qapp)
        assert window.agents_section.is_expanded() is False
        assert window.research_section.is_expanded() is True
    finally:
        settings.remove("ui/sidebar/agents_expanded")
        settings.remove("ui/sidebar/research_expanded")
        qapp.setOrganizationName(original_org)
        qapp.setApplicationName(original_app)


def test_active_processes_scroll_is_bounded_when_many_rows_exist(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    for index in range(10):
        window.database.upsert_process(
            f"export:agent-{index}:run-1", "export", f"Export {index}", "running", {}
        )
    window._populate_processes()
    # The pinned panel is bounded by its outer scroll area, not by
    # artificially capping the row list's own natural height.
    assert window.process_scroll.maximumHeight() <= 4 * 66
    assert window.process_list.count() == 10


def test_agents_section_header_toggles_without_a_separate_chevron_button(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    assert not hasattr(window.agents_section, "chevron")
    before = window.agents_section.is_expanded()
    window.agents_section.header.clicked.emit()
    assert window.agents_section.is_expanded() != before
    window.agents_section.header.clicked.emit()
    assert window.agents_section.is_expanded() == before


def test_agent_sidebar_row_uses_rename_pencil_and_compact_overflow_menu(qapp) -> None:
    def callback() -> None:
        pass

    row = AgentRow(
        Agent(id="agent-1", name="Raxeko"),
        "Active",
        callback,
        callback,
        callback,
        callback,
        callback,
    )
    buttons = row.findChildren(QToolButton)
    assert [button.objectName() for button in buttons] == [
        "pencilButton",
        "overflowButton",
    ]
    overflow = buttons[-1]
    assert [action.text() for action in overflow.menu().actions()] == [
        "Edit",
        "Copy ID",
        "Open Folder",
        "Delete",
    ]


def test_research_sidebar_row_uses_rename_pencil_and_compact_overflow_menu(qapp) -> None:
    def callback() -> None:
        pass

    row = ResearchRow(
        "First run",
        "Raxeko",
        "Aug 24 · 4:42 PM",
        callback,
        callback,
        callback,
        callback,
        callback,
    )
    buttons = row.findChildren(QToolButton)
    assert [button.objectName() for button in buttons] == [
        "pencilButton",
        "overflowButton",
    ]
    assert [action.text() for action in buttons[-1].menu().actions()] == [
        "Open Research",
        "Copy ID",
        "Open Folder",
        "Delete",
    ]


def test_global_research_list_includes_every_agents_runs(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    for index in range(3):
        window.database.cache_agent(
            {
                "id": f"agent-{index}",
                "name": f"Agent {index}",
                "intent": "x",
                "keywords": [],
                "platforms": ["tiktok"],
                "is_recurring": False,
            }
        )
        for run_index in range(5):
            window.database.assign_runs(
                f"agent-{index}",
                [{"id": f"run-{index}-{run_index}", "started_at": "2026-08-24T20:42:58Z", "status": "completed"}],
            )
    window._load_cached_agents()
    # 3 agents x 5 runs = 15 total; the old RECENT_RESEARCH_LIMIT (12) bug
    # would have silently dropped 3 of them from the sidebar.
    assert window.research_list.count() == 15
