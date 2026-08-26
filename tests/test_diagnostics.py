from __future__ import annotations

from virlo_exporter.export.diagnostics import classify_pagination_warnings


def test_duplicate_ids_become_deduplications_not_warnings() -> None:
    warnings = [
        "Duplicate videos id skipped: abc",
        "Duplicate videos id skipped: def",
        "Duplicate sounds id skipped: xyz",
    ]
    notices, real_warnings, deduplications = classify_pagination_warnings(warnings)
    assert real_warnings == []
    assert notices == []
    assert {"resource": "videos", "count": 2} in deduplications
    assert {"resource": "sounds", "count": 1} in deduplications


def test_count_mismatch_fully_explained_by_duplicates_is_a_notice() -> None:
    warnings = [
        "Duplicate videos id skipped: a",
        "Duplicate videos id skipped: b",
        "Expected 100 videos records; received 98.",
    ]
    notices, real_warnings, deduplications = classify_pagination_warnings(warnings)
    assert real_warnings == []
    assert len(notices) == 1
    assert notices[0]["resource"] == "videos"
    assert notices[0]["expected"] == 100
    assert notices[0]["received"] == 98
    assert deduplications == [{"resource": "videos", "count": 2}]


def test_count_mismatch_not_explained_by_duplicates_is_a_real_warning() -> None:
    # Only one duplicate observed, but 5 records are missing -- real data loss.
    warnings = [
        "Duplicate videos id skipped: a",
        "Expected 100 videos records; received 95.",
    ]
    notices, real_warnings, deduplications = classify_pagination_warnings(warnings)
    assert notices == []
    assert len(real_warnings) == 1
    assert real_warnings[0]["message"] == "Expected 100 videos records; received 95."
    assert deduplications == [{"resource": "videos", "count": 1}]


def test_unrecognized_message_is_a_real_warning() -> None:
    notices, real_warnings, deduplications = classify_pagination_warnings(
        ["Something unexpected happened."]
    )
    assert notices == []
    assert deduplications == []
    assert real_warnings == [
        {
            "stage": None,
            "endpoint": None,
            "http_status": None,
            "error_code": None,
            "message": "Something unexpected happened.",
        }
    ]


def test_empty_input_produces_empty_groups() -> None:
    assert classify_pagination_warnings([]) == ([], [], [])
