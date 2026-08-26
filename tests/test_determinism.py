from __future__ import annotations

import json
import random
from datetime import UTC, datetime

from virlo_exporter.export.engine import ExportEngine


class _FakeClient:
    base_url = "https://api.virlo.ai/v1"


def _videos(count: int) -> list[dict]:
    videos = []
    for i in range(count):
        # Deliberate ties: every third video shares (virality_score, views)
        # with two others, so any order-dependent tie-breaking would show up.
        bucket = i % 10
        videos.append(
            {
                "id": f"v{i}",
                "platform": ("tiktok", "youtube", "instagram")[i % 3],
                "views": 1000 * bucket,
                "virality_score": float(bucket),
                "url": f"https://example/{i}",
            }
        )
    return videos


def _resources(videos: list[dict]) -> dict:
    return {
        "videos": videos,
        "slideshows": [],
        "ads": [],
        "outliers": [],
        "analysis": [],
        "trends": [],
        "sounds": [],
        "hashtags": [],
        "benchmarks": [],
        "affinity": [],
        "activity": [],
        "proposals": [],
        "hooks": [],
    }


def _build(videos_order: list[dict]) -> dict:
    from virlo_exporter.export.dataset import deterministic_baseline, select_high_signal

    engine = ExportEngine(_FakeClient(), database=None, export_root=None)  # type: ignore[arg-type]
    resources = _resources(videos_order)
    high_signal, unresolved = select_high_signal(resources["videos"], resources)
    baseline = deterministic_baseline(resources["videos"], high_signal, 20)
    started = datetime(2026, 1, 1, tzinfo=UTC)
    dataset = engine._build_dataset(  # noqa: SLF001 - testing determinism of internals directly
        agent={"id": "agent-1", "name": "Raxeko", "platforms": ["tiktok"]},
        run={"id": "run-1"},
        resources=resources,
        manifest={"resources": {}, "warnings": [], "errors": []},
        research_number=1,
        export_number=1,
        started=started,
        high_signal=high_signal,
        baseline=baseline,
        unresolved=unresolved,
    )
    return dataset


def _normalized(dataset: dict) -> str:
    # exported_at/timestamps are explicitly allowed to differ (item 8) --
    # everything else must be byte-identical between two builds of the same
    # underlying data.
    clean = json.loads(json.dumps(dataset, default=str))
    clean.get("_dataset_info", {}).pop("exported_at", None)
    return json.dumps(clean, sort_keys=True, ensure_ascii=True)


def test_dataset_build_is_deterministic_across_shuffled_input_order() -> None:
    videos = _videos(90)
    forward = list(videos)
    shuffled = list(videos)
    random.Random(42).shuffle(shuffled)  # fixed seed -- reproducible test, not flaky

    dataset_a = _build(forward)
    dataset_b = _build(shuffled)

    assert _normalized(dataset_a) == _normalized(dataset_b)


def test_dataset_build_is_byte_identical_on_repeated_calls_with_same_order() -> None:
    videos = _videos(60)
    dataset_a = _build(list(videos))
    dataset_b = _build(list(videos))
    assert _normalized(dataset_a) == _normalized(dataset_b)
