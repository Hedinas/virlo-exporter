from __future__ import annotations

from virlo_exporter.export.validator import (
    check_no_secrets,
    has_actionable_report,
    reconcile_raw_and_dataset,
    validate_report_consistency,
)


def test_has_actionable_report_true_for_cancelled_warning_failed() -> None:
    assert has_actionable_report("cancelled") is True
    assert has_actionable_report("failed") is True
    assert has_actionable_report("complete_with_warnings") is True


def test_has_actionable_report_false_for_clean_complete() -> None:
    assert has_actionable_report("complete") is False


def test_validate_report_consistency_catches_the_historical_192_warnings_bug() -> None:
    # The exact real-world bug this exists to prevent: summary said 192
    # warnings while the structured warnings list was empty.
    report = {
        "report_schema_version": "1.0",
        "export": {"export_number": 6, "research_number": 1, "status": "complete_with_warnings"},
        "summary": {"warnings": 192},
        "warnings": [],
    }
    problems = validate_report_consistency(report)
    assert any("192" in p and "0" in p for p in problems)


def test_validate_report_consistency_passes_when_counts_agree() -> None:
    report = {
        "report_schema_version": "1.0",
        "export": {"export_number": 1, "research_number": 1, "status": "complete"},
        "summary": {"warnings": 2, "errors": 0},
        "warnings": [{"message": "a"}, {"message": "b"}],
        "errors": [],
    }
    assert validate_report_consistency(report) == []


def test_validate_report_consistency_requires_schema_version_and_export_identity() -> None:
    problems = validate_report_consistency({})
    assert "report_schema_version is missing" in problems
    assert "export.export_number is missing" in problems
    assert "export.research_number is missing" in problems
    assert "export.status is missing" in problems


def test_reconcile_raw_and_dataset_clean_case() -> None:
    raw_videos = [{"id": "v1"}, {"id": "v2"}, {"id": "v3"}]
    dataset = {
        "high_signal_videos": [{"id": "v1"}],
        "baseline_video_sample": [{"id": "v2"}],
        "relationships": {"unresolved_evidence_video_ids": ["ghost-id"]},
    }
    assert reconcile_raw_and_dataset(raw_videos, dataset) == []


def test_reconcile_raw_and_dataset_flags_missing_high_signal_id() -> None:
    raw_videos = [{"id": "v1"}]
    dataset = {"high_signal_videos": [{"id": "v1"}, {"id": "phantom"}]}
    problems = reconcile_raw_and_dataset(raw_videos, dataset)
    assert any("phantom" in p for p in problems)


def test_reconcile_raw_and_dataset_flags_missing_baseline_id() -> None:
    raw_videos = [{"id": "v1"}]
    dataset = {"baseline_video_sample": [{"id": "phantom"}]}
    problems = reconcile_raw_and_dataset(raw_videos, dataset)
    assert any("baseline_video_sample" in p and "phantom" in p for p in problems)


def test_reconcile_raw_and_dataset_flags_overlap_between_high_signal_and_baseline() -> None:
    raw_videos = [{"id": "v1"}]
    dataset = {
        "high_signal_videos": [{"id": "v1"}],
        "baseline_video_sample": [{"id": "v1"}],
    }
    problems = reconcile_raw_and_dataset(raw_videos, dataset)
    assert any("both high_signal_videos and baseline_video_sample" in p for p in problems)


def test_reconcile_raw_and_dataset_flags_internal_duplicates() -> None:
    raw_videos = [{"id": "v1"}]
    dataset = {"high_signal_videos": [{"id": "v1"}, {"id": "v1"}]}
    problems = reconcile_raw_and_dataset(raw_videos, dataset)
    assert any("duplicate" in p and "high_signal_videos" in p for p in problems)


def test_reconcile_raw_and_dataset_flags_contradicted_unresolved_reference() -> None:
    raw_videos = [{"id": "v1"}]
    dataset = {"relationships": {"unresolved_evidence_video_ids": ["v1"]}}
    problems = reconcile_raw_and_dataset(raw_videos, dataset)
    assert any("unresolved" in p and "v1" in p for p in problems)


def test_check_no_secrets_clean_text() -> None:
    assert check_no_secrets("hello world, no tokens here") == []


def test_check_no_secrets_flags_token() -> None:
    assert check_no_secrets("key=virlo_tkn_abc123") != []


def test_check_no_secrets_flags_bearer_header() -> None:
    assert check_no_secrets("Authorization: Bearer abcdef123456") != []
