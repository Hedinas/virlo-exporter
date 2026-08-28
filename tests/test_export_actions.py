from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QEvent, QRect
from PySide6.QtWidgets import QLabel, QScrollArea, QToolButton, QWidget

from virlo_exporter.config import AppSettings, SettingsStore
from virlo_exporter.export import report as report_module
from virlo_exporter.storage.database import Database
from virlo_exporter.ui.components import FlowLayout
from virlo_exporter.ui.main_window import MainWindow, ResponsiveColumns


@pytest.fixture(autouse=True)
def close_qt_windows_after_test(qapp):
    yield
    for widget in qapp.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class NoKeyStore:
    def get(self) -> str | None:
        return None

    def set(self, value: str) -> None:  # pragma: no cover
        raise AssertionError

    def delete(self) -> None:  # pragma: no cover
        pass


def _make_window_with_export(tmp_path, qapp, *, status: str = "complete"):
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
        export_id, path=str(export_dir), status=status, completed_at="2026-08-25T10:05:00Z", validation="valid"
    )
    report = report_module.build_report(
        export_row={"export_number": export_number, "research_number": 1, "status": status},
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


def test_delete_sends_directory_to_recycle_bin_keeps_db_row_gone_and_numbering(
    tmp_path, qapp, monkeypatch
) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    assert export_dir.exists()
    window._confirm_delete_export = lambda *args: True
    sent: list[str] = []
    monkeypatch.setattr("virlo_exporter.ui.main_window.delete_directory", lambda path: sent.append(str(path)))

    window.delete_export_to_recycle_bin(agent, run, export_record)

    assert sent == [str(export_dir)]  # sent to Recycle Bin, not shutil.rmtree'd in-process
    assert window.database.export_history("agent-1", "run-1") == []
    _, next_number = window.database.begin_export("agent-1", "run-1", 1, "p", "2026-01-01")
    assert next_number == 2  # export #1 was deleted, but its number is never reissued


def test_delete_is_refused_while_export_is_running(tmp_path, qapp, monkeypatch) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    export_record = dict(export_record)
    export_record["status"] = "running"
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    window.delete_export_to_recycle_bin(agent, run, export_record)

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


def test_completion_overlay_shows_real_warning_count_not_raw_string_count(tmp_path, qapp, monkeypatch) -> None:
    from PySide6.QtWidgets import QLabel

    from virlo_exporter.export.engine import ExportResult
    from virlo_exporter.ui.main_window import ExportCompletionOverlay

    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    process_id = f"export:{agent.id}:{run.id}"
    window._live_export_events[process_id] = []
    monkeypatch.setattr("virlo_exporter.ui.main_window.open_in_explorer", lambda path: None)

    # Raw manifest warnings (dataset audit trail) has entries, but the real
    # (structured) warning count -- what the completion overlay must use -- is 0.
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

    overlays = window.centralWidget().findChildren(ExportCompletionOverlay)
    assert len(overlays) == 1
    title_text = next(
        label.text() for label in overlays[0].findChildren(QLabel) if label.objectName() == "completionTitle"
    )
    assert title_text == "✓ EXPORT COMPLETE"  # not warnings/failed framing


def _report_button(card) -> QToolButton:
    return next(
        button
        for button in card.findChildren(QToolButton)
        if button.toolTip() == "Report"
    )


def test_report_action_disabled_for_a_fully_clean_export(tmp_path, qapp) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(
        tmp_path, qapp, status="complete"
    )
    card = window._export_card(agent, run, export_record)
    button = _report_button(card)
    assert not button.isEnabled()
    assert button.toolTip() == "Report"


def test_report_action_enabled_for_cancelled_warning_and_failed_exports(tmp_path, qapp) -> None:
    for status in ("cancelled", "complete_with_warnings", "failed"):
        window, agent, run, export_record, export_dir = _make_window_with_export(
            tmp_path / status, qapp, status=status
        )
        card = window._export_card(agent, run, export_record)
        button = _report_button(card)
        assert button.isEnabled(), f"Report must be enabled for status={status}"
        assert button.toolTip() == "Report"


def test_cancel_export_reacts_instantly_and_preserves_route(tmp_path, qapp) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(
        tmp_path, qapp, status="complete"
    )
    window.export_cancel = Event()
    process_id = f"export:{agent.id}:{run.id}"
    window._live_export_events[process_id] = []
    window._show_live_export_view(process_id, agent, run)
    timeline = window._active_export_timeline
    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running"})
    route_before = window._current_page

    window._cancel_export(process_id, timeline)

    # All synchronous -- none of this waits for a background worker.
    assert window.export_cancel.is_set()
    assert timeline.stage_status("videos") == "cancelled"
    assert not timeline.cancel_button.isEnabled()
    assert process_id in window._cancelling_process_ids
    assert window._current_page == route_before  # cancel never navigates away

    # The worker's eventual confirmation clears the transient cancelling flag.
    window._export_failed(process_id, Exception(), "ExportCancelled")
    assert process_id not in window._cancelling_process_ids
    assert window._current_page == route_before


def test_cancelled_export_card_shows_interrupted_context_not_zeroed_metrics(tmp_path, qapp) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(
        tmp_path, qapp, status="cancelled"
    )
    report = report_module.build_report(
        export_row={"export_number": export_record["export_number"], "research_number": 1, "status": "cancelled"},
        stages=[],
        agent_name="Raxeko",
        summary={
            "videos": 0,
            "warnings": 0,
            "paid_api_calls": 0,
            "reason": "user_cancelled",
            "interrupted_stage": "videos",
            "interrupted_page": 14,
        },
    )
    report_module.write_report(export_dir, report)
    export_record = dict(export_record)
    export_record["started_at"] = "2026-08-26T05:44:00Z"
    export_record["completed_at"] = "2026-08-26T05:45:37Z"

    card = window._export_card(agent, run, export_record)
    labels = [label.text() for label in card.findChildren(QLabel)]
    assert "VIDEOS" not in labels  # no meaningless "Videos 0" metric tile
    assert any("1m 37s" in text for text in labels)
    assert any(text == "Videos" for text in labels)  # the interrupted-stage value itself


def test_complete_export_card_uses_compact_useful_hierarchy(tmp_path, qapp) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    report = report_module.build_report(
        export_row={
            "export_number": export_record["export_number"],
            "research_number": 1,
            "status": "complete",
        },
        stages=[],
        agent_name="Raxeko",
        summary={
            "dataset_bytes": 4096,
            "raw_bytes": 8192,
            "videos": 100,
            "high_signal_videos": 17,
        },
    )
    report_module.write_report(export_dir, report)
    export_record = {
        **export_record,
        "started_at": "2026-08-26T05:44:00Z",
        "completed_at": "2026-08-26T05:45:37Z",
    }

    card = window._export_card(agent, run, export_record)
    labels = card.findChildren(QLabel)
    texts = [label.text() for label in labels]

    assert {"AI DATASET", "RAW DATA", "VIDEOS", "DURATION", "HIGH SIGNAL"} <= set(texts)
    assert {"4.0 KB", "8.0 KB", "100", "1m 37s", "17"} <= set(texts)
    assert next(label for label in labels if label.text() == "Export #001").objectName() == (
        "exportCardTitle"
    )
    assert all(
        label.objectName() == "exportMetricValue"
        for label in labels
        if label.text() in {"4.0 KB", "8.0 KB", "100", "1m 37s", "17"}
    )


def test_export_cards_in_the_same_flow_row_receive_equal_height(tmp_path, qapp) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    complete = window._export_card(agent, run, export_record)
    interrupted_record = {**export_record, "status": "cancelled"}
    interrupted = window._export_card(agent, run, interrupted_record)
    host = QWidget()
    flow = FlowLayout(equal_row_heights=True, spacing=14)
    host.setLayout(flow)
    flow.addWidget(complete)
    flow.addWidget(interrupted)

    flow.setGeometry(QRect(0, 0, 1100, 500))

    assert complete.y() == interrupted.y()
    assert complete.height() == interrupted.height()
    assert complete.maximumWidth() > interrupted.maximumWidth()


def test_research_run_card_is_bounded_width(tmp_path, qapp) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    card = window._run_card(agent, run)
    assert card.maximumWidth() <= 520


def test_research_run_card_uses_clickable_name_without_repeated_identity(
    tmp_path, qapp
) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    window.database.rename_research(agent.id, run.id, "First run")
    run.execution_time_ms = 97_000

    card = window._run_card(agent, run)
    labels = card.findChildren(QLabel)
    texts = [label.text() for label in labels]

    assert next(label for label in labels if label.text() == "First run").objectName() == (
        "researchLink"
    )
    assert not any("Research #001 · Raxeko" in text for text in texts)
    assert "EXPORTS" in texts
    assert "DURATION" in texts
    assert "1m 37s" in texts


def test_agent_intent_keeps_full_text_and_wraps_at_narrow_width(tmp_path, qapp) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    agent.intent = " ".join(["A complete research intent that must remain visible."] * 12)

    window.resize(940, 700)
    window.show()
    window.show_agent(agent.id)
    qapp.processEvents()
    columns = window.detail.currentWidget().findChild(ResponsiveColumns)
    intent = next(
        label
        for label in window.detail.currentWidget().findChildren(QLabel)
        if label.objectName() == "bodyText"
    )

    assert columns is not None
    assert columns.is_stacked()
    assert intent.text() == agent.intent
    assert intent.wordWrap()
    assert intent.heightForWidth(220) > intent.fontMetrics().height() * 3
    assert intent.height() >= intent.heightForWidth(intent.width())


def test_research_header_actions_stay_inside_narrow_viewport(tmp_path, qapp) -> None:
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)

    window.resize(940, 700)
    window.show()
    window.show_run(agent, run)
    qapp.processEvents()
    page = window.detail.currentWidget()
    scroll = page.findChild(QScrollArea)
    assert scroll is not None
    assert scroll.widget().width() <= scroll.viewport().width()

    action_buttons = [
        button
        for button in page.findChildren(QToolButton)
        if button.toolTip() in {"Copy ID", "Open Folder", "Delete"}
        and button.geometry().y() < 100
    ]
    assert {button.toolTip() for button in action_buttons} == {
        "Copy ID",
        "Open Folder",
        "Delete",
    }
    for button in action_buttons:
        right_edge = button.mapTo(scroll.viewport(), button.rect().topRight()).x()
        assert right_edge <= scroll.viewport().width()


def test_corrupt_report_file_degrades_gracefully_instead_of_crashing(tmp_path, qapp) -> None:
    # Error-matrix case: a report file that exists but is not valid JSON
    # (e.g. truncated by an external disk issue, or hand-edited) must never
    # crash the app -- it should be treated the same as a missing report.
    window, agent, run, export_record, export_dir = _make_window_with_export(tmp_path, qapp)
    (export_dir / "EXPORT_REPORT.json").write_text("{not valid json!!", encoding="utf-8")

    payload = window._read_export_report_payload(export_record["path"])
    assert payload == {}
    summary = window._read_export_summary(export_record["path"])
    assert summary == {}

    # The export card itself must still render without raising.
    card = window._export_card(agent, run, export_record)
    assert card is not None
