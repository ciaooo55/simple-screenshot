from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor, QImage

from simple_screenshot.output import save_png_atomic, unique_screenshot_path


def test_unique_name_uses_milliseconds_and_suffix(tmp_path):
    moment = datetime(2026, 7, 16, 12, 34, 56, 789123)
    first = unique_screenshot_path(tmp_path, moment)
    assert first.name == "Screenshot_20260716_123456_789.png"
    first.touch()

    second = unique_screenshot_path(tmp_path, moment)

    assert second.name == "Screenshot_20260716_123456_789_1.png"


def test_png_is_saved_and_temporary_file_is_removed(tmp_path):
    image = QImage(12, 8, QImage.Format.Format_ARGB32)
    image.fill(QColor("#34c759"))

    target = save_png_atomic(image, tmp_path / "nested")

    loaded = QImage(str(target))
    assert target.suffix == ".png"
    assert loaded.size() == image.size()
    assert list(target.parent.glob("*.tmp")) == []


def test_export_drag_copy_writes_png_and_cleanup_removes_stale(
    tmp_path, monkeypatch
):
    import os
    import time as time_module

    from PySide6.QtGui import QColor, QImage

    from simple_screenshot import output

    monkeypatch.setattr(
        output.tempfile, "gettempdir", lambda: str(tmp_path)
    )
    image = QImage(20, 20, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))

    target = output.export_drag_copy(image)
    assert target.exists()
    assert target.suffix == ".png"
    assert target.parent == tmp_path / output.DRAG_EXPORT_DIRNAME

    # 新文件保留,过期文件清掉。
    stale = target.parent / "old.png"
    stale.write_bytes(target.read_bytes())
    old = time_module.time() - output.DRAG_EXPORT_MAX_AGE_SECONDS - 10
    os.utime(stale, (old, old))

    output.cleanup_stale_drag_copies()
    assert not stale.exists()
    assert target.exists()
