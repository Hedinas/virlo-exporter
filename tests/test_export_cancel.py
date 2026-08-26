from __future__ import annotations

import json
from threading import Event

import pytest

from virlo_exporter.api.pagination import PageResult
from virlo_exporter.export.engine import ExportCancelled, ExportEngine
from virlo_exporter.storage.database import Database


class CancellingFakeClient:
    """A client whose videos resource actually drives on_page per page, so a
    cancel_event set mid-pagination is noticed the same way it would be
    against the real API."""

    base_url = "https://api.virlo.ai/v1"

    def __init__(self, cancel_event: Event, cancel_at_page: int) -> None:
        self.cancel_event = cancel_event
        self.cancel_at_page = cancel_at_page

    def get_agent(self, agent_id: str) -> dict:
        return {"data": {"id": agent_id, "name": "Test", "data_intelligence_enabled": False}}

    def get_run(self, agent_id: str, run_id: str) -> dict:
        return {"data": {"id": run_id, "agent_id": agent_id, "status": "completed"}}

    def list_runs(self, agent_id: str) -> PageResult:
        return PageResult([{"id": "run-1", "agent_id": agent_id}], 1)

    def get_resource(self, agent_id: str, resource: str, *, on_page=None, **_kwargs) -> PageResult:
        if resource != "videos":
            return PageResult([], 1)
        records: list[dict] = []
        for page in range(1, 5):
            records.append({"id": str(page), "platform": "tiktok"})
            if page == self.cancel_at_page:
                self.cancel_event.set()
            if on_page:
                on_page(page, len(records), 4)
        return PageResult(records, 4, 4)


def test_cancel_mid_pagination_marks_interrupted_stage_with_page_context(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    cancel_event = Event()
    client = CancellingFakeClient(cancel_event, cancel_at_page=2)
    engine = ExportEngine(client, db, tmp_path / "exports", cancel_event=cancel_event)  # type: ignore[arg-type]

    with pytest.raises(ExportCancelled):
        engine.export("agent-1", "run-1")

    export_row = db.export_history("agent-1", "run-1")[0]
    assert export_row["status"] == "cancelled"

    stages = {row["stage"]: row for row in db.export_stages(export_row["id"])}
    assert stages["videos"]["status"] == "cancelled"
    assert "Interrupted by user" in stages["videos"]["summary"]
    assert "page 2" in stages["videos"]["summary"]
    # A resource that never started must not be marked as anything -- it
    # simply never ran.
    assert "slideshows" not in stages


def test_cancel_report_records_reason_and_interrupted_context(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    cancel_event = Event()
    client = CancellingFakeClient(cancel_event, cancel_at_page=1)
    engine = ExportEngine(client, db, tmp_path / "exports", cancel_event=cancel_event)  # type: ignore[arg-type]

    with pytest.raises(ExportCancelled):
        engine.export("agent-1", "run-1")

    export_row = db.export_history("agent-1", "run-1")[0]
    from pathlib import Path

    report_path = Path(export_row["path"]) / "EXPORT_REPORT.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["export"]["status"] == "cancelled"
    assert report["summary"]["reason"] == "user_cancelled"
    assert report["summary"]["interrupted_stage"] == "videos"
    assert report["summary"]["interrupted_page"] == 1
