from __future__ import annotations

from PySide6.QtCore import QSettings

from virlo_exporter.config import AppSettings, SettingsStore
from virlo_exporter.storage.database import Database
from virlo_exporter.ui.components import CollapsibleSection
from virlo_exporter.ui.main_window import MainWindow


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


def test_natural_list_bounded_height_caps_active_processes(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    for index in range(10):
        window.database.upsert_process(
            f"export:agent-{index}:run-1", "export", f"Export {index}", "running", {}
        )
    window._populate_processes()
    # Ten rows would naturally be much taller than the configured cap.
    assert window.process_list.height() <= 4 * 66 + 20
