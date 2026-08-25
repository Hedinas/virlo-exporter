from __future__ import annotations

import pytest

from virlo_exporter.api.errors import MalformedResponseError, PaginationError
from virlo_exporter.api.pagination import Paginator


def test_shape_a_paginates_to_total() -> None:
    calls = []

    def fetch(query: dict[str, int]) -> dict:
        calls.append(query.copy())
        offset = query["offset"]
        records = [{"id": str(i)} for i in range(offset, min(offset + 2, 5))]
        return {"data": {"videos": records, "total": 5, "limit": 2, "offset": offset}}

    result = Paginator(limit=2).collect(fetch, "videos")
    assert [row["id"] for row in result.records] == ["0", "1", "2", "3", "4"]
    assert result.pages == 3
    assert result.expected_total == 5
    assert [call["offset"] for call in calls] == [0, 2, 4]


def test_shape_b_uses_has_next_page() -> None:
    def fetch(query: dict[str, int]) -> dict:
        page = query["page"]
        return {
            "data": [{"id": str(page)}],
            "pagination": {
                "page": page,
                "limit": 1,
                "total": 3,
                "total_pages": 99,
                "has_next_page": page < 3,
            },
        }

    result = Paginator(limit=1).collect(fetch, "sounds")
    assert len(result.records) == 3
    assert result.pages == 3


def test_shape_c_stops_on_short_page() -> None:
    def fetch(query: dict[str, int]) -> dict:
        page = query["page"]
        rows = [{"id": f"{page}-{index}"} for index in range(2 if page < 3 else 1)]
        return {"data": {"agents": rows, "count": len(rows), "limit": 2, "page": page}}

    result = Paginator(limit=2).collect(fetch, "agents")
    assert len(result.records) == 5
    assert result.expected_total is None


def test_agents_shape_c_one_short_page_makes_one_request() -> None:
    calls: list[int] = []

    def fetch(query: dict[str, int]) -> dict:
        calls.append(query["page"])
        rows = [{"id": str(index)} for index in range(3)]
        return {"data": {"agents": rows, "count": 3, "limit": 100, "page": 1}}

    result = Paginator(limit=100).collect(fetch, "agents")
    assert len(result.records) == 3
    assert calls == [1]


def test_agents_shape_c_full_then_short_returns_all_records() -> None:
    calls: list[int] = []

    def fetch(query: dict[str, int]) -> dict:
        page = query["page"]
        calls.append(page)
        count = 100 if page == 1 else 17
        start = (page - 1) * 100
        rows = [{"id": str(index)} for index in range(start, start + count)]
        return {"data": {"agents": rows, "count": count, "limit": 100, "page": page}}

    result = Paginator(limit=100).collect(fetch, "agents")
    assert len(result.records) == 117
    assert calls == [1, 2]


def test_agents_repeated_full_page_fails_immediately() -> None:
    calls: list[int] = []
    rows = [{"id": str(index)} for index in range(100)]

    def fetch(query: dict[str, int]) -> dict:
        calls.append(query["page"])
        return {
            "data": {
                "agents": rows,
                "count": 100,
                "limit": 100,
                "page": query["page"],
            }
        }

    with pytest.raises(PaginationError, match="Repeated page detected while listing agents"):
        Paginator(limit=100).collect(fetch, "agents")
    assert calls == [1, 2]


def test_shape_d_is_read_once() -> None:
    calls = 0

    def fetch(_query: dict[str, int]) -> dict:
        nonlocal calls
        calls += 1
        return {"data": [{"follower_tier": "micro"}]}

    result = Paginator().collect(fetch, "benchmarks")
    assert calls == 1
    assert result.pages == 1


def test_repeated_page_detection() -> None:
    payload = {"data": {"runs": [{"id": "same"}], "count": 1, "limit": 1, "page": 1}}
    with pytest.raises(PaginationError, match="Repeated page"):
        Paginator(limit=1).collect(lambda _query: payload, "runs")


@pytest.mark.parametrize("payload", [{}, {"data": "bad"}, {"oops": []}])
def test_malformed_responses(payload: dict) -> None:
    with pytest.raises(MalformedResponseError):
        Paginator().collect(lambda _query: payload, "videos")


def test_duplicate_ids_are_skipped_with_warning() -> None:
    def fetch(query: dict[str, int]) -> dict:
        page = query["page"]
        rows = [{"id": "duplicate"}, {"id": str(page)}] if page == 1 else [{"id": "duplicate"}]
        return {"data": {"agents": rows, "count": len(rows), "limit": 2, "page": page}}

    result = Paginator(limit=2).collect(fetch, "agents")
    assert len(result.records) == 2
    assert result.warnings
