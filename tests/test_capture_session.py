from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from simple_screenshot.capture_session import CaptureSessionWindow
from simple_screenshot.ocr import OcrOutcome, OcrSpan


class MouseEventStub:
    def __init__(self, point: QPointF, button=Qt.MouseButton.LeftButton) -> None:
        self._point = point
        self._button = button

    def position(self) -> QPointF:
        return self._point

    def button(self):  # type: ignore[no-untyped-def]
        return self._button

    def accept(self) -> None:
        pass


def make_session(action: str = "copy") -> CaptureSessionWindow:
    image = QImage(400, 260, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    return CaptureSessionWindow(image, action)


def test_session_is_regular_taskbar_window(qapplication):
    session = make_session()

    assert (
        session.windowFlags() & Qt.WindowType.WindowType_Mask
    ) == Qt.WindowType.Window
    assert not bool(session.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    assert bool(session.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint)
    assert bool(session.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint)
    assert session._zoom > 0
    assert session._image_rect().width() > 0
    assert session._image_rect().height() > 0
    target = session._image_rect()
    assert target.left() <= 13
    assert target.top() <= 13
    assert session._canvas.width() - target.right() <= 13
    assert session._canvas.height() - target.bottom() <= 13
    session.close()


def test_small_motion_double_click_completes_without_pen(qapplication):
    session = make_session("save")
    point = session._image_rect().center()
    completed: list[str] = []
    session.completed.connect(lambda image, action: completed.append(action))

    session.mousePressEvent(MouseEventStub(point))  # type: ignore[arg-type]
    session.mouseReleaseEvent(MouseEventStub(point))  # type: ignore[arg-type]
    session.mousePressEvent(MouseEventStub(point))  # type: ignore[arg-type]
    session.mouseDoubleClickEvent(MouseEventStub(point))  # type: ignore[arg-type]
    session.mouseReleaseEvent(MouseEventStub(QPointF(point.x() + 2, point.y())))  # type: ignore[arg-type]

    assert completed == ["save"]
    assert session.annotations == []
    session.close()


def test_drag_beyond_system_threshold_creates_pen_annotation(qapplication):
    session = make_session()
    start = session._image_rect().center()
    end = QPointF(start.x() + QApplication.startDragDistance() + 20, start.y() + 10)

    session.mousePressEvent(MouseEventStub(start))  # type: ignore[arg-type]
    session.mouseMoveEvent(MouseEventStub(end))  # type: ignore[arg-type]
    session.mouseReleaseEvent(MouseEventStub(end))  # type: ignore[arg-type]

    assert len(session.annotations) == 1
    session.close()


def test_dedicated_canvas_receives_real_drag_events(qapplication):
    session = make_session()
    canvas = session._canvas
    start = session._image_rect().center()
    end = QPointF(start.x() + QApplication.startDragDistance() + 20, start.y() + 10)

    qapplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            start,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    qapplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            end,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    qapplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            end,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )

    assert len(session.annotations) == 1
    session.close()


def test_pen_button_keeps_direct_drawing_enabled(qapplication):
    session = make_session()
    start = session._image_rect().center()
    end = QPointF(start.x() + QApplication.startDragDistance() + 20, start.y() + 10)

    session._pen_button.click()
    session.mousePressEvent(MouseEventStub(start))  # type: ignore[arg-type]
    session.mouseMoveEvent(MouseEventStub(end))  # type: ignore[arg-type]
    session.mouseReleaseEvent(MouseEventStub(end))  # type: ignore[arg-type]

    assert session._pen_button.isChecked()
    assert len(session.annotations) == 1
    session.close()


def test_right_click_undo_then_requests_reselect(qapplication):
    session = make_session()
    start = session._image_rect().center()
    end = QPointF(start.x() + QApplication.startDragDistance() + 20, start.y() + 10)
    reselects: list[bool] = []
    session.reselect_requested.connect(lambda: reselects.append(True))

    session.mousePressEvent(MouseEventStub(start))  # type: ignore[arg-type]
    session.mouseMoveEvent(MouseEventStub(end))  # type: ignore[arg-type]
    session.mouseReleaseEvent(MouseEventStub(end))  # type: ignore[arg-type]
    session.mousePressEvent(MouseEventStub(start, Qt.MouseButton.RightButton))  # type: ignore[arg-type]

    assert session.annotations == []
    assert reselects == []

    session.mousePressEvent(MouseEventStub(start, Qt.MouseButton.RightButton))  # type: ignore[arg-type]
    assert reselects == [True]
    session.close()


def test_escape_and_ctrl_z_follow_the_same_undo_hierarchy(qapplication):
    session = make_session()
    start = session._image_rect().center()
    end = QPointF(start.x() + QApplication.startDragDistance() + 20, start.y() + 10)
    reselects: list[bool] = []
    session.reselect_requested.connect(lambda: reselects.append(True))

    session.mousePressEvent(MouseEventStub(start))  # type: ignore[arg-type]
    session.mouseMoveEvent(MouseEventStub(end))  # type: ignore[arg-type]
    session.mouseReleaseEvent(MouseEventStub(end))  # type: ignore[arg-type]
    session.keyPressEvent(
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Z,
            Qt.KeyboardModifier.ControlModifier,
        )
    )
    assert session.annotations == []

    session.keyPressEvent(
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert reselects == [True]
    session.close()


def test_ocr_hides_pen_and_restores_it_on_exit(qapplication):
    session = make_session()
    received: list[QImage] = []
    session.ocr_requested.connect(received.append)

    session.request_ocr()
    assert len(received) == 1
    assert session._toolbar.isHidden()

    session.set_ocr_result(
        OcrOutcome("A", 1, (OcrSpan("A", 0, 0, 5, 5, 20, 20),))
    )
    assert session._ocr_outcome is not None
    assert session._toolbar.isHidden()

    session._exit_ocr_mode()
    assert not session._toolbar.isHidden()
    session.close()
