from __future__ import annotations

import httpx
import pytest

from virlo_exporter.api.client import VirloClient
from virlo_exporter.api.errors import (
    AuthenticationError,
    InsufficientBalanceError,
    RateLimitError,
    VirloError,
)


def test_402_is_not_retried() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(402, json={"required_credits": 150, "remaining_credits": 72})

    client = VirloClient("virlo_tkn_test", transport=httpx.MockTransport(handler))
    with pytest.raises(InsufficientBalanceError, match=r"Required \$1.50"):
        client.create_agent({"intent": "x", "keywords": ["x"], "is_recurring": False})
    assert calls == 1


def test_paid_ambiguous_network_error_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("ambiguous", request=request)

    client = VirloClient("virlo_tkn_test", transport=httpx.MockTransport(handler))
    with pytest.raises(VirloError, match="not retried"):
        client.create_agent({})
    assert calls == 1


def test_429_surfaces_retry_after() -> None:
    client = VirloClient(
        "virlo_tkn_test",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(429, headers={"Retry-After": "8"}, json={})
        ),
    )
    with pytest.raises(RateLimitError) as raised:
        client.request("GET", "/agents", retries=1)
    assert raised.value.retry_after == 8


def test_agents_page_parameter_is_propagated_to_http_requests() -> None:
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        limit = int(request.url.params["limit"])
        requested_pages.append(page)
        count = 100 if page == 1 else 17
        start = (page - 1) * limit
        rows = [{"id": str(index)} for index in range(start, start + count)]
        return httpx.Response(
            200,
            json={
                "data": {
                    "agents": rows,
                    "count": count,
                    "limit": limit,
                    "page": page,
                }
            },
        )

    client = VirloClient("virlo_tkn_test", transport=httpx.MockTransport(handler))
    result = client.list_agents(limit=100)
    assert len(result.records) == 117
    assert requested_pages == [1, 2]


def test_runs_page_parameter_is_propagated_without_offset() -> None:
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/agents/agent-1/runs"
        assert "offset" not in request.url.params
        page = int(request.url.params["page"])
        limit = int(request.url.params["limit"])
        requested_pages.append(page)
        count = 100 if page == 1 else 2
        start = (page - 1) * limit
        rows = [{"id": f"run-{index}"} for index in range(start, start + count)]
        return httpx.Response(
            200,
            json={
                "data": {
                    "runs": rows,
                    "count": count,
                    "limit": limit,
                    "page": page,
                }
            },
        )

    client = VirloClient("virlo_tkn_test", transport=httpx.MockTransport(handler))
    result = client.list_runs("agent-1", limit=100)
    assert len(result.records) == 102
    assert requested_pages == [1, 2]


def test_connection_check_reads_one_page_only_even_when_full() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["page"] == "1"
        assert request.url.params["limit"] == "1"
        return httpx.Response(
            200,
            json={
                "data": {
                    "agents": [{"id": "existing-agent"}],
                    "count": 1,
                    "limit": 1,
                    "page": 1,
                }
            },
        )

    client = VirloClient("virlo_tkn_test", transport=httpx.MockTransport(handler))
    assert client.test_connection() == {"connected": True, "agent_count_on_page": 1}
    assert calls == 1


def test_401_has_human_authentication_message_and_bearer_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer virlo_tkn_test"
        return httpx.Response(401, json={"message": "Unauthorized"})

    client = VirloClient("virlo_tkn_test", transport=httpx.MockTransport(handler))
    with pytest.raises(
        AuthenticationError, match="Virlo authentication failed. Check your API key."
    ):
        client.test_connection()
