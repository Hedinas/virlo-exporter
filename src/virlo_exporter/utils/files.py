from __future__ import annotations

import re
from pathlib import Path

WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_filename(value: str, fallback: str = "Untitled", max_length: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)[:max_length].rstrip(" .")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def open_in_explorer(path: Path) -> None:
    import os

    os.startfile(str(path.resolve()))  # type: ignore[attr-defined]


def reveal_in_explorer(path: Path) -> None:
    """Open Windows Explorer with `path` selected, rather than launching it."""
    import subprocess

    subprocess.run(["explorer", f"/select,{path.resolve()}"], check=False)


def delete_directory(path: Path) -> None:
    """Recursively and permanently delete a directory. A no-op if it's
    already gone (e.g. the user deleted it manually, or it never existed)."""
    import shutil

    if path.exists():
        shutil.rmtree(path)


def directory_size(path: Path) -> int:
    """Total size in bytes of every file under `path`, or 0 if it's missing."""
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
