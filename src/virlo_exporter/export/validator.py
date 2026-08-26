"""Reusable export validation: structural invariants EXPORT_REPORT.json
must always satisfy, RAW<->dataset reconciliation, and the
has_actionable_report contract UI code should call rather than re-deriving
from status strings of its own.
"""

from __future__ import annotations

from typing import Any

ACTIONABLE_STATUSES = {"cancelled", "failed", "complete_with_warnings"}


def has_actionable_report(status: str) -> bool:
    """True when there's a real reason to open the report: the export was
    interrupted, ended with a warning, or failed. False for a clean
    completed export with only harmless informational data. This is the
    single source of truth -- UI code should call this rather than
    re-deriving the same status set on its own."""
    return status in ACTIONABLE_STATUSES


def validate_report_consistency(report: dict[str, Any]) -> list[str]:
    """Structural invariants EXPORT_REPORT.json must always satisfy. Never
    silently tolerate summary counts disagreeing with the actual
    structured diagnostic lists -- this is exactly the class of bug behind
    a historical real report that had summary.warnings == 192 while its
    structured warnings list was empty."""
    problems: list[str] = []
    if not report.get("report_schema_version"):
        problems.append("report_schema_version is missing")
    summary = report.get("summary") or {}
    warnings = report.get("warnings") or []
    errors = report.get("errors") or []
    if "warnings" in summary and summary["warnings"] != len(warnings):
        problems.append(
            f"summary.warnings ({summary['warnings']}) != len(warnings) ({len(warnings)})"
        )
    if "errors" in summary and summary["errors"] != len(errors):
        problems.append(f"summary.errors ({summary['errors']}) != len(errors) ({len(errors)})")
    export = report.get("export") or {}
    for field in ("export_number", "research_number", "status"):
        if export.get(field) is None:
            problems.append(f"export.{field} is missing")
    return problems


def reconcile_raw_and_dataset(
    raw_videos: list[dict[str, Any]], dataset: dict[str, Any]
) -> list[str]:
    """Cross-check that every video ID the dataset claims as high-signal or
    baseline really exists in RAW/videos.json, that no video is selected as
    both, and that no ID appears twice within either list. A mismatch here
    means the dataset is making a claim its own RAW evidence can't back up."""
    from .dataset import video_identity

    problems: list[str] = []
    raw_ids = {video_identity(video) for video in raw_videos}

    high_signal_ids = [video_identity(video) for video in dataset.get("high_signal_videos") or []]
    baseline_ids = [video_identity(video) for video in dataset.get("baseline_video_sample") or []]

    missing_hs = [vid for vid in high_signal_ids if vid not in raw_ids]
    if missing_hs:
        problems.append(
            f"{len(missing_hs)} high_signal_videos ID(s) not found in RAW videos: {missing_hs[:5]}"
        )
    missing_bl = [vid for vid in baseline_ids if vid not in raw_ids]
    if missing_bl:
        problems.append(
            f"{len(missing_bl)} baseline_video_sample ID(s) not found in RAW videos: {missing_bl[:5]}"
        )

    overlap = set(high_signal_ids) & set(baseline_ids)
    if overlap:
        problems.append(
            f"{len(overlap)} video ID(s) appear in both high_signal_videos and "
            f"baseline_video_sample: {sorted(overlap)[:5]}"
        )

    dupe_hs = len(high_signal_ids) - len(set(high_signal_ids))
    if dupe_hs:
        problems.append(f"{dupe_hs} duplicate ID(s) within high_signal_videos itself")
    dupe_bl = len(baseline_ids) - len(set(baseline_ids))
    if dupe_bl:
        problems.append(f"{dupe_bl} duplicate ID(s) within baseline_video_sample itself")

    unresolved = set(dataset.get("relationships", {}).get("unresolved_evidence_video_ids") or [])
    contradicted = unresolved & raw_ids
    if contradicted:
        problems.append(
            f"{len(contradicted)} 'unresolved' evidence ID(s) actually DO exist in RAW: "
            f"{sorted(contradicted)[:5]}"
        )

    return problems


def check_no_secrets(text: str) -> list[str]:
    """Defense in depth: confirm redact_secrets() would not have changed
    this text -- i.e. it never contained a token/bearer-shaped pattern."""
    from .report import redact_secrets

    if redact_secrets(text) != text:
        return ["secret-looking content found (token/bearer pattern)"]
    return []
