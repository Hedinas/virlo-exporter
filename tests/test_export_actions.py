from __future__ import annotations

from pathlib import Path

from virlo_exporter.config import AppSettings, SettingsStore
from virlo_exporter.export import report as report_module
from virlo_exporter.storage.database import Database
from virlo_exporter.ui.main_window import MainWindow


class NoKeyStore:
    def get(self) -> str | None:
        return None

    def set(self, value: str) -> None:  # pragma: no cover
        raise AssertionError

    def delete(self) -> None:  # pragma: no cover
        pass


def _make_window_with_export(tmp_path, qapp):
    db = Database(tmp_path / "state.db")
    db.cache_agent(
        {
            "id": "agent-1",
            "name": "Raxeko",
            "intent": "x",
            "keywords": [],
            "platforms": ["tiktok"],
            "is_recurring": False,
        }
    )
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-08-24T20:42:58Z", "status": "completed"}])
    export_dir = tmp_path / "exports" / "Raxeko" / "Research_001" / "Export_001"
    export_dir.mkdir(parents=True)
    export_id, export_number = db.begin_export(
        "agent-1", "run-1", 1, str(export_dir), "2026-08-25T10:00:00Z"
    )
    db.update_export(
        export_id, path=str(export_dir), status="complete", completed_at="2026-08-25T10:05:00Z", validation="valid"
    )
    report = report_module.build_report(
        export_row={"export_number": export_number, "research_number": 1, "status": "complete"},
        stages=[],
        agent_name="Raxeko",
        summary={"videos": 100, "warnings": 0, "paid_api_calls": 0},
    )
    report_module.write_report(export_dir, report)

    settings_store = SettingsStore(tmp_path / "settings.json")
    settings = AppSettings.defaults()
    settings.export_folder = str(tmp_path / "exports")
    window = MainWindow(settings_store, settings, NoKeyStore(), db)
    agent = window.agents["agent-1"]
    run = window.runs["agent-1"][0]
    export_record = db.export_history("agent-1", "run-1")[0]
    return window, agent, run, export_record, export_dir


def test_report_action_targets_the_exact_json_file(tmp_path, qapp, monkeypatch) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    opened: list[Path] = []
    monkeypatch.setattr("virlo_exporter.ui.main_window.open_in_explorer", lambda path: opened.append(path))

    window.open_export_report(agent, run, export_record)

    assert len(opened) == 1
    assert opened[0] == export_dir / report_module.REPORT_FILENAME


def test_show_file_action_reveals_the_exact_json_file(tmp_path, qapp, monkeypatch) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    revealed: list[Path] = []
    monkeypatch.setattr("virlo_exporter.ui.main_window.reveal_in_explorer", lambda path: revealed.append(path))

    window.reveal_export_report(agent, run, export_record)

    assert len(revealed) == 1
    assert revealed[0] == export_dir / report_module.REPORT_FILENAME


def test_open_folder_targets_the_exact_export_directory_not_documents(tmp_path, qapp) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    assert Path(export_record["path"]) == export_dir
    assert export_dir.name.startswith("Export_")


def test_permanent_delete_removes_directory_db_row_and_keeps_numbering(tmp_path, qapp) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    assert export_dir.exists()
    window._confirm_delete_export = lambda *args: True

    window.delete_export_permanently(agent, run, export_record)

    assert not export_dir.exists()
    assert window.database.export_history("agent-1", "run-1") == []
    _, next_number = window.database.begin_export("agent-1", "run-1", 1, "p", "2026-01-01")
    assert next_number == 2  # export #1 was deleted, but its number is never reissued


def test_delete_is_refused_while_export_is_running(tmp_path, qapp, monkeypatch) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    export_record = dict(export_record)
    export_record["status"] = "running"
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    window.delete_export_permanently(agent, run, export_record)

    assert export_dir.exists()  # nothing was touched
    assert window.database.export_history("agent-1", "run-1")


def test_export_card_shows_files_missing_when_directory_is_gone(tmp_path, qapp) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    import shutil

    shutil.rmtree(export_dir)

    from PySide6.QtWidgets import QLabel

    card = window._export_card(agent, run, export_record)
    labels = [label.text() for label in card.findChildren(QLabel)]
    assert any("Files missing" in text for text in labels)


def test_completion_dialog_shows_real_warning_count_not_raw_string_count(tmp_path, qapp, monkeypatch) -> None:
    from virlo_exporter.export.engine import ExportResult
    from virlo_exporter.ui.main_window import ExportCompletionDialog

    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    process_id = f"export:{agent.id}:{run.id}"
    window._live_export_events[process_id] = []

    shown: list[ExportCompletionDialog] = []
    monkeypatch.setattr(ExportCompletionDialog, "exec", lambda self: shown.append(self))
    monkeypatch.setattr("virlo_exporter.ui.main_window.open_in_explorer", lambda path: None)

    # Raw manifest warnings (dataset audit trail) has entries, but the real
    # (structured) warning count -- what the completion dialog must use -- is 0.
    result = ExportResult(
        path=export_dir,
        dataset_path=export_dir / "VIRLO_AI_DATASET.json",
        complete=True,
        warnings=["Duplicate videos id skipped: a", "Duplicate videos id skipped: b"],
        manifest={},
        export_id=export_record["id"],
        export_number=export_record["export_number"],
        research_number=1,
        statistics={"warnings": 0, "videos": 100, "high_signal": 10, "baseline": 5, "paid_api_calls": 0},
    )

    window._export_done(process_id, result, agent, run)

    assert len(shown) == 1
    dialog = shown[0]
    assert dialog.windowTitle() == "Export complete"  # not "Export failed"/warnings framing
