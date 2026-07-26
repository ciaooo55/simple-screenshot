from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QImage

# 拖出文件用的临时导出目录;超过一天的旧文件在启动时清理。
DRAG_EXPORT_DIRNAME = "SimpleScreenshot"
DRAG_EXPORT_MAX_AGE_SECONDS = 24 * 3600


def drag_export_dir() -> Path:
    return Path(tempfile.gettempdir()) / DRAG_EXPORT_DIRNAME


def export_drag_copy(image: QImage) -> Path:
    """把图片导出成临时 PNG,供拖拽(QDrag setUrls)当文件使用。"""
    directory = drag_export_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = unique_screenshot_path(directory)
    if not image.save(str(target), "PNG"):
        raise OSError("图片编码失败")
    return target


def cleanup_stale_drag_copies(
    max_age_seconds: float = DRAG_EXPORT_MAX_AGE_SECONDS,
) -> None:
    directory = drag_export_dir()
    if not directory.is_dir():
        return
    cutoff = time.time() - max_age_seconds
    for entry in directory.glob("*.png"):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
        except OSError:
            continue


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
