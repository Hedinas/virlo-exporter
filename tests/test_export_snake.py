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
    assert block.status_box.text() == "34%"

    timeline.apply_event({"stage": "sounds", "label": "Fetching sounds", "status": "running", "current": 40})
    sounds_block = timeline._blocks["sounds"]  # noqa: SLF001
    # No real percent known yet -- the status box shows an activity spinner
    # frame, never a bare/empty percent.
    from virlo_exporter.ui.export_view import SPINNER_FRAMES

    assert sounds_block.status_box.text() in SPINNER_FRAMES
    assert "40" in sounds_block.detail_label.text()


def test_percent_never_moves_backward_when_total_grows(qapp) -> None:
    # Reproduces the real "Sounds" bug: a growing/re-estimated total made
    # current/total drop between two consecutive progress events even
    # though current itself only ever increased.
    timeline = ExportTimelineWidget(live=True)
    timeline.apply_event(
        {"stage": "sounds", "label": "Fetching sounds", "status": "running", "current": 50, "total": 100}
    )
    block = timeline._blocks["sounds"]  # noqa: SLF001 - white-box check
    assert block.status_box.text() == "50%"

    timeline.apply_event(
        {"stage": "sounds", "label": "Fetching sounds", "status": "running", "current": 60, "total": 200}
    )
    # Raw ratio here is 30%, lower than the 50% already shown -- the
    # displayed value must never regress.
    assert block.status_box.text() == "50%"


def test_percent_never_reaches_100_while_still_running(qapp) -> None:
    # Reproduces the real "Hashtags/Hooks" bug: an optimistic early total
    # let current reach (or exceed) it while the stage was still running,
    # showing a fake "done" state before the stage actually finished.
    timeline = ExportTimelineWidget(live=True)
    timeline.apply_event(
        {"stage": "hashtags", "label": "Fetching hashtags", "status": "running", "current": 100, "total": 100}
    )
    block = timeline._blocks["hashtags"]  # noqa: SLF001 - white-box check
    assert block.status_box.text() == "99%"

    timeline.apply_event(
        {"stage": "hashtags", "label": "Fetching hashtags", "status": "running", "current": 150, "total": 100}
    )
    assert block.status_box.text() == "99%"


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


def test_future_chunks_are_never_pre_created(qapp) -> None:
    timeline = ExportTimelineWidget(live=True)
    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running"})
    assert timeline.stage_order() == ["videos"]

    for page in range(1, 20):
        timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running", "page": page})
        assert timeline.stage_order() == ["videos:1"], f"chunk 2 must not exist before page 21 (at page {page})"

    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running", "page": 20})
    assert timeline.stage_order() == ["videos:1"]  # page 20 is still chunk 1

    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running", "page": 21})
    assert timeline.stage_order() == ["videos:1", "videos:2"]  # page 21 starts chunk 2

    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running", "page": 41})
    assert timeline.stage_order() == ["videos:1", "videos:2", "videos:3"]  # page 41 starts chunk 3


def test_starting_a_new_chunk_completes_the_previous_one(qapp) -> None:
    timeline = ExportTimelineWidget(live=True)
    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running", "page": 5})
    first = timeline._blocks["videos:1"]  # noqa: SLF001
    assert first._status == "running"  # noqa: SLF001

    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running", "page": 21})

    assert first._status == "complete"  # noqa: SLF001
    assert first.title_label.text() == "FETCHING VIDEOS 1"
    second = timeline._blocks["videos:2"]  # noqa: SLF001
    assert second.title_label.text() == "FETCHING VIDEOS 2"
    assert second._status == "running"  # noqa: SLF001


def test_unsplit_stage_keeps_its_plain_label(qapp) -> None:
    # A stage whose pagination never exceeds one chunk must never show a
    # "1" suffix -- only stages that actually split gain chunk numbers.
    timeline = ExportTimelineWidget(live=True)
    timeline.apply_event({"stage": "hooks", "label": "Fetching hooks", "status": "running", "page": 3})
    assert timeline._blocks["hooks:1"].title_label.text() == "FETCHING HOOKS"  # noqa: SLF001

    timeline.apply_event(
        {"stage": "hooks", "label": "Fetching hooks", "status": "complete", "summary": "8 records · 3 page(s)"}
    )
    assert timeline._blocks["hooks:1"].title_label.text() == "FETCHING HOOKS"  # noqa: SLF001
    assert timeline.stage_status("hooks") == "complete"


def test_final_partial_chunk_never_shows_fake_100_before_real_completion(qapp) -> None:
    timeline = ExportTimelineWidget(live=True)
    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running", "page": 41})
    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running", "page": 47})
    block = timeline._blocks["videos:3"]  # noqa: SLF001
    assert block.status_box.text() != "100%"
    assert block._status == "running"  # noqa: SLF001

    timeline.apply_event(
        {"stage": "videos", "label": "Fetching videos", "status": "complete", "summary": "5,847 record(s) · 47 page(s)"}
    )
    assert block.status_box.text() == "✓"
    assert block._status == "complete"  # noqa: SLF001


def test_status_box_states(qapp) -> None:
    timeline = ExportTimelineWidget(live=True)
    timeline.apply_event({"stage": "videos", "label": "Fetching videos", "status": "running", "current": 10, "total": 100})
    assert timeline._blocks["videos"].status_box.text() == "10%"  # noqa: SLF001

    from virlo_exporter.ui.export_view import SPINNER_FRAMES

    timeline.apply_event({"stage": "sounds", "label": "Fetching sounds", "status": "running"})
    assert timeline._blocks["sounds"].status_box.text() in SPINNER_FRAMES  # noqa: SLF001

    timeline.apply_event({"stage": "prepare", "label": "Preparing", "status": "running"})
    timeline.apply_event({"stage": "prepare", "label": "Preparing", "status": "complete"})
    assert timeline._blocks["prepare"].status_box.text() == "✓"  # noqa: SLF001
    assert timeline._blocks["prepare"].status_box.property("state") == "complete"  # noqa: SLF001

    timeline.apply_event({"stage": "ads", "label": "Fetching ads", "status": "running"})
    timeline.apply_event({"stage": "ads", "label": "Fetching ads", "status": "warning", "summary": "partial"})
    assert timeline._blocks["ads"].status_box.text() == "!"  # noqa: SLF001
    assert timeline._blocks["ads"].status_box.property("state") == "warning"  # noqa: SLF001

    timeline.apply_event({"stage": "outliers", "label": "Fetching outliers", "status": "running"})
    timeline.apply_event({"stage": "outliers", "label": "Fetching outliers", "status": "failed", "summary": "boom"})
    assert timeline._blocks["outliers"].status_box.text() == "×"  # noqa: SLF001
    assert timeline._blocks["outliers"].status_box.property("state") == "failed"  # noqa: SLF001


def test_historical_reconstruction_restores_all_chunks(qapp) -> None:
    # Page-level events are never persisted (only stage start/finish rows
    # are), so a completed export's chunk history has to be reconstructed
    # from the finished page count baked into the persisted summary text.
    timeline = ExportTimelineWidget(live=False)
    rows = [
        {
            "stage": "videos",
            "label": "Fetching videos",
            "status": "complete",
            "summary": "5,847 record(s) · 47 page(s)",
        },
    ]
    timeline.load_history(rows)
    assert timeline.stage_order() == ["videos:1", "videos:2", "videos:3"]
    for key in timeline.stage_order():
        assert timeline._blocks[key]._status == "complete"  # noqa: SLF001
    assert timeline._blocks["videos:1"].title_label.text() == "FETCHING VIDEOS 1"  # noqa: SLF001
    assert timeline._blocks["videos:3"].title_label.text() == "FETCHING VIDEOS 3"  # noqa: SLF001


def test_historical_reconstruction_leaves_short_stage_unchunked(qapp) -> None:
    timeline = ExportTimelineWidget(live=False)
    rows = [
        {"stage": "hooks", "label": "Fetching hooks", "status": "complete", "summary": "8 record(s) · 3 page(s)"},
    ]
    timeline.load_history(rows)
    assert timeline.stage_order() == ["hooks"]
    assert timeline._blocks["hooks"].title_label.text() == "FETCHING HOOKS"  # noqa: SLF001


def test_snake_canvas_connector_rows_follow_display_order(qapp) -> None:
    from virlo_exporter.ui.export_view import SnakeCanvas

    host = QWidget()
    layout = SnakeLayout(host, spacing=10)
    host.setLayout(layout)
    blocks = [StageBlock(f"stage{i}", f"Stage {i}") for i in range(6)]
    for block in blocks:
        layout.addWidget(block)
    host.setGeometry(QRect(0, 0, 548, 400))
    layout.setGeometry(QRect(0, 0, 548, 400))

    canvas = SnakeCanvas(layout)
    rows = layout.rows_in_display_order()
    assert [b.stage for b in rows[0]] == ["stage0", "stage1", "stage2"]
    assert [b.stage for b in rows[1]] == ["stage5", "stage4", "stage3"]  # reversed row, display order
    # Sequence-last of row 0 (stage2) sits above sequence-first of row 1
    # (stage3) -- the vertical connector must join exactly those two.
    assert canvas._sequence_last(rows[0], reversed_row=False).stage == "stage2"
    assert canvas._sequence_first(rows[1], reversed_row=True).stage == "stage3"


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
