from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainterPath

from simple_screenshot.annotations import PenAnnotation
from simple_screenshot.capture import CapturedDesktop, CaptureOverlay
from simple_screenshot.window_targets import WindowTarget


class MouseEventStub:
    def __init__(self, point: QPointF, button=Qt.MouseButton.LeftButton) -> None:
        self._point = point
        self._button = button
        self.accepted = False

    def position(self) -> QPointF:
        return self._point

    def button(self):  # type: ignore[no-untyped-def]
        return self._button

    def accept(self) -> None:
        self.accepted = True


def make_overlay(
    action: str = "copy",
    window_targets: list[WindowTarget] | None = None,
) -> CaptureOverlay:
    image = QImage(320, 200, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    desktop = CapturedDesktop(image, QRect(0, 0, 320, 200), 1.0)
    return CaptureOverlay(desktop, action, window_targets or [])


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


def test_double_click_finishes_with_default_action(qapplication):
    overlay = make_overlay("copy")
    overlay.selection = QRectF(10, 20, 80, 50)
    overlay.state = "editing"
    results: list[tuple[QImage, str]] = []
    overlay.completed.connect(lambda image, action: results.append((image, action)))
    event = MouseEventStub(QPointF(25, 35))

    overlay.mouseDoubleClickEvent(event)  # type: ignore[arg-type]
    qapplication.processEvents()

    assert event.accepted
    assert len(results) == 1
    assert results[0][1] == "copy"


def test_ctrl_s_can_override_copy_action(qapplication):
    overlay = make_overlay("copy")
    overlay.selection = QRectF(10, 20, 80, 50)
    overlay.state = "editing"
    results: list[str] = []
    overlay.completed.connect(lambda image, action: results.append(action))

    overlay.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_S,
            Qt.KeyboardModifier.ControlModifier,
        )
    )
    qapplication.processEvents()

    assert results == ["save"]


def test_clicking_shaded_area_keeps_previous_selection(qapplication):
    overlay = make_overlay()
    original = QRectF(10, 20, 80, 50)
    path = QPainterPath(QPointF(20, 30))
    path.lineTo(QPointF(30, 40))
    annotation = PenAnnotation(path, "#ff0000", 4.0)
    overlay.selection = QRectF(original)
    overlay.annotations = [annotation]
    overlay.state = "editing"

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(200, 150))
    )
    overlay.mouseReleaseEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(200, 150))
    )

    assert overlay.state == "editing"
    assert overlay.selection == original
    assert overlay.annotations == [annotation]


def test_dragging_shaded_area_replaces_selection_and_clears_annotations(
    qapplication,
):
    overlay = make_overlay()
    path = QPainterPath(QPointF(20, 30))
    path.lineTo(QPointF(30, 40))
    overlay.selection = QRectF(10, 20, 80, 50)
    overlay.annotations = [PenAnnotation(path, "#ff0000", 4.0)]
    overlay.state = "editing"

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(180, 100))
    )
    overlay.mouseMoveEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(300, 180))
    )
    overlay.mouseReleaseEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(300, 180))
    )

    assert overlay.state == "editing"
    assert overlay.selection == QRectF(180, 100, 120, 80)
    assert overlay.annotations == []


def test_escape_in_text_editor_only_discards_editor(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 250, 150)
    overlay.state = "editing"
    cancelled: list[bool] = []
    overlay.cancelled.connect(lambda: cancelled.append(True))
    overlay._begin_text(QPointF(30, 30))
    editor = overlay._text_editor
    assert editor is not None
    editor.setPlainText("draft")

    editor.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.NoModifier)
    )
    qapplication.processEvents()

    assert overlay._text_editor is None
    assert not overlay._resolved
    assert cancelled == []


def test_toolbar_moves_above_selection_near_screen_bottom(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(20, 150, 280, 45)
    overlay.state = "editing"

    overlay._position_toolbar()

    assert overlay.toolbar.y() < overlay.selection.top()


def test_hover_highlights_topmost_window_target(qapplication):
    back = WindowTarget(QRectF(20, 20, 260, 160), "Back")
    front = WindowTarget(QRectF(60, 40, 120, 90), "Front")
    overlay = make_overlay(window_targets=[front, back])

    overlay.mouseMoveEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(80, 70))
    )

    assert overlay._hovered_window == front
    assert overlay.selection.isEmpty()


def test_click_selects_hovered_window_target(qapplication):
    target = WindowTarget(QRectF(40, 30, 160, 100), "Window")
    overlay = make_overlay(window_targets=[target])

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(80, 60))
    )
    overlay.mouseReleaseEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(80, 60))
    )

    assert overlay.state == "editing"
    assert overlay.selection == target.rect


def test_drag_inside_window_target_uses_manual_selection(qapplication):
    target = WindowTarget(QRectF(20, 20, 260, 160), "Window")
    overlay = make_overlay(window_targets=[target])

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(60, 50))
    )
    overlay.mouseMoveEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(140, 110))
    )
    overlay.mouseReleaseEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(140, 110))
    )

    assert overlay.state == "editing"
    assert overlay.selection == QRectF(60, 50, 80, 60)


def test_clicking_another_window_replaces_selection(qapplication):
    target = WindowTarget(QRectF(180, 100, 120, 80), "Other")
    overlay = make_overlay(window_targets=[target])
    overlay.selection = QRectF(10, 20, 80, 50)
    overlay.state = "editing"

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(220, 130))
    )
    overlay.mouseReleaseEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(220, 130))
    )

    assert overlay.state == "editing"
    assert overlay.selection == target.rect


def test_select_tool_is_default(qapplication):
    overlay = make_overlay()

    assert overlay.select_button.isChecked()
    assert not overlay.pen_button.isChecked()
    assert not overlay.color_combo.isEnabled()


def test_dragging_selection_moves_it_with_annotations(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(20, 20, 100, 80)
    overlay.state = "editing"
    path = QPainterPath(QPointF(40, 40))
    path.lineTo(QPointF(50, 50))
    overlay.annotations = [PenAnnotation(path, "#ff0000", 4.0)]

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(70, 60))
    )
    overlay.mouseMoveEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(90, 75))
    )
    overlay.mouseReleaseEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(90, 75))
    )

    assert overlay.selection == QRectF(40, 35, 100, 80)
    moved = overlay.annotations[0]
    assert isinstance(moved, PenAnnotation)
    assert moved.path.elementAt(0).x == 60
    assert moved.path.elementAt(0).y == 55


def test_moving_selection_is_clamped_to_desktop(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(250, 150, 60, 40)
    overlay.state = "editing"

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(270, 170))
    )
    overlay.mouseMoveEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(400, 260))
    )
    overlay.mouseReleaseEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(400, 260))
    )

    assert overlay.selection == QRectF(260, 160, 60, 40)


def test_dragging_east_handle_resizes_selection(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(20, 20, 100, 80)
    overlay.state = "editing"

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(120, 60))
    )
    overlay.mouseMoveEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(150, 60))
    )
    overlay.mouseReleaseEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(150, 60))
    )

    assert overlay.selection == QRectF(20, 20, 130, 80)
