from __future__ import annotations

from PySide6.QtCore import Qt

from virlo_exporter.config import AppSettings, SettingsStore
from virlo_exporter.storage.database import Database
from virlo_exporter.ui.main_window import MainWindow


class NoKeyStore:
    def get(self) -> str | None:
        return None

    def set(self, value: str) -> None:  # pragma: no cover - unused in tests
        raise AssertionError("not expected in navigation tests")

    def delete(self) -> None:  # pragma: no cover - unused in tests
        pass


def _make_window(tmp_path, qapp) -> MainWindow:
    db = Database(tmp_path / "state.db")
    db.cache_agent(
        {
            "id": "agent-1",
            "name": "Raxeko",
            "intent": "Find viral collectibles",
            "keywords": ["a", "b"],
            "platforms": ["tiktok"],
            "data_intelligence_enabled": True,
            "meta_ads_enabled": True,
            "english_only": True,
            "is_recurring": False,
        }
    )
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-08-24T20:42:58Z", "status": "completed"}])
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings = AppSettings.defaults()
    settings.export_folder = str(tmp_path / "exports")
    window = MainWindow(settings_store, settings, NoKeyStore(), db)
    return window


def test_direct_navigation_agent_to_research_and_back(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    agent = window.agents["agent-1"]
    run = window.runs["agent-1"][0]

    window.show_agent("agent-1")
    assert window._current_page == ("agent", "agent-1")
    assert window.agent_list.currentItem() is not None

    window.show_run(agent, run)
    assert window._current_page == ("run", "agent-1", run.id)
    # Opening Research must clear the Agent row's highlight, not layer on top of it.
    assert window.agent_list.currentItem() is None
    assert window.research_list.currentItem() is not None

    # Sidebar navigation is direct: going back to the Agent does not require
    # a "Back" button and does not depend on having visited Research first.
    window.show_agent("agent-1")
    assert window._current_page == ("agent", "agent-1")
    assert window.research_list.currentItem() is None
    assert window.agent_list.currentItem() is not None


def test_hide_research_locally_removes_it_and_returns_to_agent(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    agent = window.agents["agent-1"]
    run = window.runs["agent-1"][0]
    window.show_run(agent, run)
    window._confirm_hide_research = lambda *args: True

    window.hide_research_locally(agent, run)

    assert window.database.is_research_hidden("agent-1", run.id)
    assert run.id not in [value.id for value in window.runs.get("agent-1", [])]
    assert window._current_page == ("agent", "agent-1")


def test_declining_hide_research_confirmation_keeps_it(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    agent = window.agents["agent-1"]
    run = window.runs["agent-1"][0]
    window._confirm_hide_research = lambda *args: False

    window.hide_research_locally(agent, run)

    assert not window.database.is_research_hidden("agent-1", run.id)
    assert run.id in [value.id for value in window.runs.get("agent-1", [])]


def test_process_row_selection_survives_background_refresh(tmp_path, qapp) -> None:
    # Reproduces a real bug: the sidebar stored the full merged process
    # payload as item data but compared it against a bare selection key on
    # every rebuild, so `==` was always False and the highlighted process
    # row silently lost its selection on every periodic refresh.
    window = _make_window(tmp_path, qapp)
    agent = window.agents["agent-1"]
    run = window.runs["agent-1"][0]
    process_id = f"export:{agent.id}:{run.id}"
    window.database.upsert_process(process_id, "export", "Export", "running", {})
    window._populate_processes()
    key = {"kind": "local", "process_id": process_id}
    window._select_process_item(key)
    assert window.process_list.currentItem() is not None

    # Simulate a periodic background refresh rebuilding the sidebar list.
    window._populate_processes()

    current = window.process_list.currentItem()
    assert current is not None
    data = current.data(Qt.ItemDataRole.UserRole)
    assert data.get("process_id") == process_id


def test_restore_current_page_reopens_live_process_view_after_refresh(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    agent = window.agents["agent-1"]
    run = window.runs["agent-1"][0]
    process_id = f"export:{agent.id}:{run.id}"
    window.database.upsert_process(process_id, "export", "Export", "running", {})
    window._live_export_events[process_id] = []
    window._populate_processes()
    key = {"kind": "local", "process_id": process_id}
    window._select_process_item(key)
    window._process_selected(window.process_list.currentItem())
    assert window._current_page[0] == "process"

    # A background refresh must reopen the same live process view, not
    # strand the page or silently bounce to Agent/Research.
    window._restore_current_page()

    assert window._active_export_process_id == process_id


def test_agent_row_does_not_spontaneously_highlight_while_viewing_research(tmp_path, qapp) -> None:
    # Reproduces a real bug: selected_agent_id stays set to the owning agent
    # while a Research/Run page is open (show_run needs that for "New
    # Research" etc.), but a periodic background refresh re-rendering the
    # Agent list was using that same stale id to re-highlight the Agent row
    # even though the user was looking at Research, not the Agent page.
    window = _make_window(tmp_path, qapp)
    agent = window.agents["agent-1"]
    run = window.runs["agent-1"][0]
    window.show_run(agent, run)
    assert window.agent_list.currentItem() is None

    window._populate_agents([dict(agent.raw)])

    assert window.agent_list.currentItem() is None


def test_detail_scroll_state_survives_a_page_rebuild(tmp_path, qapp) -> None:
    # show_agent/show_run fully rebuild their page from scratch on every
    # call, including on every periodic background refresh -- which used to
    # silently reset scroll position (and the independently-scrolling
    # Keywords list) back to the top every time.
    from PySide6.QtWidgets import QListWidget, QScrollArea, QVBoxLayout, QWidget

    window = _make_window(tmp_path, qapp)

    old_page = QWidget()
    old_layout = QVBoxLayout(old_page)
    old_scroll = QScrollArea()
    old_layout.addWidget(old_scroll)
    old_keywords = QListWidget()
    old_keywords.setObjectName("keywordDetailList")
    old_layout.addWidget(old_keywords)
    window.detail.addWidget(old_page)
    window.detail.setCurrentWidget(old_page)
    old_scroll.verticalScrollBar().setRange(0, 500)
    old_scroll.verticalScrollBar().setValue(120)
    old_keywords.verticalScrollBar().setRange(0, 200)
    old_keywords.verticalScrollBar().setValue(45)

    state = window._capture_detail_scroll_state()
    assert state == {"page": 120, "keywords": 45}

    new_page = QWidget()
    new_layout = QVBoxLayout(new_page)
    new_scroll = QScrollArea()
    new_scroll.verticalScrollBar().setRange(0, 500)
    new_layout.addWidget(new_scroll)
    new_keywords = QListWidget()
    new_keywords.setObjectName("keywordDetailList")
    new_keywords.verticalScrollBar().setRange(0, 200)
    new_layout.addWidget(new_keywords)
    window.detail.addWidget(new_page)
    window.detail.setCurrentWidget(new_page)

    # Apply directly rather than going through the QTimer.singleShot(0, ...)
    # deferral _restore_detail_scroll_state schedules in production -- that
    # requires pumping the real Qt event loop, which is unnecessary here and
    # (via qapp.processEvents()) picks up unrelated deferred cleanup queued
    # by every other widget the test session has created.
    window._apply_detail_scroll_state(state)

    assert new_scroll.verticalScrollBar().value() == 120
    assert new_keywords.verticalScrollBar().value() == 45


def test_background_refresh_does_not_force_navigation_away_from_research(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    agent = window.agents["agent-1"]
    run = window.runs["agent-1"][0]
    window.show_run(agent, run)
    assert window._current_page == ("run", "agent-1", run.id)

    # Simulate what happens after a periodic background refresh reloads agents:
    # the previously-open Research Detail page must stay open, not bounce back
    # to Agent Detail just because selected_agent_id is set.
    window._populate_agents([dict(agent.raw)])
    assert window._current_page == ("run", "agent-1", run.id)
    assert window.research_list.currentItem() is not None
    assert window.agent_list.currentItem() is None
