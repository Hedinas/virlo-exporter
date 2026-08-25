from __future__ import annotations

import json
import logging
import shutil
import traceback
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any

from virlo_exporter import __version__
from virlo_exporter.api.billing import BillingClass
from virlo_exporter.api.client import VirloClient
from virlo_exporter.api.errors import VirloError
from virlo_exporter.storage.database import Database
from virlo_exporter.utils.files import safe_filename

from .dataset import count_platforms, deterministic_baseline, select_high_signal
from .report import build_report, write_report
from .timeline import StageTracker

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExportResult:
    path: Path
    dataset_path: Path
    complete: bool
    warnings: list[str]
    manifest: dict[str, Any]
    export_id: int
    export_number: int
    research_number: int
    statistics: dict[str, Any]


class ExportCancelled(Exception):
    pass


class ExportFatalError(VirloError):
    pass


class ExportEngine:
    RESOURCE_ORDER = [
        "runs",
        "videos",
        "slideshows",
        "ads",
        "outliers",
        "analysis",
        "trends",
        "sounds",
        "hashtags",
        "benchmarks",
        "affinity",
        "activity",
        "proposals",
        "hooks",
    ]

    def __init__(
        self,
        client: VirloClient,
        database: Database,
        export_root: Path,
        *,
        baseline_sample_size: int = 150,
        progress: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        self.client = client
        self.database = database
        self.export_root = export_root
        self.baseline_sample_size = baseline_sample_size
        self.progress = progress
        self.cancel_event = cancel_event or Event()
        self._tracker: StageTracker | None = None

    def _check_progress(
        self, current: int, total: int | None, message: str | None = None
    ) -> None:
        if self.cancel_event.is_set():
            raise ExportCancelled()
        if self._tracker:
            self._tracker.update(current=current, total=total, message=message)

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        encoder = json.JSONEncoder(ensure_ascii=False, indent=2, allow_nan=False)
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for chunk in encoder.iterencode(value):
                handle.write(chunk)
            handle.write("\n")
        temporary.replace(path)

    def export(self, agent_id: str, run_id: str) -> ExportResult:
        started = datetime.now(UTC)
        research_number = self.database.research_number(agent_id, run_id)
        provisional = str(self.export_root / "pending")
        export_id, export_number = self.database.begin_export(
            agent_id, run_id, research_number, provisional, started.isoformat()
        )
        manifest: dict[str, Any] = {"resources": {}, "warnings": [], "errors": []}
        diagnostics: list[dict[str, Any]] = []
        fatal_diagnostics: list[dict[str, Any]] = []
        resources: dict[str, Any] = {}
        export_dir: Path | None = None
        agent_name = agent_id
        log_lines = [f"{started.isoformat()} export started", "Billing policy: FREE_READ only"]
        tracker = StageTracker(self.database, export_id, self.progress)
        self._tracker = tracker

        def save_report(status: str) -> None:
            if export_dir is None:
                return
            export_row = {
                "export_number": export_number,
                "research_number": research_number,
                "status": status,
                "started_at": started.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "validation_state": "warnings" if manifest["warnings"] else "valid",
            }
            report = build_report(
                export_row=export_row,
                stages=self.database.export_stages(export_id),
                agent_name=agent_name,
                summary={
                    "videos": len(resources.get("videos", [])),
                    "warnings": len(manifest["warnings"]),
                    "errors": len(manifest["errors"]),
                    "paid_api_calls": 0,
                },
                warnings=diagnostics,
                errors=fatal_diagnostics,
            )
            with suppress(OSError):
                write_report(export_dir, report)

        try:
            tracker.start("prepare", "Preparing export", detail="Allocating a local export record")
            tracker.finish(summary=f"Research #{research_number:03d} · Export #{export_number:03d}")
            tracker.start("metadata", "Fetching Agent and run metadata")
            agent_payload = self.client.get_agent(agent_id)
            agent = agent_payload.get("data", agent_payload)
            if not isinstance(agent, dict):
                raise VirloError("Agent response is malformed.")
            run_payload = self.client.get_run(agent_id, run_id)
            run = run_payload.get("data", run_payload)
            if not isinstance(run, dict):
                raise VirloError("Run response is malformed.")

            stamp = started.astimezone().strftime("%Y-%m-%d_%H-%M-%S")
            export_dir = (
                self.export_root
                / safe_filename(str(agent.get("name") or agent_id))
                / f"Research_{research_number:03d}"
                / f"Export_{export_number:03d}_{stamp}"
            )
            raw_dir = export_dir / "RAW"
            raw_dir.mkdir(parents=True, exist_ok=False)
            self.database.update_export(
                export_id,
                path=str(export_dir),
                status="running",
                completed_at=None,
                validation="pending",
            )
            self._write_json(raw_dir / "agent.json", agent_payload)
            self._write_json(raw_dir / "run.json", run_payload)
            manifest["resources"]["agent"] = self._manifest_entry("/agents/:id", "agent", 1, 1)
            manifest["resources"]["run"] = self._manifest_entry(
                "/agents/:id/runs/:run_id", "run", 1, 1
            )
            tracker.finish(summary="Agent and selected run saved")
            agent_name = str(agent.get("name") or agent_id)

            di_enabled = bool(agent.get("data_intelligence_enabled"))
            for resource in self.RESOURCE_ORDER:
                label = f"Fetching {resource.replace('_', ' ')}"
                tracker.start(resource, label)
                if resource == "hooks" and not di_enabled:
                    reason = "Hooks retrieval costs $0.25 when Data Intelligence is disabled."
                    manifest["resources"][resource] = self._skipped_entry(
                        resource, reason, BillingClass.CONDITIONAL_COST
                    )
                    log_lines.append(f"SKIP {resource}: {reason}")
                    tracker.finish("skipped", summary="Skipped to guarantee $0 retrieval cost", detail=reason)
                    continue
                try:
                    if resource == "runs":
                        result = self.client.list_runs(agent_id)
                    else:

                        def on_page(
                            page: int, count_so_far: int, expected_total: int | None
                        ) -> None:
                            self._check_progress(count_so_far, expected_total, f"Page {page}")

                        result = self.client.get_resource(
                            agent_id,
                            resource,
                            data_intelligence_enabled=di_enabled,
                            on_page=on_page,
                        )
                    resources[resource] = result.records
                    self._write_json(raw_dir / f"{resource}.json", result.records)
                    entry = self._manifest_entry(
                        f"/agents/:id/{'creators/outliers' if resource == 'outliers' else resource}",
                        "agent",
                        len(result.records),
                        result.pages,
                        warnings=result.warnings,
                    )
                    manifest["resources"][resource] = entry
                    manifest["warnings"].extend(result.warnings)
                    log_lines.append(
                        f"OK {resource}: {len(result.records)} records, {result.pages} page(s)"
                    )
                    tracker.finish(
                        summary=f"{len(result.records):,} record(s) · {result.pages} page(s)"
                    )
                except VirloError as exc:
                    status = "unavailable" if exc.status_code in {400, 404} else "failed"
                    error_code = exc.details.get("code") if isinstance(exc.details, dict) else None
                    diagnostic_entry = {
                        "stage": resource,
                        "endpoint": f"/agents/:id/{resource}",
                        "http_status": exc.status_code,
                        "error_code": error_code,
                        "message": str(exc),
                    }
                    manifest["resources"][resource] = {
                        "endpoint": f"/agents/:id/{resource}",
                        "scope": "agent",
                        "status": status,
                        "records": 0,
                        "pages": 0,
                        "billing_class": BillingClass.FREE_READ,
                        "errors": [str(exc)],
                    }
                    if resource == "videos":
                        manifest["errors"].append(f"videos: {exc}")
                        fatal_diagnostics.append(diagnostic_entry)
                        tracker.finish("failed", summary="Required resource failed", detail=str(exc))
                        log_lines.append(f"FATAL {resource}: {type(exc).__name__}: {exc}")
                        raise ExportFatalError(
                            f"Required videos stage failed: {exc}", status_code=exc.status_code
                        ) from exc
                    manifest["warnings"].append(f"{resource}: {exc}")
                    diagnostics.append(diagnostic_entry)
                    log_lines.append(f"WARN {resource}: {type(exc).__name__}: {exc}")
                    tracker.finish("warning", summary="Optional resource unavailable", detail=str(exc))

            tracker.start("selection", "Selecting high-signal and baseline videos")
            videos = resources.get("videos", [])
            high_signal, unresolved = select_high_signal(videos, resources)
            baseline = deterministic_baseline(videos, high_signal, self.baseline_sample_size)
            if unresolved:
                manifest["warnings"].append(
                    f"{len(unresolved)} evidence video reference(s) were unresolved."
                )
            tracker.finish(
                "warning" if unresolved else "complete",
                summary=f"{len(high_signal):,} high-signal · {len(baseline):,} baseline",
                detail=(f"{len(unresolved)} unresolved evidence reference(s)" if unresolved else None),
            )
            tracker.start("dataset", "Building AI-ready dataset")
            dataset = self._build_dataset(
                agent,
                run,
                resources,
                manifest,
                research_number,
                export_number,
                started,
                high_signal,
                baseline,
                unresolved,
            )
            dataset_path = export_dir / "VIRLO_AI_DATASET.json"
            self._write_json(dataset_path, dataset)
            tracker.finish(summary="VIRLO_AI_DATASET.json written")
            tracker.start("validation", "Validating files and manifest")
            validation_warnings = self._validate(export_dir, dataset, resources)
            manifest["warnings"].extend(validation_warnings)
            diagnostics.extend(
                {
                    "stage": "validation",
                    "endpoint": None,
                    "http_status": None,
                    "error_code": None,
                    "message": message,
                }
                for message in validation_warnings
            )
            complete = True
            if manifest["warnings"]:
                dataset["_export_status"] = {
                    "complete": complete,
                    "complete_with_warnings": complete,
                    "warnings": manifest["warnings"],
                }
                dataset["_manifest"] = manifest
                self._write_json(dataset_path, dataset)
            tracker.finish(
                "warning" if validation_warnings else "complete",
                summary=(f"{len(validation_warnings)} validation warning(s)" if validation_warnings else "All required files are valid"),
                detail="\n".join(validation_warnings) or None,
            )
            tracker.start("finalize", "Finalizing export")
            completed = datetime.now(UTC).isoformat()
            log_lines.append(f"{completed} export completed; warnings={len(manifest['warnings'])}")
            (export_dir / "export.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
            self.database.update_export(
                export_id,
                path=str(export_dir),
                status="complete_with_warnings" if manifest["warnings"] else "complete",
                completed_at=completed,
                validation="warnings" if manifest["warnings"] else "valid",
            )
            raw_size = sum(path.stat().st_size for path in raw_dir.glob("*.json"))
            statistics = {
                "raw_files": len(list(raw_dir.glob("*.json"))),
                "raw_bytes": raw_size,
                "dataset_bytes": dataset_path.stat().st_size,
                "videos": len(videos),
                "high_signal": len(high_signal),
                "baseline": len(baseline),
                "warnings": len(manifest["warnings"]),
                "paid_api_calls": 0,
            }
            tracker.finish(
                "warning" if manifest["warnings"] else "complete",
                summary=(f"Complete with {len(manifest['warnings'])} warning(s)" if manifest["warnings"] else "Export complete"),
            )
            save_report("complete_with_warnings" if manifest["warnings"] else "complete")
            return ExportResult(
                export_dir, dataset_path, complete, manifest["warnings"], manifest,
                export_id, export_number, research_number, statistics
            )
        except ExportCancelled:
            if export_dir:
                (export_dir / "EXPORT_CANCELLED").write_text(
                    "Export cancelled by user.\n", encoding="utf-8"
                )
            self.database.update_export(
                export_id,
                path=str(export_dir or provisional),
                status="cancelled",
                completed_at=datetime.now(UTC).isoformat(),
                validation="incomplete",
            )
            save_report("cancelled")
            raise
        except Exception as exc:
            if tracker.current and tracker.current.get("status") == "running":
                tracker.finish("failed", summary=type(exc).__name__, detail=str(exc))
            detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            log_lines.append(f"FATAL {type(exc).__name__}: {exc}")
            log_lines.append(detail.rstrip())
            if not isinstance(exc, ExportFatalError):
                fatal_diagnostics.append(
                    {
                        "stage": tracker.current.get("stage") if tracker.current else None,
                        "endpoint": None,
                        "http_status": getattr(exc, "status_code", None),
                        "error_code": None,
                        "message": str(exc),
                    }
                )
            if export_dir:
                (export_dir / "EXPORT_INCOMPLETE").write_text(
                    "Export failed. See application logs.\n", encoding="utf-8"
                )
                with suppress(OSError):
                    (export_dir / "export.log").write_text(
                        "\n".join(log_lines) + "\n", encoding="utf-8"
                    )
            self.database.update_export(
                export_id,
                path=str(export_dir or provisional),
                status="failed",
                completed_at=datetime.now(UTC).isoformat(),
                validation="incomplete",
            )
            save_report("failed")
            raise

    @staticmethod
    def _manifest_entry(
        endpoint: str,
        scope: str,
        records: int,
        pages: int,
        *,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "endpoint": endpoint,
            "scope": scope,
            "status": "complete",
            "records": records,
            "pages": pages,
            "billing_class": BillingClass.FREE_READ,
            "cost": 0,
            "skipped": False,
            "warnings": warnings or [],
            "errors": [],
        }

    @staticmethod
    def _skipped_entry(resource: str, reason: str, classification: BillingClass) -> dict[str, Any]:
        return {
            "endpoint": f"/agents/:id/{resource}",
            "scope": "agent",
            "status": "skipped",
            "records": 0,
            "pages": 0,
            "billing_class": classification,
            "skipped": True,
            "skip_reason": reason,
            "warnings": [],
            "errors": [],
        }

    def _build_dataset(
        self,
        agent: dict[str, Any],
        run: dict[str, Any],
        resources: dict[str, Any],
        manifest: dict[str, Any],
        research_number: int,
        export_number: int,
        started: datetime,
        high_signal: list[dict[str, Any]],
        baseline: list[dict[str, Any]],
        unresolved: list[str],
    ) -> dict[str, Any]:
        analysis = resources.get("analysis", [])
        analysis_value: Any = analysis[0] if len(analysis) == 1 else analysis
        analysis_data = (
            analysis_value.get("analysis_data", {}) if isinstance(analysis_value, dict) else {}
        )
        return {
            "_dataset_info": {
                "dataset_schema_version": "1.0",
                "exporter_version": __version__,
                "exported_at": started.isoformat(),
                "agent_id": agent.get("id"),
                "agent_name": agent.get("name"),
                "run_id": run.get("id"),
                "local_research_number": research_number,
                "local_export_number": export_number,
                "scope": {
                    "run": "selected Virlo run metadata",
                    "agent_resources": "current full agent corpus; API does not expose per-run filters for these resources",
                },
                "virlo_api_base_url": self.client.base_url,
                "timezone": datetime.now().astimezone().tzname(),
                "source": "Official Virlo API v1, existing persisted Agent data only",
                "data_intelligence_enabled": bool(agent.get("data_intelligence_enabled")),
                "meta_ads_enabled": bool(agent.get("meta_ads_enabled")),
                "platforms": agent.get("platforms", []),
                "intent": agent.get("intent"),
                "keywords": agent.get("keywords", []),
            },
            "_ai_instructions": {
                "purpose": "Post-analysis of Virlo research for short-form content strategy",
                "source_of_truth": "Virlo research data preserved in this dataset; complete RAW files exist locally",
                "analysis_guidance": [
                    "Compare winners against baseline videos",
                    "Use evidence video IDs and URLs",
                    "Correlate hooks, formats, topics and performance",
                    "Distinguish recurring patterns from isolated outliers",
                    "Use Virlo Data Intelligence fields when available",
                    "Do not treat correlation as proven causation",
                    "Prefer evidence supported by multiple examples",
                ],
            },
            "_manifest": manifest,
            "_export_status": {
                "complete": not manifest["errors"],
                "warnings": manifest["warnings"],
            },
            "agent": agent,
            "run": run,
            "research_configuration": {
                key: agent.get(key)
                for key in (
                    "intent",
                    "keywords",
                    "exclude_keywords",
                    "platforms",
                    "is_recurring",
                    "cadence",
                    "english_only",
                    "data_intelligence_enabled",
                    "meta_ads_enabled",
                )
            },
            "analysis": analysis_value,
            "themes": analysis_data.get("themes", []) if isinstance(analysis_data, dict) else [],
            "viral_tactics": analysis_data.get("viral_tactics", [])
            if isinstance(analysis_data, dict)
            else [],
            "trends": resources.get("trends", []),
            "hooks": resources.get("hooks", []),
            "creator_outliers": resources.get("outliers", []),
            "ads": resources.get("ads", []),
            "slideshows": resources.get("slideshows", []),
            "sounds": resources.get("sounds", []),
            "hashtags": resources.get("hashtags", []),
            "benchmarks": resources.get("benchmarks", []),
            "affinity": resources.get("affinity", []),
            "activity": resources.get("activity", []),
            "proposals": resources.get("proposals", []),
            "high_signal_videos": high_signal,
            "baseline_video_sample": baseline,
            "statistics": {
                "raw_video_count": len(resources.get("videos", [])),
                "high_signal_video_count": len(high_signal),
                "baseline_video_count": len(baseline),
                "videos_by_platform": count_platforms(resources.get("videos", [])),
                "unresolved_evidence_reference_count": len(unresolved),
            },
            "relationships": {"unresolved_evidence_video_ids": unresolved},
            "selection_methodology": {
                "high_signal": "Virlo evidence IDs, outlier membership, top performers by platform, and strong intent matches; deduplicated by stable ID or platform+URL",
                "baseline": "Deterministic round-robin sample stratified by platform and view-count tercile, excluding high-signal videos",
                "baseline_requested_size": self.baseline_sample_size,
            },
        }

    @staticmethod
    def _validate(
        export_dir: Path, dataset: dict[str, Any], resources: dict[str, Any]
    ) -> list[str]:
        warnings: list[str] = []
        required = [
            export_dir / "RAW" / "agent.json",
            export_dir / "RAW" / "run.json",
            export_dir / "VIRLO_AI_DATASET.json",
        ]
        for path in required:
            if not path.exists():
                raise OSError(f"Required export file was not created: {path.name}")
        for path in (export_dir / "RAW").glob("*.json"):
            with path.open(encoding="utf-8") as handle:
                json.load(handle)
        if "_manifest" not in dataset or "_export_status" not in dataset:
            raise ValueError("Dataset manifest/status is missing.")
        free = shutil.disk_usage(export_dir).free
        if free < 10 * 1024 * 1024:
            warnings.append("Less than 10 MB of disk space remains after export.")
        if resources.get("videos") and not dataset.get("high_signal_videos"):
            warnings.append("Videos were retrieved but none met the high-signal selection rules.")
        return warnings
