from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent

from simple_screenshot.capture import CapturedDesktop, CaptureOverlay


def make_overlay(action: str = "copy") -> CaptureOverlay:
    image = QImage(320, 200, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    desktop = CapturedDesktop(image, QRect(0, 0, 320, 200), 1.0)
    return CaptureOverlay(desktop, action)


def test_escape_cancels_without_completing(qapplication):
    overlay = make_overlay()
    cancelled: list[bool] = []
    completed: list[object] = []
    overlay.cancelled.connect(lambda: cancelled.append(True))
    overlay.completed.connect(lambda image, action: completed.append((image, action)))

    overlay.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.NoModifier)
    )
    qapplication.processEvents()

    assert cancelled == [True]
    assert completed == []


def test_finish_emits_selected_image_and_action(qapplication):
    overlay = make_overlay("save")
    overlay.selection = QRectF(10, 20, 80, 50)
    overlay.state = "editing"
    results: list[tuple[QImage, str]] = []
    overlay.completed.connect(lambda image, action: results.append((image, action)))

    overlay.finish()
    qapplication.processEvents()

    assert len(results) == 1
    assert results[0][0].size().width() == 80
    assert results[0][0].size().height() == 50
    assert results[0][1] == "save"
