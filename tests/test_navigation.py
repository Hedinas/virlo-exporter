from __future__ import annotations

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
