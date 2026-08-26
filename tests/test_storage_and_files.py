from __future__ import annotations

from virlo_exporter.storage.database import Database
from virlo_exporter.utils.files import delete_directory, directory_size, safe_filename


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


def test_deleted_export_number_is_never_reused(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    db.assign_runs("a", [{"id": "run-1", "started_at": "2026-01-01"}])
    export_id, number = db.begin_export("a", "run-1", 1, "p1", "2026-01-01")
    assert number == 1

    db.delete_export(export_id)

    assert db.export_history("a", "run-1") == []  # deleted export is hidden from history
    _, next_number = db.begin_export("a", "run-1", 1, "p2", "2026-01-02")
    assert next_number == 2  # not reissued as 1


def test_delete_export_removes_stage_history(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    db.assign_runs("a", [{"id": "run-1", "started_at": "2026-01-01"}])
    export_id, _ = db.begin_export("a", "run-1", 1, "p1", "2026-01-01")
    db.upsert_export_stage(
        export_id,
        {"sequence": 1, "stage": "videos", "label": "Fetching videos", "status": "complete"},
    )
    assert db.export_stages(export_id)

    db.delete_export(export_id)

    assert db.export_stages(export_id) == []


def test_directory_size(tmp_path) -> None:
    target = tmp_path / "export_dir"
    target.mkdir()
    (target / "a.json").write_text("x" * 10, encoding="utf-8")
    (target / "sub").mkdir()
    (target / "sub" / "b.json").write_text("y" * 5, encoding="utf-8")

    assert directory_size(target) == 15
    assert directory_size(tmp_path / "does-not-exist") == 0


def test_delete_directory_sends_to_recycle_bin_not_permanent(tmp_path, monkeypatch) -> None:
    # Must never call shutil.rmtree -- a deleted export should be recoverable
    # from the Windows Recycle Bin, not gone forever. Mocked so the test
    # suite never touches the real Recycle Bin.
    target = tmp_path / "export_dir"
    target.mkdir()
    (target / "a.json").write_text("x", encoding="utf-8")

    sent: list[str] = []
    monkeypatch.setattr("virlo_exporter.utils.files.send2trash", sent.append)

    delete_directory(target)

    assert sent == [str(target.resolve())]
    assert target.exists()  # the mock didn't actually move anything


def test_delete_directory_missing_path_is_a_noop(tmp_path, monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr("virlo_exporter.utils.files.send2trash", sent.append)

    delete_directory(tmp_path / "does-not-exist")

    assert sent == []
