from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TERMINAL_RUN_STATES = {"completed", "failed", "partial_failure"}


@dataclass(slots=True)
class Agent:
    id: str
    name: str
    is_recurring: bool = False
    active: bool = True
    is_processing: bool = False
    finalized: bool = False
    cadence: str | None = None
    intent: str = ""
    keywords: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    english_only: bool = True
    data_intelligence_enabled: bool = False
    meta_ads_enabled: bool = False
    created_at: str | None = None
    last_run_at: str | None = None
    next_run_at: str | None = None
    latest_run: dict[str, Any] | None = None
    pending_jobs: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Agent:
        known = {name for name in cls.__dataclass_fields__ if name != "raw"}
        values = {key: data[key] for key in known if key in data}
        values.setdefault("id", str(data.get("id", "")))
        values.setdefault("name", data.get("name") or "Untitled agent")
        values["raw"] = dict(data)
        return cls(**values)


@dataclass(slots=True)
class Run:
    id: str
    agent_id: str
    status: str = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    videos_linked: int = 0
    slideshows_linked: int = 0
    meta_ads_linked: int = 0
    outliers_identified: int = 0
    execution_time_ms: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    local_number: int | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Run:
        known = {name for name in cls.__dataclass_fields__ if name not in {"raw", "local_number"}}
        values = {key: data[key] for key in known if key in data}
        values.setdefault("id", str(data.get("id", "")))
        values.setdefault("agent_id", str(data.get("agent_id", "")))
        values["raw"] = dict(data)
        return cls(**values)
