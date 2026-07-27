from __future__ import annotations

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QGuiApplication, QImage

from simple_screenshot.app import AppController
from simple_screenshot.capture import CapturedDesktop


def test_session_right_click_returns_to_same_desktop_selection(qapplication):
    image = QImage(400, 260, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    desktop = CapturedDesktop(image, QRect(10, 20, 400, 260), 1.0)
    controller = object.__new__(AppController)
    controller.overlay = None
    controller.capture_sessions = []
    controller._restore_settings_dialog = lambda: None

    AppController._create_capture_session(controller, image, desktop, "copy")
    session = controller.capture_sessions[0]

    session.reselect_requested.emit()

    assert controller.capture_sessions == []
    assert controller.overlay is not None
    assert controller.overlay.desktop is desktop
    assert controller.overlay.state == "selecting"
    controller.overlay._resolved = True
    controller.overlay.close()


def test_session_copy_updates_clipboard_and_closes_window(qapplication):
    image = QImage(120, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("#2f7de1"))
    desktop = CapturedDesktop(image, QRect(10, 20, 120, 80), 1.0)
    controller = object.__new__(AppController)
    controller.app = qapplication
    controller.overlay = None
    controller.capture_sessions = []
    controller._last_image = QImage()

    AppController._create_capture_session(controller, image, desktop, "copy")
    session = controller.capture_sessions[0]
    session.completed.emit(QImage(image), "copy")
    qapplication.processEvents()

    assert controller.capture_sessions == []
    copied = QGuiApplication.clipboard().image()
    assert copied.size() == image.size()
