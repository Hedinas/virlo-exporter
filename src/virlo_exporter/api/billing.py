from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class BillingClass(StrEnum):
    FREE_READ = "FREE_READ"
    PAID_ACTION = "PAID_ACTION"
    CONDITIONAL_COST = "CONDITIONAL_COST"


@dataclass(frozen=True, slots=True)
class PriceEstimate:
    base: float
    data_intelligence: float = 0.0
    meta_ads: float = 0.0

    @property
    def total(self) -> float:
        return self.base + self.data_intelligence + self.meta_ads


class BillingSafety:
    """Central allow-list and pricing snapshot from Virlo docs (checked 2026-08-25)."""

    BASE_AGENT_RUN = 0.50
    DATA_INTELLIGENCE_ADDON = 1.00

    FREE_AGENT_RESOURCES = {
        "agent",
        "runs",
        "run",
        "videos",
        "slideshows",
        "ads",
        "outliers",
        "sounds",
        "hashtags",
        "benchmarks",
        "affinity",
        "analysis",
        "trends",
        "activity",
        "proposals",
    }

    @classmethod
    def estimate_agent(cls, *, data_intelligence: bool) -> PriceEstimate:
        return PriceEstimate(
            base=cls.BASE_AGENT_RUN,
            data_intelligence=cls.DATA_INTELLIGENCE_ADDON if data_intelligence else 0,
        )

    @classmethod
    def classify(
        cls, method: str, path: str, *, data_intelligence_enabled: bool = False
    ) -> BillingClass:
        normalized = "/" + path.lstrip("/")
        if method.upper() == "POST" and normalized.endswith("/agents/suggest-keywords"):
            return BillingClass.FREE_READ
        if method.upper() == "POST" and normalized.endswith("/agents"):
            return BillingClass.PAID_ACTION
        if method.upper() == "GET" and normalized.endswith("/hooks"):
            return (
                BillingClass.FREE_READ
                if data_intelligence_enabled
                else BillingClass.CONDITIONAL_COST
            )
        if method.upper() == "GET" and "/agents" in normalized:
            return BillingClass.FREE_READ
        if method.upper() in {"PUT", "DELETE"} and "/agents/" in normalized:
            return BillingClass.FREE_READ
        return BillingClass.CONDITIONAL_COST

    @staticmethod
    def response_cost(headers: Mapping[str, str]) -> tuple[float | None, float | None]:
        def number(*names: str) -> float | None:
            for name in names:
                value = headers.get(name)
                if value not in {None, ""}:
                    try:
                        return float(value)
                    except ValueError:
                        pass
            return None

        cost = number("x-cost")
        if cost is None:
            credits = number("x-credits-used")
            cost = credits / 100 if credits is not None else None
        balance = number("x-balance-remaining")
        if balance is None:
            credits = number("x-credits-remaining")
            balance = credits / 100 if credits is not None else None
        return cost, balance
