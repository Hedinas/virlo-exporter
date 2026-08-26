from __future__ import annotations

from pathlib import Path

from virlo_exporter.config import (
    AppSettings,
    SettingsStore,
    documents_export_root,
    legacy_export_root,
    migrate_legacy_exports,
)


def test_default_export_folder_is_under_documents_never_inside_app_dir() -> None:
    settings = AppSettings.defaults()
    expected = str(Path.home() / "Documents" / "Virlo Exporter" / "Exports")
    assert settings.export_folder == expected
    assert "dist" not in settings.export_folder.lower()


def test_persisted_legacy_default_is_migrated_on_load(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    legacy = AppSettings(export_folder=str(legacy_export_root()))
    store.save(legacy)

    loaded = store.load()

    assert loaded.export_folder == str(documents_export_root())


def test_custom_export_folder_is_left_alone_on_load(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    custom = AppSettings(export_folder=str(tmp_path / "my-custom-exports"))
    store.save(custom)

    loaded = store.load()

    assert loaded.export_folder == str(tmp_path / "my-custom-exports")


def test_migrate_legacy_exports_copies_without_deleting_originals(tmp_path, monkeypatch) -> None:
    legacy = tmp_path / "legacy_exports"
    legacy.mkdir()
    (legacy / "Research_001").mkdir()
    (legacy / "Research_001" / "VIRLO_AI_DATASET.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr("virlo_exporter.config.legacy_export_root", lambda: legacy)
    target = tmp_path / "new_exports"
    settings = AppSettings(export_folder=str(target))

    migrated = migrate_legacy_exports(settings)

    assert migrated == ["Research_001"]
    assert (legacy / "Research_001" / "VIRLO_AI_DATASET.json").exists()  # original untouched
    assert (target / "Research_001" / "VIRLO_AI_DATASET.json").exists()  # copied


def test_migrate_legacy_exports_does_not_overwrite_existing_target(tmp_path, monkeypatch) -> None:
    legacy = tmp_path / "legacy_exports"
    legacy.mkdir()
    (legacy / "Research_001").mkdir()
    (legacy / "Research_001" / "marker.txt").write_text("legacy", encoding="utf-8")

    monkeypatch.setattr("virlo_exporter.config.legacy_export_root", lambda: legacy)
    target = tmp_path / "new_exports"
    (target / "Research_001").mkdir(parents=True)
    (target / "Research_001" / "marker.txt").write_text("already migrated", encoding="utf-8")
    settings = AppSettings(export_folder=str(target))

    migrated = migrate_legacy_exports(settings)

    assert migrated == []
    assert (target / "Research_001" / "marker.txt").read_text(encoding="utf-8") == "already migrated"


def test_migrate_legacy_exports_is_a_noop_when_nothing_legacy_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("virlo_exporter.config.legacy_export_root", lambda: tmp_path / "does-not-exist")
    settings = AppSettings(export_folder=str(tmp_path / "new_exports"))

    assert migrate_legacy_exports(settings) == []
