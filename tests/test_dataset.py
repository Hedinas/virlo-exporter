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


def test_baseline_order_is_independent_of_input_order_in_round_robin_path() -> None:
    # Exercises the stratified round-robin path (candidates > sample_size).
    source = videos(90)
    shuffled = list(source)
    import random

    random.Random(7).shuffle(shuffled)
    selected, _ = select_high_signal(source, {}, top_per_platform=1)
    baseline_forward = deterministic_baseline(source, selected, 15)
    baseline_shuffled = deterministic_baseline(shuffled, selected, 15)
    assert [video_identity(item) for item in baseline_forward] == [
        video_identity(item) for item in baseline_shuffled
    ]


def test_baseline_order_is_independent_of_input_order_when_pool_smaller_than_sample() -> None:
    # Regression test for a real bug: when there are fewer candidates than
    # the requested sample size, the function used to short-circuit and
    # return them in raw input order -- which differs depending on how the
    # API happened to order pages on a given fetch. Every candidate is
    # returned either way (nothing to sample), but the *order* must not
    # depend on input order.
    source = videos(5)
    shuffled = list(reversed(source))
    baseline_forward = deterministic_baseline(source, [], sample_size=20)
    baseline_reversed = deterministic_baseline(shuffled, [], sample_size=20)
    assert len(baseline_forward) == 5
    assert [video_identity(item) for item in baseline_forward] == [
        video_identity(item) for item in baseline_reversed
    ]


def test_top_performer_selection_is_order_independent_even_with_tied_scores() -> None:
    # Regression/audit test for a real determinism risk: the API's own
    # pagination ordering across two separate fetches of the "same"
    # completed Research is not documented as stable (Paginator's repeated-
    # page guard exists precisely because it sometimes isn't). If two
    # videos are genuinely tied on (score, views), Python's stable sort
    # breaks the tie by input-list position -- so if the *input order*
    # itself isn't guaranteed stable across fetches, a tied video could
    # fall on either side of the top-25-per-platform cutoff depending on
    # which fetch happened to run. Prove the *result set* selected is the
    # same regardless of input order when a genuine tie sits at the cutoff.
    platform_videos = [
        {"id": f"tie-{i}", "platform": "tiktok", "views": 1000, "url": f"https://x/{i}"}
        for i in range(30)  # 30 videos every one of them exactly tied
    ]
    forward = list(platform_videos)
    reversed_order = list(reversed(platform_videos))

    selected_forward, _ = select_high_signal(forward, {}, top_per_platform=25)
    selected_reversed, _ = select_high_signal(reversed_order, {}, top_per_platform=25)

    ids_forward = {video_identity(item) for item in selected_forward}
    ids_reversed = {video_identity(item) for item in selected_reversed}
    assert len(ids_forward) == 25
    assert ids_forward == ids_reversed, (
        "top-performer selection changed which videos were picked when the "
        "input order was reversed, even though every video was tied on "
        "(score, views) -- selection is not truly deterministic across "
        "fetches whose page ordering may differ"
    )
