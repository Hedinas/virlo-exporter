from __future__ import annotations

from virlo_exporter.storage.database import Database
from virlo_exporter.utils.files import safe_filename


def test_filename_sanitization() -> None:
    assert safe_filename('bad<>:"/\\|?* name.') == "bad_________ name"
    assert safe_filename("CON") == "_CON"
    assert safe_filename("   ") == "Untitled"


def test_stable_research_and_export_numbering(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    first = db.assign_runs(
        "a",
        [
            {"id": "new", "started_at": "2026-02-01"},
            {"id": "old", "started_at": "2026-01-01"},
        ],
    )
    assert first == {"old": 1, "new": 2}
    second = db.assign_runs(
        "a",
        [
            {"id": "older-discovered-late", "started_at": "2025-01-01"},
            {"id": "old", "started_at": "2026-01-01"},
        ],
    )
    assert second["old"] == 1
    assert second["older-discovered-late"] == 3
    cached = db.cached_runs()
    assert {row["id"]: row["local_number"] for row in cached} == {
        "old": 1,
        "new": 2,
        "older-discovered-late": 3,
    }
    _, export_one = db.begin_export("a", "old", 1, "p1", "2026-01-01")
    _, export_two = db.begin_export("a", "old", 1, "p2", "2026-01-02")
    assert (export_one, export_two) == (1, 2)
