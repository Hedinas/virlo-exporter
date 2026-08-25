from __future__ import annotations

import json

import pytest

from virlo_exporter.api.errors import VirloError
from virlo_exporter.api.pagination import PageResult
from virlo_exporter.export.engine import ExportEngine, ExportFatalError
from virlo_exporter.storage.database import Database


class FakeClient:
    base_url = "https://api.virlo.ai/v1"

    def get_agent(self, agent_id: str) -> dict:
        return {
            "data": {
                "id": agent_id,
                "name": "Test / Agent",
                "intent": "Find test evidence",
                "keywords": ["test video"],
                "platforms": ["tiktok"],
                "data_intelligence_enabled": False,
                "meta_ads_enabled": True,
            }
        }

    def get_run(self, agent_id: str, run_id: str) -> dict:
        return {"data": {"id": run_id, "agent_id": agent_id, "status": "completed"}}

    def list_runs(self, agent_id: str) -> PageResult:
        return PageResult([{"id": "run-1", "agent_id": agent_id}], 1)

    def get_resource(self, agent_id: str, resource: str, **_kwargs) -> PageResult:
        if resource == "videos":
            return PageResult(
                [
                    {
                        "id": str(index),
                        "platform": "tiktok",
                        "views": index,
                        "url": f"https://v/{index}",
                    }
                    for index in range(200)
                ],
                2,
                200,
            )
        if resource == "analysis":
            return PageResult(
                [{"analysis_data": {"themes": ["proof"]}, "evidence_video_ids": ["199"]}], 1
            )
        return PageResult([], 1)


def test_end_to_end_export_uses_only_existing_free_data(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    result = ExportEngine(FakeClient(), db, tmp_path / "exports", baseline_sample_size=20).export(  # type: ignore[arg-type]
        "agent-1", "run-1"
    )
    assert result.complete
    assert result.dataset_path.exists()
    assert not list(result.path.glob("*.zip"))
    dataset = json.loads(result.dataset_path.read_text(encoding="utf-8"))
    raw_videos = json.loads((result.path / "RAW" / "videos.json").read_text(encoding="utf-8"))
    assert len(raw_videos) == 200
    assert len(dataset["baseline_video_sample"]) == 20
    assert len(dataset["high_signal_videos"]) < 200
    assert dataset["_dataset_info"]["scope"]["agent_resources"].startswith(
        "current full agent corpus"
    )
    assert dataset["_manifest"]["resources"]["hooks"]["status"] == "skipped"
    assert dataset["_manifest"]["resources"]["videos"]["billing_class"] == "FREE_READ"


class FailingFakeClient(FakeClient):
    """FakeClient that raises VirloError for one named resource."""

    def __init__(self, failing_resource: str) -> None:
        self.failing_resource = failing_resource
        self.paid_calls: list[str] = []

    def get_resource(self, agent_id: str, resource: str, **_kwargs) -> PageResult:
        if resource == self.failing_resource:
            raise VirloError(f"{resource} is unavailable", status_code=503)
        return super().get_resource(agent_id, resource, **_kwargs)

    # Any of these being called would mean the export attempted a paid
    # action, which must never happen for a free retrieval of existing data.
    def create_agent(self, *_args, **_kwargs):
        self.paid_calls.append("create_agent")
        raise AssertionError("export must never call create_agent")

    def suggest_keywords(self, *_args, **_kwargs):
        self.paid_calls.append("suggest_keywords")
        raise AssertionError("export must never call suggest_keywords")


def test_optional_resource_failure_is_a_warning_not_a_failure(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    client = FailingFakeClient(failing_resource="sounds")
    result = ExportEngine(client, db, tmp_path / "exports", baseline_sample_size=20).export(
        "agent-1", "run-1"
    )
    assert result.complete
    assert any("sounds" in warning for warning in result.warnings)
    history = db.export_history("agent-1", "run-1")
    assert history[0]["status"] == "complete_with_warnings"
    assert not client.paid_calls


def test_fatal_core_resource_failure_marks_export_failed(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    client = FailingFakeClient(failing_resource="videos")
    engine = ExportEngine(client, db, tmp_path / "exports", baseline_sample_size=20)
    with pytest.raises(ExportFatalError):
        engine.export("agent-1", "run-1")
    history = db.export_history("agent-1", "run-1")
    assert history[0]["status"] == "failed"
    assert not client.paid_calls


def test_stage_event_sequence_and_history_persistence(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    events: list[dict] = []
    result = ExportEngine(
        FakeClient(), db, tmp_path / "exports", baseline_sample_size=20, progress=events.append
    ).export("agent-1", "run-1")

    started = [event for event in events if event["status"] == "running"]
    finished = [event for event in events if event["status"] != "running"]
    assert [event["stage"] for event in started][:3] == ["prepare", "metadata", "runs"]
    # Every started stage eventually reaches a terminal status.
    started_stages = {event["stage"] for event in started}
    finished_stages = {event["stage"] for event in finished}
    assert started_stages <= finished_stages
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(sequences)

    persisted = db.export_stages(result.export_id)
    assert persisted
    assert [row["sequence"] for row in persisted] == sorted(row["sequence"] for row in persisted)
    assert all(row["status"] != "running" for row in persisted)
    videos_row = next(row for row in persisted if row["stage"] == "videos")
    assert videos_row["status"] == "complete"
