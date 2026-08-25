from virlo_exporter.export.dataset import deterministic_baseline, select_high_signal, video_identity


def videos(count: int = 30) -> list[dict]:
    return [
        {
            "id": str(index),
            "platform": ("tiktok", "instagram", "youtube")[index % 3],
            "views": index * 100,
            "url": f"https://example/{index}",
        }
        for index in range(count)
    ]


def test_high_signal_deduplicates_multiple_reasons() -> None:
    source = videos()
    resources = {
        "analysis": [{"evidence_video_ids": ["29"]}],
        "trends": [{"evidence_video_ids": ["29", "28", "missing"]}],
        "hooks": [{"video_id": "29"}],
        "outliers": [],
    }
    selected, unresolved = select_high_signal(source, resources, top_per_platform=1)
    by_id = {item["id"]: item for item in selected}
    assert len([item for item in selected if item["id"] == "29"]) == 1
    assert set(by_id["29"]["_selection"]["reasons"]) >= {
        "analysis_evidence",
        "trend_evidence",
        "top_hook",
        "top_performer",
    }
    assert unresolved == ["missing"]


def test_baseline_is_deterministic_and_excludes_selected() -> None:
    source = videos(90)
    selected, _ = select_high_signal(source, {}, top_per_platform=1)
    first = deterministic_baseline(source, selected, 15)
    second = deterministic_baseline(source, selected, 15)
    assert [video_identity(item) for item in first] == [video_identity(item) for item in second]
    assert not (
        {video_identity(item) for item in first} & {video_identity(item) for item in selected}
    )
