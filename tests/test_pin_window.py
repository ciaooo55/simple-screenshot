from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeyEvent

from simple_screenshot.pin_window import PinWindow


def make_image(width: int = 100, height: int = 60, ratio: float = 1.0) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("#34c759"))
    image.setDevicePixelRatio(ratio)
    return image


def test_pin_window_uses_logical_size_and_position(qapplication):
    pin = PinWindow(make_image(200, 120, 2.0), QSize(100, 60), QPoint(30, 40))

    assert pin.size() == QSize(100, 60)
    assert pin.pos() == QPoint(30, 40)
    pin.close()


def test_zoom_resizes_window_and_clamps(qapplication):
    pin = PinWindow(make_image(), QSize(100, 60), QPoint(0, 0))

    pin.set_zoom(2.0)
    assert pin.size() == QSize(200, 120)

    pin.set_zoom(100.0)
    assert pin.zoom == 5.0

    # 100×60 的小贴图受最小尺寸保护:短边不低于 48px,即缩放下限 0.8。
    pin.set_zoom(0.01)
    assert pin.zoom == 0.8

    pin.reset_view()
    assert pin.size() == QSize(100, 60)
    pin.close()


def test_escape_closes_and_emits_closed(qapplication):
    pin = PinWindow(make_image(), QSize(100, 60), QPoint(0, 0))
    closed: list[object] = []
    pin.closed.connect(lambda window: closed.append(window))

    pin.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.NoModifier)
    )
    qapplication.processEvents()

    assert closed == [pin]


def test_ctrl_c_copies_image_to_clipboard(qapplication):
    pin = PinWindow(make_image(), QSize(100, 60), QPoint(0, 0))

    pin.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_C,
            Qt.KeyboardModifier.ControlModifier,
        )
    )

    clipboard_image = QGuiApplication.clipboard().image()
    assert not clipboard_image.isNull()
    assert clipboard_image.size() == QSize(100, 60)
    pin.close()


def test_zoom_keeps_anchor_point_fixed(qapplication):
    from PySide6.QtCore import QPointF

    pin = PinWindow(make_image(), QSize(100, 60), QPoint(100, 100))

    pin.set_zoom(2.0, QPointF(50, 30))

    assert pin.size() == QSize(200, 120)
    assert pin.pos() == QPoint(50, 70)
    pin.close()


def test_arrow_keys_nudge_pin_position(qapplication):
    pin = PinWindow(make_image(), QSize(100, 60), QPoint(100, 100))

    pin.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.NoModifier)
    )
    pin.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Down,
            Qt.KeyboardModifier.ShiftModifier,
        )
    )

    assert pin.pos() == QPoint(101, 110)
    pin.close()


def test_plus_minus_keys_zoom(qapplication):
    pin = PinWindow(make_image(), QSize(100, 60), QPoint(0, 0))

    pin.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Plus, Qt.NoModifier)
    )
    assert pin.zoom > 1.0

    pin.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Minus, Qt.NoModifier)
    )
    assert abs(pin.zoom - 1.0) < 1e-6
    pin.close()


def test_snapped_position_sticks_to_screen_edges(qapplication):
    from PySide6.QtGui import QGuiApplication

    pin = PinWindow(make_image(), QSize(100, 60), QPoint(200, 200))
    area = QGuiApplication.primaryScreen().availableGeometry()

    near_corner = QPoint(area.left() + 8, area.top() + 5)
    snapped = pin._snapped_position(near_corner)

    assert snapped == QPoint(area.left(), area.top())

    middle = QPoint(area.center().x(), area.center().y())
    assert pin._snapped_position(middle) == middle
    pin.close()


def test_ctrl_s_requests_save(qapplication):
    pin = PinWindow(make_image(), QSize(100, 60), QPoint(0, 0))
    saved: list[QImage] = []
    pin.save_requested.connect(lambda image: saved.append(image))

    pin.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_S,
            Qt.KeyboardModifier.ControlModifier,
        )
    )

    assert len(saved) == 1
    assert saved[0].size() == QSize(100, 60)
    pin.close()


def test_large_pin_can_still_reach_global_min_zoom(qapplication):
    pin = PinWindow(make_image(600, 400), QSize(600, 400), QPoint(0, 0))

    pin.set_zoom(0.01)
    assert pin.zoom == 0.2
    pin.close()


def test_show_save_result_shows_hud_feedback(qapplication):
    pin = PinWindow(make_image(), QSize(100, 60), QPoint(0, 0))

    pin.show_save_result(True)
    assert pin._hud_text == "已保存"

    pin.show_save_result(False)
    assert "保存失败" in pin._hud_text
    pin.close()


def test_fit_to_allows_below_normal_min_and_stays_reachable(qapplication):
    # 800×8000 的长图:fit≈0.116,低于常规下限也要生效,且还原后还能回去。
    pin = PinWindow(make_image(800, 800), QSize(800, 8000), QPoint(0, 0))

    pin.fit_to(0.116)
    assert abs(pin.zoom - 0.116) < 1e-9

    pin.set_zoom(1.0)
    pin.set_zoom(0.01)
    assert abs(pin.zoom - 0.116) < 1e-9
    pin.close()


def test_ctrl_shift_s_requests_save_as(qapplication):
    pin = PinWindow(make_image(), QSize(100, 60), QPoint(0, 0))
    saved_as: list[QImage] = []
    pin.save_as_requested.connect(lambda image: saved_as.append(image))

    pin.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_S,
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier,
        )
    )

    assert len(saved_as) == 1
    pin.close()


def test_click_through_toggles_window_flag(qapplication):
    pin = PinWindow(make_image(), QSize(100, 60), QPoint(0, 0))

    pin.set_click_through(True)
    assert pin.click_through
    assert bool(
        pin.windowFlags() & Qt.WindowType.WindowTransparentForInput
    )

    pin.set_click_through(False)
    assert not pin.click_through
    assert not bool(
        pin.windowFlags() & Qt.WindowType.WindowTransparentForInput
    )
    pin.close()


def test_ctrl_click_without_move_does_not_start_drag(qapplication):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    pin = PinWindow(make_image(), QSize(100, 60), QPoint(0, 0))
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(30, 30),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
    )
    pin.mousePressEvent(press)
    assert pin._ctrl_drag_origin is not None

    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(30, 30),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
    )
    pin.mouseReleaseEvent(release)
    assert pin._ctrl_drag_origin is None
    pin.close()


def test_click_through_restores_user_opacity(qapplication):
    pin = PinWindow(make_image(), QSize(100, 60), QPoint(0, 0))
    pin.setWindowOpacity(0.4)

    pin.set_click_through(True)
    pin.set_click_through(False)

    assert abs(pin.windowOpacity() - 0.4) < 0.05
    pin.close()


def test_request_ocr_emits_image(qapplication):
    pin = PinWindow(make_image(), QSize(100, 60), QPoint(0, 0))
    received: list[QImage] = []
    pin.ocr_requested.connect(lambda image: received.append(image))

    pin.request_ocr()

    assert len(received) == 1
    assert received[0].size() == QSize(100, 60)
    pin.close()
