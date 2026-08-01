from __future__ import annotations

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from simple_screenshot.app import AppController
from simple_screenshot.config import default_settings


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


def _capture_controller(qapplication, tmp_path, hide_pins: bool):
    controller = AppController.__new__(AppController)
    controller.overlay = None
    controller._capture_pending = False
    controller.settings = default_settings(tmp_path).updated(
        hide_pins_on_capture=hide_pins
    )
    controller.settings_dialog = QWidget()
    controller._settings_was_visible = False
    pin = QWidget()
    pin.show()
    qapplication.processEvents()
    controller.pin_windows = [pin]
    controller._pins_hidden_for_capture = []
    calls: list[tuple[str, bool]] = []

    def begin(action: str, fullscreen: bool = False) -> None:
        calls.append((action, fullscreen))
        controller._capture_pending = False

    controller._begin_capture = begin
    return controller, pin, calls


def test_copy_capture_keeps_pins_visible_by_default(qapplication, tmp_path):
    controller, pin, calls = _capture_controller(qapplication, tmp_path, False)

    controller.request_capture("copy")

    assert pin.isVisible()
    assert controller._pins_hidden_for_capture == []
    QTest.qWait(500)
    assert calls == [("copy", False)]
    pin.close()


def test_capture_can_still_hide_pins_when_enabled(qapplication, tmp_path):
    controller, pin, calls = _capture_controller(qapplication, tmp_path, True)

    controller.request_capture("save")

    assert not pin.isVisible()
    assert controller._pins_hidden_for_capture == [pin]
    QTest.qWait(500)
    assert calls == [("save", False)]
    controller._restore_hidden_pins()
    assert pin.isVisible()
    pin.close()
