from __future__ import annotations

import re
from typing import Any

_DUPLICATE_PATTERN = re.compile(r"^Duplicate (?P<resource>\S+) id skipped: (?P<id>.+)$")
_COUNT_MISMATCH_PATTERN = re.compile(
    r"^Expected (?P<expected>\d+) (?P<resource>\S+) records; received (?P<actual>\d+)\.$"
)


def classify_pagination_warnings(
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split Paginator-produced warning strings into (notices, real_warnings,
    deduplications).

    Duplicate-ID skips are always a safe, intentional deduplication -- the
    exporter saw the same record twice across pages and kept one copy. A
    resulting "expected N, received M" record-count mismatch is only a
    harmless notice when it's fully explained by those same duplicates for
    that resource; anything left unexplained is a real warning, since it
    may mean data was actually lost.
    """
    dedup_counts: dict[str, int] = {}
    mismatches: list[tuple[str, int, int]] = []
    other: list[str] = []

    for message in warnings:
        duplicate_match = _DUPLICATE_PATTERN.match(message)
        if duplicate_match:
            resource = duplicate_match.group("resource")
            dedup_counts[resource] = dedup_counts.get(resource, 0) + 1
            continue
        mismatch_match = _COUNT_MISMATCH_PATTERN.match(message)
        if mismatch_match:
            mismatches.append(
                (
                    mismatch_match.group("resource"),
                    int(mismatch_match.group("expected")),
                    int(mismatch_match.group("actual")),
                )
            )
            continue
        other.append(message)

    deduplications = [
        {"resource": resource, "count": count} for resource, count in sorted(dedup_counts.items())
    ]

    notices: list[dict[str, Any]] = []
    real_warnings: list[dict[str, Any]] = []
    for resource, expected, actual in mismatches:
        gap = expected - actual
        if gap > 0 and dedup_counts.get(resource, 0) >= gap:
            notices.append(
                {
                    "type": "record_count_reconciled_by_deduplication",
                    "resource": resource,
                    "expected": expected,
                    "received": actual,
                    "message": (
                        f"Expected {expected} {resource} records; received {actual} "
                        f"after safely removing {gap} duplicate page overlap(s)."
                    ),
                }
            )
        else:
            real_warnings.append(
                {
                    "stage": resource,
                    "endpoint": None,
                    "http_status": None,
                    "error_code": None,
                    "message": f"Expected {expected} {resource} records; received {actual}.",
                }
            )

    for message in other:
        real_warnings.append(
            {
                "stage": None,
                "endpoint": None,
                "http_status": None,
                "error_code": None,
                "message": message,
            }
        )

    return notices, real_warnings, deduplications
