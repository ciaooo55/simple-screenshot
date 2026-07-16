from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QImage


def unique_screenshot_path(
    directory: Path,
    moment: datetime | None = None,
) -> Path:
    now = moment or datetime.now()
    stem = now.strftime("Screenshot_%Y%m%d_%H%M%S_%f")[:-3]
    candidate = directory / f"{stem}.png"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}.png"
        counter += 1
    return candidate


def save_png_atomic(image: QImage, directory: Path) -> Path:
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = unique_screenshot_path(directory)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        if not image.save(str(temporary), "PNG"):
            raise OSError("图片编码失败")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target
