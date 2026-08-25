from __future__ import annotations

import json

from virlo_exporter.api.pagination import PageResult
from virlo_exporter.export.engine import ExportEngine
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
