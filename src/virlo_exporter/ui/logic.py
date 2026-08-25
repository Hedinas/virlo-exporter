from __future__ import annotations

from collections.abc import Iterable

from virlo_exporter.models import TERMINAL_RUN_STATES, Agent, Run

INTENT_LIMIT = 500
INTENT_NEAR_LIMIT = 450
KEYWORD_LIMIT = 50
KEYWORD_NEAR_LIMIT = 45


def clamp_intent(value: str) -> str:
    return value[:INTENT_LIMIT]


def counter_state(count: int, *, near: int, maximum: int) -> str:
    if count >= maximum:
        return "exact"
    if count >= near:
        return "near"
    return "normal"


def add_keyword(existing: Iterable[str], raw_value: str) -> tuple[list[str], str]:
    values = list(existing)
    value = raw_value.strip()
    if not value:
        return values, "empty"
    if value in values:
        return values, "duplicate"
    if len(values) >= KEYWORD_LIMIT:
        return values, "limit"
    values.append(value)
    return values, "added"


def agent_display_status(agent: Agent, runs: Iterable[Run] = ()) -> str:
    known_runs = list(runs)
    latest_status = str((agent.latest_run or {}).get("status") or "").casefold()
    if agent.is_processing or latest_status in {"pending", "running", "processing"}:
        return "Processing"
    if any(run.status.casefold() in {"pending", "running", "processing"} for run in known_runs):
        return "Processing"
    if agent.is_recurring:
        return "Active" if agent.active else "Paused"
    terminal = [run.status.casefold() for run in known_runs if run.status.casefold()]
    if latest_status == "failed" or (terminal and terminal[0] == "failed"):
        return "Failed"
    if agent.finalized or latest_status in TERMINAL_RUN_STATES or any(
        status in TERMINAL_RUN_STATES for status in terminal
    ):
        return "Completed"
    return "Ready"


def run_timestamp(run: Run) -> str:
    return run.started_at or run.completed_at or str(run.raw.get("created_at") or "")


def research_search_text(
    agent_name: str, run: Run, display_name: str | None = None
) -> str:
    return " ".join(
        (
            display_name or "",
            f"research #{run.local_number or 0:03d}",
            f"research {run.local_number or 0:03d}",
            agent_name,
            run.id,
            run.status,
            run_timestamp(run),
        )
    ).casefold()


def research_matches(
    query: str, agent_name: str, run: Run, display_name: str | None = None
) -> bool:
    return query.casefold().strip() in research_search_text(agent_name, run, display_name)
