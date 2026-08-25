from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QWidget

from virlo_exporter.ui.export_view import ExportTimelineWidget, SnakeLayout, StageBlock


def test_stages_appear_only_once_started(qapp) -> None:
    timeline = ExportTimelineWidget(live=True)
    assert timeline.stage_order() == []
    timeline.apply_event({"stage": "prepare", "label": "Preparing", "status": "running"})
    assert timeline.stage_order() == ["prepare"]
    # A stage that hasn't been reported yet must not exist as a block.
    assert timeline.stage_status("videos") is None
    timeline.apply_event({"stage": "prepare", "label": "Preparing", "status": "complete"})
    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running"})
    assert timeline.stage_order() == ["prepare", "videos"]


def test_stage_order_is_preserved_across_updates(qapp) -> None:
    timeline = ExportTimelineWidget(live=True)
    for stage in ["prepare", "metadata", "videos", "slideshows"]:
        timeline.apply_event({"stage": stage, "label": stage, "status": "running"})
    # Re-applying an update to an earlier stage must not reorder it.
    timeline.apply_event({"stage": "prepare", "label": "prepare", "status": "complete"})
    assert timeline.stage_order() == ["prepare", "metadata", "videos", "slideshows"]


def test_warning_state_is_preserved(qapp) -> None:
    timeline = ExportTimelineWidget(live=True)
    timeline.apply_event({"stage": "sounds", "label": "Fetching sounds", "status": "running"})
    timeline.apply_event(
        {"stage": "sounds", "label": "Fetching sounds", "status": "warning", "summary": "unavailable"}
    )
    assert timeline.stage_status("sounds") == "warning"


def test_failed_stage_shows_failure_panel_and_stays_last(qapp) -> None:
    timeline = ExportTimelineWidget(live=True)
    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running"})
    timeline.apply_event(
        {
            "stage": "videos",
            "label": "Fetching videos",
            "status": "failed",
            "summary": "Required resource failed",
            "detail": "trace...",
        }
    )
    assert timeline.stage_status("videos") == "failed"
    assert timeline._failure_panel.isVisibleTo(timeline)  # noqa: SLF001 - white-box check
    assert "Required resource failed" in timeline._failure_summary.text()  # noqa: SLF001


def test_real_percentage_only_shown_when_total_known(qapp) -> None:
    timeline = ExportTimelineWidget(live=True)
    timeline.apply_event(
        {"stage": "videos", "label": "Fetching videos", "status": "running", "current": 1800, "total": 5247}
    )
    block = timeline._blocks["videos"]  # noqa: SLF001 - white-box check
    assert block.percent_label.text() == "34%"

    timeline.apply_event({"stage": "sounds", "label": "Fetching sounds", "status": "running", "current": 40})
    sounds_block = timeline._blocks["sounds"]  # noqa: SLF001
    assert sounds_block.percent_label.text() == ""
    assert "40" in sounds_block.detail_label.text()


def test_historical_view_loads_all_stages_without_animation(qapp) -> None:
    timeline = ExportTimelineWidget(live=False)
    rows = [
        {"stage": "prepare", "label": "Preparing", "status": "complete", "summary": "ok"},
        {"stage": "videos", "label": "Fetching videos", "status": "complete", "summary": "5,247 records"},
        {"stage": "sounds", "label": "Fetching sounds", "status": "warning", "summary": "unavailable"},
    ]
    timeline.load_history(rows)
    assert timeline.stage_order() == ["prepare", "videos", "sounds"]
    assert timeline.stage_status("prepare") == "complete"
    assert timeline.stage_status("videos") == "complete"
    assert timeline.stage_status("sounds") == "warning"


def test_fatal_failure_stops_persisting_later_stages(tmp_path) -> None:
    from virlo_exporter.api.errors import VirloError
    from virlo_exporter.api.pagination import PageResult
    from virlo_exporter.export.engine import ExportEngine, ExportFatalError
    from virlo_exporter.storage.database import Database

    class FailingFakeClient:
        base_url = "https://api.virlo.ai/v1"

        def get_agent(self, agent_id: str) -> dict:
            return {"data": {"id": agent_id, "name": "Test", "data_intelligence_enabled": False}}

        def get_run(self, agent_id: str, run_id: str) -> dict:
            return {"data": {"id": run_id, "agent_id": agent_id, "status": "completed"}}

        def list_runs(self, agent_id: str) -> PageResult:
            return PageResult([{"id": "run-1", "agent_id": agent_id}], 1)

        def get_resource(self, agent_id: str, resource: str, **_kwargs) -> PageResult:
            if resource == "videos":
                raise VirloError("videos is unavailable", status_code=503)
            return PageResult([], 1)

    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    engine = ExportEngine(FailingFakeClient(), db, tmp_path / "exports")
    export_id = None
    try:
        engine.export("agent-1", "run-1")
    except ExportFatalError:
        export_id = db.export_history("agent-1", "run-1")[0]["id"]
    assert export_id is not None
    stages = {row["stage"] for row in db.export_stages(export_id)}
    assert "videos" in stages
    # Nothing later in RESOURCE_ORDER should ever have started.
    later_stages = set(ExportEngine.RESOURCE_ORDER[ExportEngine.RESOURCE_ORDER.index("videos") + 1 :])
    assert not (later_stages & stages)


def test_snake_layout_alternates_row_direction(qapp) -> None:
    host = QWidget()
    layout = SnakeLayout(host, spacing=10)
    host.setLayout(layout)
    blocks = [StageBlock(f"stage{i}", f"Stage {i}") for i in range(6)]
    for block in blocks:
        layout.addWidget(block)
    # Three columns fit: 3 * (176 + 10) - 10 = 548
    host.setGeometry(QRect(0, 0, 548, 400))
    layout.setGeometry(QRect(0, 0, 548, 400))

    row0 = [block.geometry().x() for block in blocks[0:3]]
    row1 = [block.geometry().x() for block in blocks[3:6]]
    assert row0 == sorted(row0)  # left to right
    assert row1 == sorted(row1, reverse=True)  # right to left
    assert blocks[0].geometry().y() < blocks[3].geometry().y()
