from __future__ import annotations

import contextlib
import json

from virlo_exporter.api.errors import VirloError
from virlo_exporter.api.pagination import PageResult
from virlo_exporter.export import report as report_module
from virlo_exporter.export.engine import ExportEngine, ExportFatalError
from virlo_exporter.storage.database import Database
from virlo_exporter.utils.files import reveal_in_explorer


class FakeClient:
    base_url = "https://api.virlo.ai/v1"

    def get_agent(self, agent_id: str) -> dict:
        return {
            "data": {
                "id": agent_id,
                "name": "Test Agent",
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
                    {"id": str(index), "platform": "tiktok", "views": index, "url": f"https://v/{index}"}
                    for index in range(20)
                ],
                1,
                20,
            )
        return PageResult([], 1)


class FailingFakeClient(FakeClient):
    def __init__(self, failing_resource: str) -> None:
        self.failing_resource = failing_resource

    def get_resource(self, agent_id: str, resource: str, **_kwargs) -> PageResult:
        if resource == self.failing_resource:
            raise VirloError(f"{resource} is unavailable", status_code=503)
        return super().get_resource(agent_id, resource, **_kwargs)


def test_successful_export_writes_clean_report(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    result = ExportEngine(FakeClient(), db, tmp_path / "exports", baseline_sample_size=20).export(
        "agent-1", "run-1"
    )
    report_path = result.path / report_module.REPORT_FILENAME
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["report_schema_version"] == "1.0"
    assert report["export"]["status"] == "complete"
    assert report["warnings"] == []
    assert report["errors"] == []
    assert report["summary"]["paid_api_calls"] == 0


def test_complete_with_warnings_report_has_warning_detail(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    client = FailingFakeClient(failing_resource="sounds")
    result = ExportEngine(client, db, tmp_path / "exports", baseline_sample_size=20).export(
        "agent-1", "run-1"
    )
    report = json.loads((result.path / report_module.REPORT_FILENAME).read_text(encoding="utf-8"))
    assert report["export"]["status"] == "complete_with_warnings"
    assert report["warnings"]
    warning = next(entry for entry in report["warnings"] if entry["stage"] == "sounds")
    assert warning["http_status"] == 503
    assert "sounds is unavailable" in warning["message"]


def test_fatal_failure_report_has_error_detail(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    client = FailingFakeClient(failing_resource="videos")
    engine = ExportEngine(client, db, tmp_path / "exports", baseline_sample_size=20)
    with contextlib.suppress(ExportFatalError):
        engine.export("agent-1", "run-1")
    export_dir = next((tmp_path / "exports").rglob("Export_*"))
    report = json.loads((export_dir / report_module.REPORT_FILENAME).read_text(encoding="utf-8"))
    assert report["export"]["status"] == "failed"
    assert report["errors"]
    error = report["errors"][0]
    assert error["stage"] == "videos"
    assert error["http_status"] == 503


def test_report_never_contains_secrets(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])

    class LeakyFakeClient(FakeClient):
        def get_resource(self, agent_id: str, resource: str, **_kwargs) -> PageResult:
            if resource == "sounds":
                raise VirloError(
                    "Authorization: Bearer virlo_tkn_realsecret123 was rejected", status_code=401
                )
            return super().get_resource(agent_id, resource, **_kwargs)

    result = ExportEngine(LeakyFakeClient(), db, tmp_path / "exports", baseline_sample_size=20).export(
        "agent-1", "run-1"
    )
    raw_text = (result.path / report_module.REPORT_FILENAME).read_text(encoding="utf-8")
    assert "virlo_tkn_realsecret123" not in raw_text
    assert "Bearer virlo_tkn_realsecret123" not in raw_text


def test_ensure_report_regenerates_missing_file_from_persisted_stages(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    result = ExportEngine(FakeClient(), db, tmp_path / "exports", baseline_sample_size=20).export(
        "agent-1", "run-1"
    )
    report_path = result.path / report_module.REPORT_FILENAME
    report_path.unlink()
    assert not report_path.exists()

    export_row = db.export_history("agent-1", "run-1")[0]
    regenerated = report_module.ensure_report(
        result.path,
        export_row=export_row,
        stages=db.export_stages(result.export_id),
        agent_name="Test Agent",
    )
    assert regenerated == report_path
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["export"]["agent_name"] == "Test Agent"


def test_export_dir_never_assigned_stores_honest_empty_path_not_a_fake_pending_folder(
    tmp_path,
) -> None:
    # Reproduces a real bug: when the export fails before export_dir is ever
    # assigned (e.g. get_agent/get_run itself raises), the code used to fall
    # back to `provisional` (export_root / "pending") and persist THAT as the
    # export's permanent path -- but that directory is never actually
    # created on disk, so Report/Open Folder later look plausible while
    # pointing at a folder that never existed under the exports root.
    db = Database(tmp_path / "state.db")
    db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])

    class BrokenMetadataClient(FakeClient):
        def get_agent(self, agent_id: str) -> dict:
            raise VirloError("agent lookup failed", status_code=500)

    engine = ExportEngine(BrokenMetadataClient(), db, tmp_path / "exports", baseline_sample_size=20)
    with contextlib.suppress(VirloError):
        engine.export("agent-1", "run-1")

    record = db.export_history("agent-1", "run-1")[0]
    assert record["path"] == ""
    assert not (tmp_path / "exports" / "pending").exists()


def test_reveal_in_explorer_invokes_explorer_select(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args, check=False):  # noqa: ANN001 - test double
        calls.append(args)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    target = tmp_path / "EXPORT_REPORT.json"
    target.write_text("{}", encoding="utf-8")
    reveal_in_explorer(target)
    assert len(calls) == 1
    assert calls[0][0] == "explorer"
    assert calls[0][1] == f"/select,{target.resolve()}"
