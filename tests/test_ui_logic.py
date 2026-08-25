from virlo_exporter.models import Agent, Run
from virlo_exporter.ui.logic import (
    INTENT_LIMIT,
    KEYWORD_LIMIT,
    add_keyword,
    agent_display_status,
    clamp_intent,
    counter_state,
)


def test_intent_is_hard_limited_to_500_characters() -> None:
    assert len(clamp_intent("x" * 501)) == INTENT_LIMIT
    assert clamp_intent("x" * 499) == "x" * 499
    assert counter_state(449, near=450, maximum=500) == "normal"
    assert counter_state(450, near=450, maximum=500) == "near"
    assert counter_state(500, near=450, maximum=500) == "exact"


def test_keyword_limit_trim_and_duplicate_rules() -> None:
    values, result = add_keyword([], "  useful phrase  ")
    assert values == ["useful phrase"]
    assert result == "added"
    unchanged, result = add_keyword(values, "useful phrase")
    assert unchanged == values
    assert result == "duplicate"
    full = [f"keyword-{index}" for index in range(KEYWORD_LIMIT)]
    unchanged, result = add_keyword(full, "keyword-51")
    assert unchanged == full
    assert result == "limit"


def test_one_time_agent_uses_derived_display_status_only() -> None:
    agent = Agent(id="a", name="Agent", active=True, is_recurring=False)
    completed = Run(id="r", agent_id="a", status="completed")
    processing = Run(id="r2", agent_id="a", status="processing")
    assert agent_display_status(agent, [completed]) == "Completed"
    assert agent_display_status(agent, [processing]) == "Processing"
    assert agent.active is True


def test_recurring_agent_display_status() -> None:
    active = Agent(id="a", name="Agent", active=True, is_recurring=True)
    paused = Agent(id="b", name="Agent", active=False, is_recurring=True)
    assert agent_display_status(active) == "Active"
    assert agent_display_status(paused) == "Paused"
