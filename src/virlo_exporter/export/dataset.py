from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from copy import deepcopy
from typing import Any


def video_identity(video: dict[str, Any]) -> str:
    identifier = video.get("id") or video.get("video_id")
    if identifier:
        return str(identifier)
    return f"{video.get('platform', '')}|{video.get('url', '')}"


def _find_evidence_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"evidence_video_id", "video_id"} and isinstance(child, (str, int)):
                found.add(str(child))
            elif key in {"evidence_video_ids", "video_ids", "related_video_ids"} and isinstance(
                child, list
            ):
                found.update(str(item) for item in child if isinstance(item, (str, int)))
            found.update(_find_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_evidence_ids(child))
    return found


def _metric(video: dict[str, Any], name: str) -> float:
    try:
        return float(video.get(name) or 0)
    except (TypeError, ValueError):
        return 0


def select_high_signal(
    videos: list[dict[str, Any]],
    resources: dict[str, Any],
    *,
    top_per_platform: int = 25,
) -> tuple[list[dict[str, Any]], list[str]]:
    by_id = {video_identity(video): video for video in videos if video_identity(video) != "|"}
    reasons: dict[str, set[str]] = defaultdict(set)

    evidence_sources = {
        "analysis": "analysis_evidence",
        "trends": "trend_evidence",
        "hooks": "top_hook",
        "outliers": "creator_outlier",
    }
    unresolved: set[str] = set()
    for resource, reason in evidence_sources.items():
        for identifier in _find_evidence_ids(resources.get(resource, [])):
            if identifier in by_id:
                reasons[identifier].add(reason)
            else:
                unresolved.add(identifier)

    # Some outlier payloads embed whole video objects rather than just IDs.
    for item in resources.get("outliers", []) or []:
        if not isinstance(item, dict):
            continue
        for embedded in item.get("videos", []) or []:
            if isinstance(embedded, dict):
                key = video_identity(embedded)
                if key in by_id:
                    reasons[key].add("creator_outlier")

    by_platform: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for video in videos:
        by_platform[str(video.get("platform") or "unknown")].append(video)
        intent_match = video.get("intent_match")
        if isinstance(intent_match, dict) and intent_match.get("matches") is True:
            score = _metric(video, "virality_score") or _metric(video, "outlier_score")
            if score >= 2:
                reasons[video_identity(video)].add("high_intent_match")
    for platform_videos in by_platform.values():
        ranked = sorted(
            platform_videos,
            key=lambda item: (
                _metric(item, "virality_score") or _metric(item, "outlier_score"),
                _metric(item, "views"),
            ),
            reverse=True,
        )
        for video in ranked[:top_per_platform]:
            reasons[video_identity(video)].add("top_performer")

    selected: list[dict[str, Any]] = []
    for key, selection_reasons in reasons.items():
        if key not in by_id:
            continue
        record = deepcopy(by_id[key])
        record["_selection"] = {"reasons": sorted(selection_reasons)}
        selected.append(record)
    selected.sort(key=lambda item: _metric(item, "views"), reverse=True)
    return selected, sorted(unresolved)


def deterministic_baseline(
    videos: list[dict[str, Any]], selected: list[dict[str, Any]], sample_size: int
) -> list[dict[str, Any]]:
    if sample_size <= 0:
        return []
    excluded = {video_identity(video) for video in selected}
    candidates = [video for video in videos if video_identity(video) not in excluded]
    if len(candidates) <= sample_size:
        return candidates

    strata: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    views_sorted = sorted(_metric(video, "views") for video in candidates)
    q1 = views_sorted[len(views_sorted) // 3]
    q2 = views_sorted[(len(views_sorted) * 2) // 3]
    for video in candidates:
        views = _metric(video, "views")
        bucket = 0 if views <= q1 else (1 if views <= q2 else 2)
        strata[(str(video.get("platform") or "unknown"), bucket)].append(video)

    # Stable hashing makes repeated exports comparable without pretending to analyze content.
    for values in strata.values():
        values.sort(
            key=lambda item: hashlib.sha256(video_identity(item).encode("utf-8")).hexdigest()
        )
    result: list[dict[str, Any]] = []
    groups = sorted(strata)
    while len(result) < sample_size and groups:
        next_groups: list[tuple[str, int]] = []
        for group in groups:
            if strata[group] and len(result) < sample_size:
                result.append(strata[group].pop(0))
            if strata[group]:
                next_groups.append(group)
        groups = next_groups
    return result


def count_platforms(videos: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for video in videos:
        counts[str(video.get("platform") or "unknown")] += 1
    return dict(sorted(counts.items()))
