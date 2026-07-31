from __future__ import annotations

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QImage

from simple_screenshot.app import AppController


def test_create_pin_window_accepts_capture_position(qapplication):
    controller = AppController.__new__(AppController)
    controller.pin_windows = []
    image = QImage(160, 100, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))

    controller._create_pin_window(image, QPoint(35, 45))

    assert len(controller.pin_windows) == 1
    pin = controller.pin_windows[0]
    assert pin.pos() == QPoint(35, 45)
    assert pin.size() == QSize(160, 100)
    assert pin.isVisible()
    pin.close()
    qapplication.processEvents()
    assert controller.pin_windows == []
