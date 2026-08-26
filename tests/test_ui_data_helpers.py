from __future__ import annotations

from virlo_exporter.models import Agent, Run
from virlo_exporter.ui.main_window import MainWindow


def _run(**overrides) -> Run:
    defaults = dict(
        id="run-1",
        agent_id="agent-1",
        status="completed",
        videos_linked=100,
        slideshows_linked=20,
        meta_ads_linked=5,
        outliers_identified=2,
        raw={},
    )
    defaults.update(overrides)
    return Run(**defaults)


def _agent(**overrides) -> Agent:
    defaults = dict(id="agent-1", name="Raxeko", platforms=["youtube", "tiktok", "meta_ads"])
    defaults.update(overrides)
    return Agent(**defaults)


def test_run_metrics_omits_trends_when_not_reported() -> None:
    metrics = MainWindow._run_metrics(_run())
    labels = [label for label, _ in metrics]
    assert labels == ["Videos", "Slideshows", "Meta Ads", "Outliers"]


def test_run_metrics_includes_trends_when_present() -> None:
    metrics = MainWindow._run_metrics(_run(raw={"trends_detected": 12}))
    assert ("Trends", "12") in metrics


def test_run_metrics_never_invents_hooks_sounds_hashtags() -> None:
    # These resources only exist once an export has actually fetched them --
    # the Run object itself never carries them, so the UI must never show a
    # tile for data it doesn't have.
    metrics = MainWindow._run_metrics(_run(raw={"hooks_count": 999}))
    labels = [label for label, _ in metrics]
    assert "Hooks" not in labels
    assert "Sounds" not in labels
    assert "Hashtags" not in labels


def test_platform_pills_only_lists_agent_configured_platforms() -> None:
    agent = _agent(platforms=["youtube", "tiktok", "instagram", "meta_ads"])
    run = _run(meta_ads_linked=411, raw={"youtube_count": 3518, "tiktok_count": 4141, "instagram_count": 1904})
    pills = MainWindow._platform_pills(agent, run)
    assert pills == [
        ("Youtube", 3518),
        ("Tiktok", 4141),
        ("Instagram", 1904),
        ("Meta Ads", 411),
    ]


def test_platform_pills_omits_count_when_not_available() -> None:
    agent = _agent(platforms=["youtube"])
    run = _run(raw={})
    pills = MainWindow._platform_pills(agent, run)
    assert pills == [("Youtube", None)]


def test_platform_pills_never_sums_meta_ads_into_videos() -> None:
    agent = _agent(platforms=["meta_ads"])
    run = _run(videos_linked=100, meta_ads_linked=411)
    pills = MainWindow._platform_pills(agent, run)
    assert pills == [("Meta Ads", 411)]
    # The Videos metric is untouched by Meta Ads' own count.
    metrics = dict(MainWindow._run_metrics(run))
    assert metrics["Videos"] == "100"


def test_export_duration_text_formats_minutes_and_seconds() -> None:
    record = {"started_at": "2026-08-26T05:44:00Z", "completed_at": "2026-08-26T05:45:37Z"}
    assert MainWindow._export_duration_text(record) == "1m 37s"


def test_export_duration_text_missing_timestamps_returns_none() -> None:
    assert MainWindow._export_duration_text({"started_at": None, "completed_at": None}) is None
