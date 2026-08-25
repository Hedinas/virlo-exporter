from __future__ import annotations

from virlo_exporter.config import AppSettings, SettingsStore
from virlo_exporter.storage.database import Database
from virlo_exporter.ui.export_view import ExportTimelineWidget
from virlo_exporter.ui.main_window import MainWindow


class NoKeyStore:
    def get(self) -> str | None:
        return None

    def set(self, value: str) -> None:  # pragma: no cover
        raise AssertionError("not expected in routing tests")

    def delete(self) -> None:  # pragma: no cover
        pass


def _make_window(tmp_path, qapp) -> MainWindow:
    db = Database(tmp_path / "state.db")
    db.cache_agent(
        {
            "id": "agent-1",
            "name": "Raxeko",
            "intent": "x",
            "keywords": ["a"],
            "platforms": ["tiktok"],
            "data_intelligence_enabled": False,
            "meta_ads_enabled": True,
            "english_only": True,
            "is_recurring": False,
        }
    )
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-08-24T20:42:58Z", "status": "completed"}])
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings = AppSettings.defaults()
    settings.export_folder = str(tmp_path / "exports")
    return MainWindow(settings_store, settings, NoKeyStore(), db)


def test_active_process_click_always_opens_the_snake_view_never_legacy(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    process_id = "export:agent-1:run-1"
    window._live_export_events[process_id] = [
        {"stage": "prepare", "label": "Preparing", "status": "running", "sequence": 1},
    ]

    handled = window._open_export_process(
        {"kind": "export", "process_id": process_id, "agent_id": "agent-1", "status": "running"}
    )

    assert handled is True
    assert isinstance(window._active_export_timeline, ExportTimelineWidget)
    assert window._active_export_timeline.stage_order() == ["prepare"]
    assert window.detail.currentWidget() is not window.placeholder


def test_completed_export_process_click_opens_historical_snake_view(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    export_id, export_number = window.database.begin_export(
        "agent-1", "run-1", 1, str(tmp_path / "exports" / "Export_001"), "2026-08-25T10:00:00Z"
    )
    window.database.upsert_export_stage(
        export_id,
        {
            "sequence": 1,
            "stage": "videos",
            "label": "Fetching videos",
            "status": "complete",
            "started_at": "2026-08-25T10:00:00Z",
            "completed_at": "2026-08-25T10:01:00Z",
            "summary": "5,247 records",
        },
    )
    window.database.update_export(
        export_id,
        path=str(tmp_path / "exports" / "Export_001"),
        status="complete",
        completed_at="2026-08-25T10:02:00Z",
        validation="valid",
    )

    handled = window._open_export_process(
        {
            "kind": "export",
            "process_id": "export:agent-1:run-1",
            "agent_id": "agent-1",
            "status": "complete",
        }
    )

    assert handled is True
    # Historical views don't register as the "active live" export.
    assert window._active_export_process_id is None


def test_background_refresh_does_not_disturb_a_live_export_view(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    agent = window.agents["agent-1"]
    process_id = "export:agent-1:run-1"
    window._live_export_events[process_id] = []
    run = window.runs["agent-1"][0]
    window._show_live_export_view(process_id, agent, run)
    assert window._active_export_process_id == process_id
    live_timeline = window._active_export_timeline

    # A periodic background refresh reloading agents must not tear down or
    # replace the live export view that's currently on screen.
    window._populate_agents([dict(agent.raw)])

    assert window._active_export_process_id == process_id
    assert window._active_export_timeline is live_timeline


def test_navigating_away_and_back_replays_the_persisted_event_log(tmp_path, qapp) -> None:
    window = _make_window(tmp_path, qapp)
    agent = window.agents["agent-1"]
    run = window.runs["agent-1"][0]
    process_id = "export:agent-1:run-1"
    window._live_export_events[process_id] = [
        {"stage": "prepare", "label": "Preparing", "status": "running", "sequence": 1},
        {"stage": "prepare", "label": "Preparing", "status": "complete", "sequence": 1, "summary": "ok"},
        {"stage": "videos", "label": "Fetching videos", "status": "running", "sequence": 2, "current": 10, "total": 100},
    ]
    window._show_live_export_view(process_id, agent, run)
    assert window._active_export_timeline.stage_order() == ["prepare", "videos"]

    window.show_agent("agent-1")
    assert window._active_export_timeline is None

    window._open_export_process(
        {"kind": "export", "process_id": process_id, "agent_id": "agent-1", "status": "running"}
    )
    assert window._active_export_timeline is not None
    assert window._active_export_timeline.stage_order() == ["prepare", "videos"]
    assert window._active_export_timeline.stage_status("prepare") == "complete"
    assert window._active_export_timeline.stage_status("videos") == "running"
