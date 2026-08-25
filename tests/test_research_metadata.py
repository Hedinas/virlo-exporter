from __future__ import annotations

from virlo_exporter.models import Run
from virlo_exporter.storage.database import Database
from virlo_exporter.ui.logic import research_matches


def test_research_rename_persists_and_leaves_number_unchanged(tmp_path) -> None:
    db = Database(tmp_path / "state.db")
    mapping = db.assign_runs("agent-1", [{"id": "run-1", "started_at": "2026-01-01"}])
    number_before = db.research_number("agent-1", "run-1")

    db.rename_research("agent-1", "run-1", "Fandom Products - August")
    assert db.research_display_name("agent-1", "run-1") == "Fandom Products - August"
    assert db.research_number("agent-1", "run-1") == number_before
    assert mapping["run-1"] == number_before

    db.rename_research("agent-1", "run-1", "Renamed Again")
    assert db.research_display_name("agent-1", "run-1") == "Renamed Again"
    assert db.research_number("agent-1", "run-1") == number_before


def test_research_search_matches_custom_name_number_agent_and_run_id() -> None:
    run = Run(
        id="a1b2c3d4-run-id",
        agent_id="agent-1",
        status="completed",
        started_at="2026-08-25T14:31:00Z",
        local_number=14,
    )
    assert research_matches("fandom", "Raxeko", run, "Fandom Products - August")
    assert research_matches("research #014", "Raxeko", run, "Fandom Products - August")
    assert research_matches("raxeko", "Raxeko", run, "Fandom Products - August")
    assert research_matches("a1b2c3d4-run-id", "Raxeko", run, "Fandom Products - August")
    assert not research_matches("nonexistent", "Raxeko", run, "Fandom Products - August")


def test_research_search_matches_by_agent_name_without_custom_name() -> None:
    run = Run(id="run-2", agent_id="agent-2", status="completed", local_number=3)
    assert research_matches("raxeko", "Raxeko", run, None)
    assert research_matches("research #003", "Raxeko", run, None)
