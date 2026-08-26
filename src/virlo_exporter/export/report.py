from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

REPORT_FILENAME = "EXPORT_REPORT.json"
REPORT_SCHEMA_VERSION = "1.0"

_SECRET_PATTERNS = (
    re.compile(r"virlo_tkn_[A-Za-z0-9_-]+", re.IGNORECASE),
    re.compile(r"bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
)


def redact_secrets(text: str) -> str:
    """Defense in depth: strip anything that looks like a token or bearer header."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


def _duration_ms(started_at: str | None, completed_at: str | None) -> int | None:
    if not started_at or not completed_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(completed_at)
    except ValueError:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def build_report(
    *,
    export_row: dict[str, Any],
    stages: list[dict[str, Any]],
    agent_name: str,
    summary: dict[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    notices: list[dict[str, Any]] | None = None,
    deduplications: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    stage_entries = [
        {
            "name": row.get("stage"),
            "label": row.get("label"),
            "status": row.get("status"),
            "duration_ms": _duration_ms(row.get("started_at"), row.get("completed_at")),
            "summary": row.get("summary"),
        }
        for row in stages
    ]

    def clean(entries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        cleaned = []
        for entry in entries or []:
            cleaned.append(
                {
                    key: (redact_secrets(value) if isinstance(value, str) else value)
                    for key, value in entry.items()
                }
            )
        return cleaned

    from .validator import has_actionable_report

    status = str(export_row.get("status") or "")
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "export": {
            "export_number": export_row.get("export_number"),
            "research_number": export_row.get("research_number"),
            "agent_name": agent_name,
            "status": export_row.get("status"),
            "started_at": export_row.get("started_at"),
            "completed_at": export_row.get("completed_at"),
            "duration_ms": _duration_ms(export_row.get("started_at"), export_row.get("completed_at")),
        },
        "summary": summary or {},
        "warnings": clean(warnings),
        "errors": clean(errors),
        "notices": clean(notices),
        "deduplications": clean(deduplications),
        "stages": stage_entries,
        "validation": {
            "validation_state": export_row.get("validation_state"),
            "has_actionable_report": has_actionable_report(status),
        },
    }


def write_report(export_dir: Path, report: dict[str, Any]) -> Path:
    path = export_dir / REPORT_FILENAME
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)
    return path


def ensure_report(
    export_dir: Path,
    *,
    export_row: dict[str, Any],
    stages: list[dict[str, Any]],
    agent_name: str,
) -> Path:
    """Return the report path, regenerating a best-effort copy from persisted
    stage diagnostics if the file is missing (e.g. an export from before this
    feature existed, or a manually-deleted report)."""
    path = export_dir / REPORT_FILENAME
    if path.exists():
        return path
    warnings = [
        {
            "stage": row.get("stage"),
            "endpoint": None,
            "http_status": None,
            "error_code": None,
            "message": row.get("detail") or row.get("summary") or "",
        }
        for row in stages
        if row.get("status") == "warning"
    ]
    errors = [
        {
            "stage": row.get("stage"),
            "endpoint": None,
            "http_status": None,
            "error_code": None,
            "message": row.get("detail") or row.get("summary") or "",
        }
        for row in stages
        if row.get("status") == "failed"
    ]
    report = build_report(
        export_row=export_row,
        stages=stages,
        agent_name=agent_name,
        summary={
            "warnings": len(warnings),
            "errors": len(errors),
            "paid_api_calls": 0,
        },
        warnings=warnings,
        errors=errors,
    )
    return write_report(export_dir, report)
