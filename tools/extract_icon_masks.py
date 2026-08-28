"""Extract clean monochrome masks from the approved Virlo icon references.

The source PNGs already carry transparency, but also contain low-opacity
generation noise around the approved white shapes.  This tool keeps only
substantial connected foreground components, fills tiny enclosed pinholes,
and writes square transparent masks without redrawing their geometry.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

SOURCE_FILES = {
    "gear": "01_settings.png",
    "folder": "02_folder.png",
    "copy": "03_copy.png",
    "report": "05_error_report.png",
    "pencil": "06_rename.png",
    "trash": "07_delete.png",
    "workflow": "file_000000002e2481f68f917699dfec479c.png",
}


def _components(mask: bytearray, width: int, height: int) -> list[list[int]]:
    seen = bytearray(width * height)
    groups: list[list[int]] = []
    for start, value in enumerate(mask):
        if not value or seen[start]:
            continue
        group: list[int] = []
        queue = [start]
        seen[start] = 1
        while queue:
            current = queue.pop()
            group.append(current)
            y, x = divmod(current, width)
            for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if not (0 <= next_x < width and 0 <= next_y < height):
                    continue
                index = next_y * width + next_x
                if mask[index] and not seen[index]:
                    seen[index] = 1
                    queue.append(index)
        groups.append(group)
    return groups


def _fill_small_holes(mask: bytearray, width: int, height: int, max_area: int) -> None:
    inverse = bytearray(0 if value else 1 for value in mask)
    for group in _components(inverse, width, height):
        touches_edge = any(
            index < width
            or index >= width * (height - 1)
            or index % width in (0, width - 1)
            for index in group
        )
        if not touches_edge and len(group) <= max_area:
            for index in group:
                mask[index] = 1


def extract_mask(source: Path, output: Path, output_size: int = 256) -> None:
    image = QImage(str(source)).convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull():
        raise ValueError(f"Unable to load {source}")

    width, height = image.width(), image.height()
    pixels = bytes(image.bits())
    foreground = bytearray(width * height)
    for index in range(width * height):
        offset = index * 4
        strength = pixels[offset + 3] * max(pixels[offset : offset + 3]) // 255
        foreground[index] = strength >= 160

    minimum_component = max(64, int(width * height * 0.001))
    cleaned = bytearray(width * height)
    kept = [group for group in _components(foreground, width, height) if len(group) >= minimum_component]
    if not kept:
        raise ValueError(f"No substantial foreground found in {source}")
    for group in kept:
        for index in group:
            cleaned[index] = 1

    _fill_small_holes(cleaned, width, height, max(64, int(width * height * 0.0015)))

    points = [index for index, value in enumerate(cleaned) if value]
    xs = [index % width for index in points]
    ys = [index // width for index in points]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    content_size = max(right - left + 1, bottom - top + 1)
    side = min(max(width, height), int(content_size * 1.16))
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    crop_left = max(0, min(width - side, round(center_x - side / 2)))
    crop_top = max(0, min(height - side, round(center_y - side / 2)))

    mask = QImage(width, height, QImage.Format.Format_RGBA8888)
    mask.fill(Qt.GlobalColor.transparent)
    white = QColor(255, 255, 255, 255)
    for index, value in enumerate(cleaned):
        if value:
            y, x = divmod(index, width)
            mask.setPixelColor(x, y, white)

    cropped = mask.copy(crop_left, crop_top, side, side)
    result = cropped.scaled(
        output_size,
        output_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    if not result.save(str(output), "PNG"):
        raise OSError(f"Unable to write {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    for name, filename in SOURCE_FILES.items():
        extract_mask(args.source_dir / filename, args.output_dir / f"{name}.png")


if __name__ == "__main__":
    main()
