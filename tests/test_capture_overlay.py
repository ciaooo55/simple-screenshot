from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainterPath

from simple_screenshot.annotations import (
    ArrowAnnotation,
    MosaicAnnotation,
    NumberAnnotation,
    PenAnnotation,
    ShapeAnnotation,
    TextAnnotation,
)
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


def press_key(overlay, key, modifiers=Qt.KeyboardModifier.NoModifier):
    overlay.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers))


def drag(overlay, start: QPointF, end: QPointF) -> None:
    overlay.mousePressEvent(MouseEventStub(start))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(end))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(end))  # type: ignore[arg-type]


def test_escape_cancels_without_completing(qapplication):
    overlay = make_overlay()
    cancelled: list[bool] = []
    completed: list[object] = []
    overlay.cancelled.connect(lambda: cancelled.append(True))
    overlay.completed.connect(
        lambda image, action, pos: completed.append((image, action, pos))
    )

    press_key(overlay, Qt.Key.Key_Escape)
    qapplication.processEvents()

    assert cancelled == [True]
    assert completed == []


def test_finish_emits_selected_image_action_and_position(qapplication):
    overlay = make_overlay("save")
    overlay.selection = QRectF(10, 20, 80, 50)
    overlay.state = "editing"
    results: list[tuple[QImage, str, object]] = []
    overlay.completed.connect(
        lambda image, action, pos: results.append((image, action, pos))
    )

    overlay.finish()
    qapplication.processEvents()

    assert len(results) == 1
    assert results[0][0].size().width() == 80
    assert results[0][0].size().height() == 50
    assert results[0][1] == "save"
    assert results[0][2].x() == 10
    assert results[0][2].y() == 20


def test_double_click_finishes_with_default_action(qapplication):
    overlay = make_overlay("copy")
    overlay.selection = QRectF(10, 20, 80, 50)
    overlay.state = "editing"
    results: list[str] = []
    overlay.completed.connect(lambda image, action, pos: results.append(action))
    event = MouseEventStub(QPointF(25, 35))

    overlay.mouseDoubleClickEvent(event)  # type: ignore[arg-type]
    qapplication.processEvents()

    assert event.accepted
    assert results == ["copy"]


def test_ctrl_s_can_override_copy_action(qapplication):
    overlay = make_overlay("copy")
    overlay.selection = QRectF(10, 20, 80, 50)
    overlay.state = "editing"
    results: list[str] = []
    overlay.completed.connect(lambda image, action, pos: results.append(action))

    press_key(overlay, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    qapplication.processEvents()

    assert results == ["save"]


def test_ctrl_d_finishes_with_pin_action(qapplication):
    overlay = make_overlay("copy")
    overlay.selection = QRectF(10, 20, 80, 50)
    overlay.state = "editing"
    results: list[str] = []
    overlay.completed.connect(lambda image, action, pos: results.append(action))

    press_key(overlay, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    qapplication.processEvents()

    assert results == ["pin"]


def test_ctrl_a_selects_full_desktop(qapplication):
    overlay = make_overlay()

    press_key(overlay, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)

    assert overlay.state == "editing"
    assert overlay.selection == QRectF(0, 0, 320, 200)


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

    drag(overlay, QPointF(180, 100), QPointF(300, 180))

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

    drag(overlay, QPointF(60, 50), QPointF(140, 110))

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

    drag(overlay, QPointF(70, 60), QPointF(90, 75))

    assert overlay.selection == QRectF(40, 35, 100, 80)
    moved = overlay.annotations[0]
    assert isinstance(moved, PenAnnotation)
    assert moved.path.elementAt(0).x == 60
    assert moved.path.elementAt(0).y == 55


def test_moving_selection_is_clamped_to_desktop(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(250, 150, 60, 40)
    overlay.state = "editing"

    drag(overlay, QPointF(270, 170), QPointF(400, 260))

    assert overlay.selection == QRectF(260, 160, 60, 40)


def test_dragging_east_handle_resizes_selection(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(20, 20, 100, 80)
    overlay.state = "editing"

    drag(overlay, QPointF(120, 60), QPointF(150, 60))

    assert overlay.selection == QRectF(20, 20, 130, 80)


def test_arrow_keys_nudge_selection_and_annotations(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(20, 20, 100, 80)
    overlay.state = "editing"
    path = QPainterPath(QPointF(40, 40))
    path.lineTo(QPointF(50, 50))
    overlay.annotations = [PenAnnotation(path, "#ff0000", 4.0)]

    press_key(overlay, Qt.Key.Key_Right)
    press_key(overlay, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)

    assert overlay.selection == QRectF(21, 30, 100, 80)
    moved = overlay.annotations[0]
    assert isinstance(moved, PenAnnotation)
    assert moved.path.elementAt(0).x == 41
    assert moved.path.elementAt(0).y == 50


def test_rect_tool_creates_shape_annotation(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("rect")

    drag(overlay, QPointF(40, 40), QPointF(120, 100))

    assert len(overlay.annotations) == 1
    shape = overlay.annotations[0]
    assert isinstance(shape, ShapeAnnotation)
    assert shape.shape == "rect"
    assert shape.rect == QRectF(40, 40, 80, 60)


def test_ellipse_tool_creates_ellipse_annotation(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("ellipse")

    drag(overlay, QPointF(50, 50), QPointF(90, 80))

    assert len(overlay.annotations) == 1
    shape = overlay.annotations[0]
    assert isinstance(shape, ShapeAnnotation)
    assert shape.shape == "ellipse"


def test_arrow_tool_creates_arrow_annotation(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("arrow")

    drag(overlay, QPointF(40, 40), QPointF(140, 90))

    assert len(overlay.annotations) == 1
    arrow = overlay.annotations[0]
    assert isinstance(arrow, ArrowAnnotation)
    assert arrow.start == QPointF(40, 40)
    assert arrow.end == QPointF(140, 90)


def test_mosaic_tool_creates_mosaic_annotation(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("mosaic")

    drag(overlay, QPointF(40, 40), QPointF(100, 90))

    assert len(overlay.annotations) == 1
    assert isinstance(overlay.annotations[0], MosaicAnnotation)


def test_tiny_shape_drag_is_ignored(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("rect")

    drag(overlay, QPointF(40, 40), QPointF(41, 41))

    assert overlay.annotations == []


def test_number_tool_places_incrementing_markers(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("number")

    overlay.mousePressEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    overlay.mousePressEvent(MouseEventStub(QPointF(90, 70)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(90, 70)))  # type: ignore[arg-type]

    numbers = [
        command.number
        for command in overlay.annotations
        if isinstance(command, NumberAnnotation)
    ]
    assert numbers == [1, 2]

    overlay.undo()
    overlay.mousePressEvent(MouseEventStub(QPointF(120, 90)))  # type: ignore[arg-type]
    numbers = [
        command.number
        for command in overlay.annotations
        if isinstance(command, NumberAnnotation)
    ]
    assert numbers == [1, 2]


def test_undo_redo_round_trip(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("rect")

    drag(overlay, QPointF(40, 40), QPointF(120, 100))
    assert len(overlay.annotations) == 1

    overlay.undo()
    assert overlay.annotations == []

    overlay.redo()
    assert len(overlay.annotations) == 1
    assert isinstance(overlay.annotations[0], ShapeAnnotation)

    press_key(overlay, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert overlay.annotations == []
    press_key(overlay, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert len(overlay.annotations) == 1


def test_new_annotation_clears_redo_stack(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("rect")

    drag(overlay, QPointF(40, 40), QPointF(120, 100))
    overlay.undo()
    drag(overlay, QPointF(60, 60), QPointF(140, 120))

    overlay.redo()

    assert len(overlay.annotations) == 1
    assert overlay.annotations[0].rect == QRectF(60, 60, 80, 60)


def test_clear_annotations_is_undoable(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("rect")
    drag(overlay, QPointF(40, 40), QPointF(120, 100))

    overlay.clear_annotations()
    assert overlay.annotations == []

    overlay.undo()
    assert len(overlay.annotations) == 1


def test_tool_shortcut_keys_switch_tools(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"

    press_key(overlay, Qt.Key.Key_M)
    assert overlay.mosaic_button.isChecked()

    press_key(overlay, Qt.Key.Key_A)
    assert overlay.arrow_button.isChecked()

    press_key(overlay, Qt.Key.Key_V)
    assert overlay.select_button.isChecked()


def test_click_on_toolbar_gap_does_not_disturb_selection(qapplication):
    overlay = make_overlay(
        window_targets=[WindowTarget(QRectF(0, 0, 320, 200), "Desktop")]
    )
    overlay.show()
    overlay.selection = QRectF(10, 10, 200, 100)
    overlay._accept_selection()
    annotation = PenAnnotation(QPainterPath(QPointF(20, 20)), "#ff0000", 4.0)
    overlay.annotations = [annotation]
    assert overlay.toolbar.isVisible()
    gap = QPointF(
        overlay.toolbar.geometry().center().x(),
        overlay.toolbar.geometry().top() + 2,
    )

    overlay.mousePressEvent(MouseEventStub(gap))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(gap))  # type: ignore[arg-type]

    assert overlay.state == "editing"
    assert overlay.selection == QRectF(10, 10, 200, 100)
    assert overlay.annotations == [annotation]
    overlay.cancel()


def test_right_click_steps_back_before_cancelling(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 200, 100)
    overlay.state = "editing"
    overlay.annotations = [
        PenAnnotation(QPainterPath(QPointF(20, 20)), "#ff0000", 4.0)
    ]
    cancelled: list[bool] = []
    overlay.cancelled.connect(lambda: cancelled.append(True))

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(50, 50), Qt.MouseButton.RightButton)
    )
    assert overlay.state == "selecting"
    assert overlay.selection.isEmpty()
    assert overlay.annotations == []
    assert cancelled == []

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(50, 50), Qt.MouseButton.RightButton)
    )
    qapplication.processEvents()
    assert cancelled == [True]


def test_selection_accept_switches_to_pen_for_direct_drawing(qapplication):
    overlay = make_overlay()

    drag(overlay, QPointF(20, 20), QPointF(200, 140))

    assert overlay.state == "editing"
    assert overlay._current_tool() == "pen"

    drag(overlay, QPointF(40, 40), QPointF(120, 90))
    assert any(
        isinstance(command, PenAnnotation) for command in overlay.annotations
    )
    overlay.cancel()


def test_reselection_keeps_explicit_tool_choice(qapplication):
    overlay = make_overlay()
    drag(overlay, QPointF(20, 20), QPointF(200, 140))
    overlay.set_tool("mosaic")

    # 在阴影区拖出新选区:回到编辑态后保持用户选的马赛克,不重置回画笔。
    drag(overlay, QPointF(250, 30), QPointF(310, 120))

    assert overlay.state == "editing"
    assert overlay._current_tool() == "mosaic"
    overlay.cancel()


def test_right_click_during_shape_drag_discards_only_that_stroke(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 200, 100)
    overlay.state = "editing"
    existing = PenAnnotation(QPainterPath(QPointF(20, 20)), "#ff0000", 4.0)
    overlay.annotations = [existing]
    overlay.set_tool("rect")

    overlay.mousePressEvent(MouseEventStub(QPointF(30, 30)))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(QPointF(80, 70)))  # type: ignore[arg-type]
    assert overlay._shape_origin is not None

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(80, 70), Qt.MouseButton.RightButton)
    )

    # 右键只丢弃拖到一半的矩形,已有标注和编辑态都保留。
    assert overlay.state == "editing"
    assert overlay.annotations == [existing]
    assert overlay._shape_origin is None
    assert overlay._active_shape is None

    overlay.mouseReleaseEvent(MouseEventStub(QPointF(80, 70)))  # type: ignore[arg-type]
    assert overlay.annotations == [existing]
    overlay.cancel()


def test_right_click_during_selection_move_restores_original(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 200, 100)
    overlay.state = "editing"
    existing = PenAnnotation(QPainterPath(QPointF(20, 20)), "#ff0000", 4.0)
    overlay.annotations = [existing]
    overlay.set_tool("select")

    overlay.mousePressEvent(MouseEventStub(QPointF(60, 60)))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(QPointF(100, 90)))  # type: ignore[arg-type]
    assert overlay._selection_transform == "move"
    assert overlay.selection != QRectF(10, 10, 200, 100)

    overlay.mousePressEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(100, 90), Qt.MouseButton.RightButton)
    )

    assert overlay.state == "editing"
    assert overlay.selection == QRectF(10, 10, 200, 100)
    assert overlay.annotations == [existing]
    assert overlay._selection_transform is None

    overlay.mouseReleaseEvent(MouseEventStub(QPointF(100, 90)))  # type: ignore[arg-type]
    assert overlay.selection == QRectF(10, 10, 200, 100)
    overlay.cancel()


def test_inline_text_commit_preserves_leading_blank_lines(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.start()
    qapplication.processEvents()
    overlay._begin_text(QPointF(30, 30))
    editor = overlay._text_editor
    assert editor is not None

    editor.setPlainText("\n\nhi  ")
    overlay._commit_inline_text(editor)

    texts = [
        command.text
        for command in overlay.annotations
        if isinstance(command, TextAnnotation)
    ]
    # 行首空行参与排版要保留;行尾空白不影响渲染,裁掉以拦下纯空白输入。
    assert texts == ["\n\nhi"]
    overlay.cancel()


def test_double_click_with_number_tool_places_marker_instead_of_finishing(
    qapplication,
):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("number")
    results: list[str] = []
    overlay.completed.connect(lambda image, action, pos: results.append(action))

    overlay.mousePressEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    overlay.mouseDoubleClickEvent(  # type: ignore[arg-type]
        MouseEventStub(QPointF(52, 50))
    )
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(52, 50)))  # type: ignore[arg-type]
    qapplication.processEvents()

    numbers = [
        command.number
        for command in overlay.annotations
        if isinstance(command, NumberAnnotation)
    ]
    assert numbers == [1, 2]
    assert results == []


def test_ctrl_arrow_keys_resize_selection(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(20, 20, 100, 80)
    overlay.state = "editing"

    press_key(overlay, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    press_key(
        overlay,
        Qt.Key.Key_Down,
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.ShiftModifier,
    )
    press_key(overlay, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)

    assert overlay.selection == QRectF(20, 20, 101, 89)


def test_r_key_restores_last_finished_selection(qapplication):
    CaptureOverlay._last_finished_selection = QRectF(30, 40, 120, 60)
    try:
        overlay = make_overlay()
        press_key(overlay, Qt.Key.Key_R)

        assert overlay.state == "editing"
        assert overlay.selection == QRectF(30, 40, 120, 60)
    finally:
        CaptureOverlay._last_finished_selection = None


def test_finish_remembers_selection_and_toolbar_style(qapplication):
    CaptureOverlay._last_finished_selection = None
    CaptureOverlay._remembered_style = {}
    try:
        overlay = make_overlay()
        overlay.selection = QRectF(10, 20, 80, 50)
        overlay.state = "editing"
        overlay.color_combo.setCurrentIndex(4)
        overlay.width_combo.setCurrentIndex(0)
        overlay.finish()
        qapplication.processEvents()

        assert CaptureOverlay._last_finished_selection == QRectF(10, 20, 80, 50)

        second = make_overlay()
        assert second.color_combo.currentIndex() == 4
        assert second.width_combo.currentIndex() == 0
        second.cancel()
    finally:
        CaptureOverlay._last_finished_selection = None
        CaptureOverlay._remembered_style = {}


def test_shift_constraints_produce_square_and_snapped_angle(qapplication):
    origin = QPointF(10, 10)

    square_end = CaptureOverlay._constrain_square(origin, QPointF(60, 30))
    assert square_end == QPointF(60, 60)

    square_end = CaptureOverlay._constrain_square(origin, QPointF(-40, 20))
    assert square_end == QPointF(-40, 60)

    snapped = CaptureOverlay._snap_angle(origin, QPointF(100, 8))
    assert snapped.y() == 10  # 吸附到水平线
    assert snapped.x() > 90


def test_size_label_reports_physical_pixels(qapplication):
    image = QImage(640, 400, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    desktop = CapturedDesktop(image, QRect(0, 0, 320, 200), 2.0)
    overlay = CaptureOverlay(desktop, "copy", [])

    width, height = overlay._physical_rect_size(QRectF(10, 10, 100, 50))

    assert width == 200
    assert height == 100


def test_inline_text_editor_receives_keys_despite_keyboard_grab(qapplication):
    # 真实按键经 QWidgetWindow 投递给 keyboardGrabber,而不是焦点控件;
    # 用 QWindow 级投递还原这条路径,确保打开文字输入框时抓取被释放。
    from PySide6.QtTest import QTest

    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 300, 180)
    overlay.state = "editing"
    overlay.start()
    qapplication.processEvents()
    overlay._begin_text(QPointF(30, 30))
    editor = overlay._text_editor
    assert editor is not None
    window = overlay.windowHandle()

    QTest.keyClick(window, Qt.Key.Key_H)
    QTest.keyClick(window, Qt.Key.Key_I)
    qapplication.processEvents()
    assert editor.toPlainText() == "hi"

    QTest.keyClick(
        window, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier
    )
    qapplication.processEvents()
    assert overlay._text_editor is None
    assert [ann.text for ann in overlay.annotations] == ["hi"]

    QTest.keyClick(window, Qt.Key.Key_M)
    assert overlay.mosaic_button.isChecked()
    overlay.cancel()


def test_color_at_pointer_reads_desktop_pixel(qapplication):
    overlay = make_overlay()
    overlay._pointer_pos = QPointF(5, 5)

    color = overlay._color_at_pointer()

    assert color is not None
    assert color.name() == "#ffffff"


def test_pen_stroke_is_smoothed_with_curves(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(0, 0, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("pen")

    overlay.mousePressEvent(MouseEventStub(QPointF(40, 40)))  # type: ignore[arg-type]
    for x in (70, 110, 150):
        overlay.mouseMoveEvent(MouseEventStub(QPointF(x, 60)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(170, 70)))  # type: ignore[arg-type]

    assert len(overlay.annotations) == 1
    path = overlay.annotations[0].path
    types = {path.elementAt(i).type for i in range(path.elementCount())}
    assert QPainterPath.ElementType.CurveToElement in types
    overlay.cancel()


def test_pen_click_without_drag_leaves_no_annotation(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(0, 0, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("pen")

    overlay.mousePressEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]

    assert overlay.annotations == []
    overlay.cancel()


def test_wheel_steps_pen_width_with_notice(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(0, 0, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("pen")
    overlay.width_combo.setCurrentIndex(0)

    assert overlay._step_tool_style(1) is True
    assert overlay.width_combo.currentIndex() == 1
    assert "粗细" in overlay._style_notice

    overlay._step_tool_style(-1)
    assert overlay.width_combo.currentIndex() == 0
    overlay.cancel()


def test_wheel_steps_font_size_for_text_tool(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(0, 0, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("text")
    overlay.font_combo.setCurrentIndex(0)

    assert overlay._step_tool_style(1) is True
    assert overlay.font_combo.currentIndex() == 1
    assert "字号" in overlay._style_notice
    overlay.cancel()


def test_wheel_is_ignored_for_number_tool(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(0, 0, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("number")

    assert overlay._step_tool_style(1) is False
    overlay.cancel()


def test_help_panel_toggles_and_esc_only_closes_it(qapplication):
    overlay = make_overlay()

    press_key(overlay, Qt.Key.Key_F1)
    assert overlay._help_visible

    press_key(overlay, Qt.Key.Key_Escape)
    assert not overlay._help_visible
    assert not overlay._resolved

    press_key(overlay, Qt.Key.Key_H)
    assert overlay._help_visible
    press_key(overlay, Qt.Key.Key_F1)
    assert not overlay._help_visible
    overlay.cancel()


def test_reselect_keeps_annotations_recoverable_via_undo(qapplication):
    overlay = make_overlay()
    drag(overlay, QPointF(20, 20), QPointF(160, 120))
    assert overlay.state == "editing"
    assert overlay._current_tool() == "pen"

    drag(overlay, QPointF(40, 40), QPointF(90, 80))
    assert len(overlay.annotations) == 1

    # 误点/拖到选区外触发重选:标注被清空,但 Ctrl+Z 能找回。
    drag(overlay, QPointF(200, 30), QPointF(280, 150))
    assert overlay.state == "editing"
    assert overlay.annotations == []

    overlay.undo()
    assert len(overlay.annotations) == 1
    overlay.cancel()


def test_click_closing_help_swallows_following_double_click(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 200, 100)
    overlay.state = "editing"
    overlay.set_tool("select")
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    press_key(overlay, Qt.Key.Key_F1)
    assert overlay._help_visible

    # 双击关面板:第一击收面板,第二击(dblclick 事件)必须被吞掉。
    overlay.mousePressEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    overlay.mouseDoubleClickEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    qapplication.processEvents()

    assert not overlay._help_visible
    assert completed == []
    assert not overlay._resolved

    # 面板关闭后的真实双击仍然照常完成。
    overlay.mousePressEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    overlay.mouseDoubleClickEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    qapplication.processEvents()
    assert completed == ["copy"]


def test_enter_while_help_open_only_closes_help(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 200, 100)
    overlay.state = "editing"
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    press_key(overlay, Qt.Key.Key_F1)
    press_key(overlay, Qt.Key.Key_Return)
    qapplication.processEvents()

    assert not overlay._help_visible
    assert completed == []
    assert not overlay._resolved
    overlay.cancel()


def test_undo_redo_blocked_while_reselecting(qapplication):
    overlay = make_overlay()
    drag(overlay, QPointF(20, 20), QPointF(160, 120))
    drag(overlay, QPointF(40, 40), QPointF(90, 80))
    assert len(overlay.annotations) == 1

    # 进入重选拖拽(按下但未松手),Ctrl+Z 应被吞掉。
    overlay.mousePressEvent(MouseEventStub(QPointF(200, 30)))  # type: ignore[arg-type]
    assert overlay.state == "reselecting"
    press_key(
        overlay, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier
    )
    assert len(overlay.annotations) == 1
    assert overlay._history != []
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(200, 30)))  # type: ignore[arg-type]
    overlay.cancel()


def test_highlight_tool_draws_translucent_wide_stroke(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(0, 0, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("highlight")
    overlay.width_combo.setCurrentIndex(1)  # 4px

    overlay.mousePressEvent(MouseEventStub(QPointF(40, 40)))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(QPointF(120, 60)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(150, 70)))  # type: ignore[arg-type]

    assert len(overlay.annotations) == 1
    stroke = overlay.annotations[0]
    assert isinstance(stroke, PenAnnotation)
    # 半透明 ARGB 颜色(#AARRGGBB)+ 3 倍宽度。
    assert len(stroke.color) == 9
    assert stroke.color.lower().startswith("#66")
    assert stroke.width == 12.0
    overlay.cancel()


def test_ctrl_shift_s_finishes_with_save_as_action(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 200, 100)
    overlay.state = "editing"
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    press_key(
        overlay,
        Qt.Key.Key_S,
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.ShiftModifier,
    )
    qapplication.processEvents()

    assert completed == ["save_as"]


def test_escape_mid_stroke_only_cancels_gesture(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(0, 0, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("pen")

    overlay.mousePressEvent(MouseEventStub(QPointF(40, 40)))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(QPointF(80, 60)))  # type: ignore[arg-type]
    press_key(overlay, Qt.Key.Key_Escape)

    assert overlay.active_path is None
    assert overlay.state == "editing"
    assert not overlay._resolved

    press_key(overlay, Qt.Key.Key_Escape)
    assert overlay._resolved


def test_style_change_applies_live_to_open_text_editor(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(0, 0, 300, 180)
    overlay.state = "editing"
    overlay.set_tool("text")
    overlay.mousePressEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    editor = overlay._text_editor
    assert editor is not None

    overlay.font_combo.setCurrentIndex(2)  # 32px
    assert editor.font().pixelSize() == 32
    assert editor is overlay._text_editor  # 没被提交关闭

    overlay._discard_inline_text()
    overlay.cancel()


def test_toolbar_children_never_take_focus(qapplication):
    overlay = make_overlay()
    for name, button in overlay._tool_buttons.items():
        assert button.focusPolicy() == Qt.FocusPolicy.NoFocus, name
    assert overlay.width_combo.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert overlay.font_combo.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert overlay.color_combo.focusPolicy() == Qt.FocusPolicy.NoFocus
    overlay.cancel()


def test_w_key_finishes_with_ocr_action(qapplication):
    overlay = make_overlay()
    drag(overlay, QPointF(20, 20), QPointF(160, 120))
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    press_key(overlay, Qt.Key.Key_W)
    qapplication.processEvents()

    assert completed == ["ocr"]


def test_toolbar_has_ocr_button_wired_to_finish(qapplication):
    overlay = make_overlay()
    overlay.selection = QRectF(10, 10, 200, 100)
    overlay.state = "editing"
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    overlay.ocr_button.click()
    qapplication.processEvents()

    assert completed == ["ocr"] or not overlay.ocr_button.isEnabled()
    overlay.cancel()


def test_w_key_is_gated_when_ocr_unavailable(qapplication):
    overlay = make_overlay()
    drag(overlay, QPointF(20, 20), QPointF(160, 120))
    overlay.ocr_button.setEnabled(False)
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    press_key(overlay, Qt.Key.Key_W)
    qapplication.processEvents()

    # OCR 不可用时按 W 不能销毁截图会话。
    assert completed == []
    assert not overlay._resolved
    assert overlay.state == "editing"
    overlay.cancel()


def test_double_click_with_pen_and_no_stroke_finishes(qapplication):
    overlay = make_overlay("copy")
    drag(overlay, QPointF(20, 20), QPointF(200, 150))
    assert overlay._current_tool() == "pen"
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    # 真实双击序列:press → release → dblclick → release,全程无拖动。
    overlay.mousePressEvent(MouseEventStub(QPointF(80, 80)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(80, 80)))  # type: ignore[arg-type]
    overlay.mouseDoubleClickEvent(MouseEventStub(QPointF(80, 80)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(80, 80)))  # type: ignore[arg-type]
    qapplication.processEvents()

    assert completed == ["copy"]
    assert overlay.annotations == []


def test_double_click_then_drag_draws_instead_of_finishing(qapplication):
    overlay = make_overlay("copy")
    drag(overlay, QPointF(20, 20), QPointF(200, 150))
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    # 快速两笔:第二笔以 dblclick 事件开始但拖出了笔迹 → 照常作画。
    overlay.mousePressEvent(MouseEventStub(QPointF(60, 60)))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(QPointF(100, 90)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(100, 90)))  # type: ignore[arg-type]
    overlay.mouseDoubleClickEvent(MouseEventStub(QPointF(62, 60)))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(QPointF(110, 70)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(110, 70)))  # type: ignore[arg-type]
    qapplication.processEvents()

    assert completed == []
    assert len(overlay.annotations) == 2
    overlay.cancel()


def test_double_click_with_rect_tool_and_no_drag_finishes(qapplication):
    overlay = make_overlay("save")
    drag(overlay, QPointF(20, 20), QPointF(200, 150))
    overlay.set_tool("rect")
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    overlay.mousePressEvent(MouseEventStub(QPointF(80, 80)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(80, 80)))  # type: ignore[arg-type]
    overlay.mouseDoubleClickEvent(MouseEventStub(QPointF(80, 80)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(80, 80)))  # type: ignore[arg-type]
    qapplication.processEvents()

    assert completed == ["save"]


def test_jittery_double_click_still_finishes_without_dot(qapplication):
    overlay = make_overlay("copy")
    drag(overlay, QPointF(20, 20), QPointF(200, 150))
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    # 真实双击常带 1-2px 抖动(Windows 容差 4px):仍要完成,不留杂点。
    overlay.mousePressEvent(MouseEventStub(QPointF(80, 80)))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(QPointF(81, 80)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(81, 80)))  # type: ignore[arg-type]
    overlay.mouseDoubleClickEvent(MouseEventStub(QPointF(80, 80)))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(QPointF(81, 81)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(81, 81)))  # type: ignore[arg-type]
    qapplication.processEvents()

    assert completed == ["copy"]
    assert overlay.annotations == []


def test_thin_long_drag_after_dblclick_does_not_finish(qapplication):
    overlay = make_overlay("copy")
    drag(overlay, QPointF(20, 20), QPointF(260, 150))
    overlay.set_tool("rect")
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    # 双击后拖出 50×2px 的细长矩形:形状虽无效,但绝不是"没拖动"。
    overlay.mousePressEvent(MouseEventStub(QPointF(60, 60)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(60, 60)))  # type: ignore[arg-type]
    overlay.mouseDoubleClickEvent(MouseEventStub(QPointF(60, 60)))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(QPointF(110, 62)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(110, 62)))  # type: ignore[arg-type]
    qapplication.processEvents()

    assert overlay.state == "editing"
    assert not overlay._resolved
    overlay.cancel()
    qapplication.processEvents()
    assert completed == []


def test_double_click_on_resize_handle_zone_still_finishes(qapplication):
    overlay = make_overlay("copy")
    drag(overlay, QPointF(20, 20), QPointF(160, 120))
    completed: list[str] = []
    overlay.completed.connect(lambda image, action, pos: completed.append(action))

    # 角把手命中区(向选区内延伸 7px)内双击,也必须能完成。
    overlay.mousePressEvent(MouseEventStub(QPointF(23, 23)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(23, 23)))  # type: ignore[arg-type]
    overlay.mouseDoubleClickEvent(MouseEventStub(QPointF(23, 23)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(23, 23)))  # type: ignore[arg-type]
    qapplication.processEvents()

    assert completed == ["copy"]


def test_tiny_jitter_single_click_leaves_no_dot(qapplication):
    overlay = make_overlay()
    drag(overlay, QPointF(20, 20), QPointF(200, 150))

    overlay.mousePressEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(QPointF(51, 50)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(51, 50)))  # type: ignore[arg-type]

    assert overlay.annotations == []

    # 超过阈值的正常短笔画仍然要能画出来。
    overlay.mousePressEvent(MouseEventStub(QPointF(50, 50)))  # type: ignore[arg-type]
    overlay.mouseMoveEvent(MouseEventStub(QPointF(58, 55)))  # type: ignore[arg-type]
    overlay.mouseReleaseEvent(MouseEventStub(QPointF(58, 55)))  # type: ignore[arg-type]

    assert len(overlay.annotations) == 1
    overlay.cancel()
