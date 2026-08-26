from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from .billing import BillingClass, BillingSafety
from .errors import (
    AuthenticationError,
    InsufficientBalanceError,
    MalformedResponseError,
    NetworkError,
    RateLimitError,
    VirloError,
)
from .pagination import PageResult, Paginator

logger = logging.getLogger(__name__)


class VirloClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.virlo.ai/v1",
        timeout: float = 45.0,
        transport: httpx.BaseTransport | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.event_callback = event_callback
        self.last_balance: float | None = None
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
            timeout=httpx.Timeout(timeout, connect=15),
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _emit(self, **event: Any) -> None:
        if self.event_callback:
            self.event_callback(event)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        billing_class: BillingClass | None = None,
        retries: int = 3,
    ) -> tuple[dict[str, Any], httpx.Headers]:
        billing_class = billing_class or BillingSafety.classify(method, path)
        # Paid writes are never blindly retried: an ambiguous timeout may already have charged.
        attempts = 1 if billing_class == BillingClass.PAID_ACTION else max(1, retries)
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                response = self._http.request(method, path, params=params, json=json_body)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                self._emit(
                    operation="request",
                    endpoint=path,
                    retry=attempt < attempts,
                    error=type(exc).__name__,
                )
                if attempt >= attempts:
                    if billing_class == BillingClass.PAID_ACTION:
                        raise NetworkError(
                            "The paid request had an ambiguous network failure. It was not retried to avoid a duplicate charge; refresh Agents before trying again.",
                            details=str(exc),
                        ) from exc
                    raise NetworkError(
                        "Virlo is unreachable. Check your connection and try again.",
                        details=str(exc),
                    ) from exc
                time.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.25))
                continue

            duration_ms = round((time.monotonic() - started) * 1000)
            cost, balance = BillingSafety.response_cost(response.headers)
            if balance is not None:
                self.last_balance = balance
            self._emit(
                operation="request",
                endpoint=path,
                method=method.upper(),
                status=response.status_code,
                duration_ms=duration_ms,
                cost=cost,
                balance=balance,
                retry=attempt > 1,
            )

            if response.status_code == 401:
                raise AuthenticationError(
                    "Virlo authentication failed. Check your API key.", status_code=401
                )
            if response.status_code == 402:
                raise InsufficientBalanceError(self._safe_json(response))
            if response.status_code == 429:
                retry_after = self._retry_after(response)
                if attempt < attempts:
                    self._emit(operation="rate_limit", endpoint=path, retry_after=retry_after)
                    time.sleep(retry_after)
                    continue
                raise RateLimitError(retry_after, self._safe_json(response))
            if (
                response.status_code in {408} or response.status_code >= 500
            ) and attempt < attempts:
                time.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.5))
                continue
            if response.is_error:
                details = self._safe_json(response)
                message = details.get("message") if isinstance(details, dict) else None
                raise VirloError(
                    message or f"Virlo request failed ({response.status_code}).",
                    status_code=response.status_code,
                    details=details,
                )
            if response.status_code == 204:
                return {"data": None}, response.headers
            try:
                payload = response.json()
            except ValueError as exc:
                raise MalformedResponseError(
                    "Virlo returned invalid JSON.", status_code=response.status_code
                ) from exc
            if not isinstance(payload, dict):
                raise MalformedResponseError("Virlo returned an unexpected response shape.")
            return payload, response.headers
        raise AssertionError("unreachable")

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"message": response.text[:500]}

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        value = response.headers.get("Retry-After", "")
        try:
            return min(60.0, max(0.5, float(value)))
        except ValueError:
            body = VirloClient._safe_json(response)
            try:
                return min(60.0, max(0.5, float(body.get("retry_after", 2))))
            except (AttributeError, TypeError, ValueError):
                return 2.0

    def test_connection(self) -> dict[str, Any]:
        # A connection check must never attempt to enumerate the entire account.
        # A one-page authenticated Shape C read is sufficient and avoids treating
        # a full first page as a pagination safety failure.
        payload = self.request(
            "GET",
            "/agents",
            params={"limit": 1, "page": 1},
            billing_class=BillingClass.FREE_READ,
        )[0]
        records, shape, _metadata = Paginator._unpack(payload, "agents")
        if shape != "C":
            raise MalformedResponseError("Virlo returned an unexpected Agents list shape.")
        return {"connected": True, "agent_count_on_page": len(records)}

    def suggest_keywords(self, payload: dict[str, Any]) -> tuple[dict[str, Any], httpx.Headers]:
        return self.request(
            "POST",
            "/agents/suggest-keywords",
            json_body=payload,
            billing_class=BillingClass.FREE_READ,
        )

    def create_agent(self, payload: dict[str, Any]) -> tuple[dict[str, Any], httpx.Headers]:
        return self.request(
            "POST", "/agents", json_body=payload, billing_class=BillingClass.PAID_ACTION
        )

    def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request(
            "PUT", f"/agents/{agent_id}", json_body=payload, billing_class=BillingClass.FREE_READ
        )[0]

    def delete_agent(self, agent_id: str) -> None:
        self.request("DELETE", f"/agents/{agent_id}", billing_class=BillingClass.FREE_READ)

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self.request("GET", f"/agents/{agent_id}", billing_class=BillingClass.FREE_READ)[0]

    def get_run(self, agent_id: str, run_id: str) -> dict[str, Any]:
        return self.request(
            "GET", f"/agents/{agent_id}/runs/{run_id}", billing_class=BillingClass.FREE_READ
        )[0]

    def list_agents(self, *, limit: int = 100, max_pages: int = 10000) -> PageResult:
        paginator = Paginator(limit, max_pages)
        return paginator.collect(
            lambda paging: self.request(
                "GET",
                "/agents",
                params={"limit": paging["limit"], "page": paging["page"]},
                billing_class=BillingClass.FREE_READ,
            )[0],
            "agents",
        )

    def list_runs(self, agent_id: str, *, limit: int = 100, max_pages: int = 10000) -> PageResult:
        paginator = Paginator(limit, max_pages)
        return paginator.collect(
            lambda paging: self.request(
                "GET",
                f"/agents/{agent_id}/runs",
                params={
                    "limit": paging["limit"],
                    "page": paging["page"],
                },
                billing_class=BillingClass.FREE_READ,
            )[0],
            "runs",
        )

    def get_resource(
        self,
        agent_id: str,
        resource: str,
        *,
        data_intelligence_enabled: bool = False,
        max_pages: int = 10000,
        on_page: Callable[[int, int, int | None], None] | None = None,
    ) -> PageResult:
        routes = {
            "videos": ("videos", "videos"),
            "slideshows": ("slideshows", "slideshows"),
            "ads": ("ads", "ads"),
            "outliers": ("creators/outliers", "outliers"),
            "sounds": ("sounds", "sounds"),
            "hashtags": ("hashtags", "hashtags"),
            "benchmarks": ("benchmarks", "benchmarks"),
            "affinity": ("affinity", "affinity"),
            "analysis": ("analysis", "analysis"),
            "trends": ("trends", "trends"),
            "activity": ("activity", "activity"),
            "proposals": ("proposals", "proposals"),
            "hooks": ("hooks", "hooks"),
        }
        if resource not in routes:
            raise ValueError(f"Unsupported agent resource: {resource}")
        suffix, response_key = routes[resource]
        path = f"/agents/{agent_id}/{suffix}"
        classification = BillingSafety.classify(
            "GET", path, data_intelligence_enabled=data_intelligence_enabled
        )
        if classification != BillingClass.FREE_READ:
            raise VirloError(
                f"Skipped {resource}: its retrieval is not documented as free for this agent."
            )
        paginator = Paginator(100, max_pages)

        def fetch(paging: dict[str, int]) -> dict[str, Any]:
            # Every documented agent-resource endpoint paginates by page+limit.
            # None of them accept an "offset" query parameter — some (videos,
            # slideshows, outliers) reject it outright with a 400 validation
            # error, and others (ads) silently ignore it and keep returning
            # page 1, which the paginator then reports as a repeated page.
            params = {"limit": paging["limit"], "page": paging["page"]}
            return self.request(
                "GET", path, params=params, billing_class=BillingClass.FREE_READ
            )[0]

        return paginator.collect(fetch, response_key, on_page=on_page)
