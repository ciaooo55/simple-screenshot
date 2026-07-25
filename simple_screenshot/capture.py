from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QToolButton,
    QWidget,
)

from .annotations import (
    Annotation,
    PenAnnotation,
    TextAnnotation,
    draw_annotations,
    render_selection,
    translated_annotations,
)
from .window_targets import WindowTarget, discover_window_targets


@dataclass(frozen=True, slots=True)
class CapturedDesktop:
    image: QImage
    virtual_geometry: QRect
    render_scale: float


def capture_virtual_desktop() -> CapturedDesktop:
    screens = QGuiApplication.screens()
    if not screens:
        raise RuntimeError("没有检测到可用显示器")

    virtual_geometry = QRect(screens[0].geometry())
    for screen in screens[1:]:
        virtual_geometry = virtual_geometry.united(screen.geometry())

    render_scale = max(max(1.0, float(screen.devicePixelRatio())) for screen in screens)
    width = max(1, math.ceil(virtual_geometry.width() * render_scale))
    height = max(1, math.ceil(virtual_geometry.height() * render_scale))
    desktop = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    desktop.fill(QColor("black"))

    painter = QPainter(desktop)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    for screen in screens:
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            painter.end()
            raise RuntimeError(f"无法捕获显示器：{screen.name()}")
        geometry = screen.geometry()
        target = QRectF(
            (geometry.x() - virtual_geometry.x()) * render_scale,
            (geometry.y() - virtual_geometry.y()) * render_scale,
            geometry.width() * render_scale,
            geometry.height() * render_scale,
        )
        source_image = pixmap.toImage()
        painter.drawImage(target, source_image, QRectF(source_image.rect()))
    painter.end()
    return CapturedDesktop(desktop, virtual_geometry, render_scale)


class InlineTextEdit(QTextEdit):
    commit_requested = Signal()
    escape_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.escape_requested.emit()
            event.accept()
            return
        if (
            event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.commit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().focusOutEvent(event)
        QTimer.singleShot(0, self.commit_requested.emit)


class CaptureOverlay(QWidget):
    completed = Signal(object, str)
    cancelled = Signal()

    def __init__(
        self,
        desktop: CapturedDesktop,
        action: str,
        window_targets: list[WindowTarget] | None = None,
    ) -> None:
        super().__init__(None)
        self.desktop = desktop
        self.action = action
        self.state = "selecting"
        self.selection = QRectF()
        self.drag_origin: QPointF | None = None
        self.annotations: list[Annotation] = []
        self.active_path: QPainterPath | None = None
        self._text_editor: InlineTextEdit | None = None
        self._text_position = QPointF()
        self._selection_before_reselect: QRectF | None = None
        self._annotations_before_reselect: list[Annotation] | None = None
        self._window_targets = (
            list(window_targets)
            if window_targets is not None
            else discover_window_targets(desktop.virtual_geometry)
        )
        self._hovered_window: WindowTarget | None = None
        self._pressed_window: WindowTarget | None = None
        self._selection_transform: str | None = None
        self._transform_origin_point = QPointF()
        self._transform_origin_selection = QRectF()
        self._transform_origin_annotations: list[Annotation] = []
        self._resolved = False

        self.setWindowTitle("区域截图")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(desktop.virtual_geometry)

        self.toolbar = self._create_toolbar()
        self.toolbar.hide()

    def _create_toolbar(self) -> QFrame:
        toolbar = QFrame(self)
        toolbar.setObjectName("captureToolbar")
        toolbar.setStyleSheet(
            "#captureToolbar { background: rgba(28, 31, 38, 245); "
            "border: 1px solid #596273; border-radius: 7px; } "
            "QLabel, QToolButton, QPushButton, QComboBox { color: white; } "
            "QToolButton, QPushButton { padding: 5px 8px; border-radius: 4px; "
            "border: 1px solid transparent; background: #3b4250; } "
            "QToolButton:checked { background: #1677ff; } "
            "QPushButton:hover, QToolButton:hover { background: #536078; } "
            "QPushButton:focus, QToolButton:focus, QComboBox:focus { "
            "border: 1px solid #8ec5ff; } "
            "QPushButton:disabled, QToolButton:disabled, QComboBox:disabled { "
            "color: #8b949e; background: #303641; } "
            "QComboBox { background: #3b4250; padding: 4px; border: 0; }"
        )
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(5)

        self.select_button = QToolButton(toolbar)
        self.select_button.setText("选择")
        self.select_button.setCheckable(True)
        self.pen_button = QToolButton(toolbar)
        self.pen_button.setText("画笔")
        self.pen_button.setCheckable(True)
        self.text_button = QToolButton(toolbar)
        self.text_button.setText("文字")
        self.text_button.setCheckable(True)
        tool_group = QButtonGroup(toolbar)
        tool_group.setExclusive(True)
        tool_group.addButton(self.select_button)
        tool_group.addButton(self.pen_button)
        tool_group.addButton(self.text_button)
        self.select_button.setChecked(True)

        self.color_combo = QComboBox(toolbar)
        self.color_combo.setToolTip("标注颜色")
        for label, color in [
            ("红", "#ff3b30"),
            ("黄", "#ffd60a"),
            ("绿", "#34c759"),
            ("蓝", "#0a84ff"),
            ("黑", "#111111"),
            ("白", "#ffffff"),
        ]:
            self.color_combo.addItem(label, color)

        self.width_combo = QComboBox(toolbar)
        self.width_combo.setToolTip("画笔粗细")
        for width in (2, 4, 8):
            self.width_combo.addItem(f"{width}px", width)
        self.width_combo.setCurrentIndex(1)

        self.font_combo = QComboBox(toolbar)
        self.font_combo.setToolTip("文字字号")
        for size in (16, 24, 32):
            self.font_combo.addItem(f"{size}px", size)
        self.font_combo.setCurrentIndex(1)

        self.undo_button = QPushButton("撤销", toolbar)
        self.clear_button = QPushButton("清空", toolbar)
        cancel_button = QPushButton("取消", toolbar)

        default_action_text = "复制" if self.action == "copy" else "保存"
        shortcut_hint = QLabel(f"双击：{default_action_text}", toolbar)
        shortcut_hint.setStyleSheet("color: #c9d1d9; padding: 0 3px;")

        self.copy_button = QPushButton("复制", toolbar)
        self.save_button = QPushButton("保存", toolbar)
        primary_button = (
            self.copy_button if self.action == "copy" else self.save_button
        )
        primary_button.setStyleSheet(
            "QPushButton { background: #1677ff; font-weight: 600; } "
            "QPushButton:hover { background: #4096ff; }"
        )
        self.copy_button.setToolTip("复制到剪贴板（Ctrl+C）")
        self.save_button.setToolTip("保存到默认目录（Ctrl+S）")

        layout.addWidget(self.select_button)
        layout.addWidget(self.pen_button)
        layout.addWidget(self.text_button)
        layout.addWidget(self.color_combo)
        layout.addWidget(self.width_combo)
        layout.addWidget(self.font_combo)
        layout.addWidget(self.undo_button)
        layout.addWidget(self.clear_button)
        layout.addWidget(cancel_button)
        layout.addWidget(shortcut_hint)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.save_button)

        self.undo_button.clicked.connect(self.undo)
        self.clear_button.clicked.connect(self.clear_annotations)
        cancel_button.clicked.connect(self.cancel)
        self.copy_button.clicked.connect(lambda: self.finish("copy"))
        self.save_button.clicked.connect(lambda: self.finish("save"))
        for button in (self.select_button, self.pen_button, self.text_button):
            button.toggled.connect(self._update_cursor)
            button.toggled.connect(self._sync_tool_options)
        self._sync_tool_options()
        self._sync_annotation_actions()
        return toolbar

    def start(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.grabKeyboard()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(QRectF(self.rect()), self.desktop.image)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 115))

        preview_rect = QRectF(self.selection)
        if preview_rect.isEmpty() and self._hovered_window is not None:
            preview_rect = QRectF(self._hovered_window.rect)

        if self.selection.isEmpty():
            self._draw_selection_hint(painter)
        if not preview_rect.isEmpty():
            painter.save()
            painter.setClipRect(preview_rect)
            painter.drawImage(QRectF(self.rect()), self.desktop.image)
            if not self.selection.isEmpty():
                draw_annotations(
                    painter,
                    self.annotations,
                    self._active_pen_annotation(),
                )
            painter.restore()
            border = QPen(QColor("#58a6ff"), 1.5, Qt.PenStyle.SolidLine)
            painter.setPen(border)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(preview_rect)
            self._draw_size_label(painter, preview_rect)
            if self.state == "editing" and not self.selection.isEmpty():
                self._draw_resize_handles(painter)
        painter.end()

    def _draw_size_label(self, painter: QPainter, rect: QRectF) -> None:
        width = max(0, round(rect.width()))
        height = max(0, round(rect.height()))
        text = f"{width} × {height}"
        label_rect = QRectF(
            rect.left(),
            max(0.0, rect.top() - 26.0),
            110.0,
            22.0,
        )
        painter.fillRect(label_rect, QColor(20, 23, 28, 215))
        painter.setPen(QColor("white"))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_selection_hint(self, painter: QPainter) -> None:
        text = "单击选择窗口  ·  拖动自由框选  ·  右键或 Esc 取消"
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 32
        height = 36
        rect = QRectF((self.width() - width) / 2, 20, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 23, 28, 220))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QColor("white"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_resize_handles(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#1677ff"), 1.0))
        painter.setBrush(QColor("white"))
        for point in self._resize_handle_points().values():
            painter.drawRect(QRectF(point.x() - 3, point.y() - 3, 6, 6))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.cancel()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        if self.state in {"selecting", "reselecting"}:
            self.drag_origin = self._clamp_point(point)
            self._pressed_window = self._window_target_at(point)
            self.selection = QRectF(self.drag_origin, self.drag_origin)
            self.toolbar.hide()
            self.update()
            return

        resize_edge = self._resize_edge_at(point)
        if resize_edge is not None:
            self._begin_selection_transform(resize_edge, point)
            return
        if not self.selection.contains(point):
            self._begin_reselection(point)
            return
        if self.select_button.isChecked():
            self._begin_selection_transform("move", point)
            return
        if self.text_button.isChecked():
            self._begin_text(point)
            return
        self.active_path = QPainterPath(point)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        point = self._clamp_point(event.position())
        if self._selection_transform is not None:
            self._update_selection_transform(point)
            return
        if self.state == "selecting" and self.drag_origin is None:
            self._set_hovered_window(self._window_target_at(point))
            return
        if (
            self.state in {"selecting", "reselecting"}
            and self.drag_origin is not None
        ):
            self.selection = QRectF(self.drag_origin, point).normalized()
            self.update()
            return
        if self.active_path is not None:
            self.active_path.lineTo(point)
            self.update()
            return
        if self.state == "editing":
            self._update_editing_cursor(point)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._selection_transform is not None:
            self._selection_transform = None
            self._transform_origin_annotations = []
            self._position_toolbar()
            self.toolbar.show()
            self._update_editing_cursor(event.position())
            self.update()
            return
        if (
            self.state in {"selecting", "reselecting"}
            and self.drag_origin is not None
        ):
            was_reselecting = self.state == "reselecting"
            self.drag_origin = None
            if self.selection.width() < 2 or self.selection.height() < 2:
                if self._pressed_window is not None:
                    self.selection = QRectF(self._pressed_window.rect)
                    self._pressed_window = None
                    if was_reselecting:
                        self.annotations.clear()
                        self._discard_reselection_backup()
                    self._accept_selection()
                    return
                self._pressed_window = None
                if was_reselecting and self._selection_before_reselect is not None:
                    self.selection = QRectF(self._selection_before_reselect)
                    self.annotations = list(self._annotations_before_reselect or [])
                    self.state = "editing"
                    self._discard_reselection_backup()
                    self._position_toolbar()
                    self.toolbar.show()
                    self._update_cursor()
                else:
                    self.selection = QRectF()
                self.update()
                return
            if was_reselecting:
                self.annotations.clear()
                self._discard_reselection_backup()
            self._pressed_window = None
            self._accept_selection()
            return
        if self.active_path is not None:
            if self.active_path.elementCount() > 1:
                self.annotations.append(
                    PenAnnotation(
                        QPainterPath(self.active_path),
                        self._current_color(),
                        float(self.width_combo.currentData()),
                    )
                )
            self.active_path = None
            self._sync_annotation_actions()
            self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.state == "editing"
            and self.selection.contains(event.position())
        ):
            self.finish()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
            return
        if (
            event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
            and self.state == "editing"
            and self._text_editor is None
        ):
            self.finish()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo()
                return
            if event.key() == Qt.Key.Key_C and self.state == "editing":
                self.finish("copy")
                return
            if event.key() == Qt.Key.Key_S and self.state == "editing":
                self.finish("save")
                return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._resolved:
            self._resolved = True
            self.cancelled.emit()
        self.releaseKeyboard()
        event.accept()

    def undo(self) -> None:
        self._commit_inline_text()
        if self.annotations:
            self.annotations.pop()
            self._sync_annotation_actions()
            self.update()

    def clear_annotations(self) -> None:
        self._discard_inline_text()
        self.active_path = None
        self.annotations.clear()
        self._sync_annotation_actions()
        self.update()

    def finish(self, action: str | None = None) -> None:
        if self._resolved or self.selection.isEmpty():
            return
        resolved_action = action or self.action
        if resolved_action not in {"copy", "save"}:
            return
        self._commit_inline_text()
        image = render_selection(
            self.desktop.image,
            self.selection,
            self.desktop.render_scale,
            self.annotations,
        )
        if image.isNull():
            return
        self._resolved = True
        self.releaseKeyboard()
        self.hide()
        self.completed.emit(image, resolved_action)
        self.close()

    def cancel(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        self._discard_inline_text()
        self.releaseKeyboard()
        self.hide()
        self.cancelled.emit()
        self.close()

    def _active_pen_annotation(self) -> PenAnnotation | None:
        if self.active_path is None:
            return None
        return PenAnnotation(
            self.active_path,
            self._current_color(),
            float(self.width_combo.currentData()),
        )

    def _current_color(self) -> str:
        return str(self.color_combo.currentData())

    def _begin_text(self, point: QPointF) -> None:
        self._commit_inline_text()
        width = max(80.0, min(320.0, self.selection.right() - point.x()))
        height = max(58.0, min(130.0, self.selection.bottom() - point.y()))
        self._text_position = QPointF(point)
        editor = InlineTextEdit(self)
        self._text_editor = editor
        editor.setPlaceholderText("输入文字（Ctrl+Enter 完成）")
        editor.setStyleSheet(
            f"QTextEdit {{ color: {self._current_color()}; "
            "background: rgba(20, 23, 28, 220); border: 1px solid #58a6ff; "
            "border-radius: 4px; padding: 3px; }}"
        )
        font = editor.font()
        font.setFamily("Microsoft YaHei")
        font.setPixelSize(int(self.font_combo.currentData()))
        editor.setFont(font)
        editor.setGeometry(
            QRect(
                round(point.x()),
                round(point.y()),
                round(width),
                round(height),
            )
        )
        editor.commit_requested.connect(
            lambda current=editor: self._commit_inline_text(current)
        )
        editor.escape_requested.connect(self._discard_inline_text)
        editor.show()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        self._sync_annotation_actions()

    def _commit_inline_text(self, expected: InlineTextEdit | None = None) -> None:
        editor = self._text_editor
        if editor is None or (expected is not None and editor is not expected):
            return
        self._text_editor = None
        text = editor.toPlainText().strip()
        width = float(editor.width())
        editor.hide()
        editor.deleteLater()
        if text:
            self.annotations.append(
                TextAnnotation(
                    QPointF(self._text_position),
                    text,
                    self._current_color(),
                    int(self.font_combo.currentData()),
                    width,
                )
            )
            self._sync_annotation_actions()
            self.update()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _discard_inline_text(self) -> None:
        editor = self._text_editor
        self._text_editor = None
        if editor is not None:
            editor.hide()
            editor.deleteLater()
        self._sync_annotation_actions()
        if not self._resolved:
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _begin_reselection(self, point: QPointF) -> None:
        self._commit_inline_text()
        self._selection_before_reselect = QRectF(self.selection)
        self._annotations_before_reselect = list(self.annotations)
        self.state = "reselecting"
        self.drag_origin = self._clamp_point(point)
        self._pressed_window = self._window_target_at(point)
        self.selection = QRectF(self.drag_origin, self.drag_origin)
        self._hovered_window = None
        self._selection_transform = None
        self.toolbar.hide()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def _discard_reselection_backup(self) -> None:
        self._selection_before_reselect = None
        self._annotations_before_reselect = None

    def _accept_selection(self) -> None:
        self.state = "editing"
        self._hovered_window = None
        self._position_toolbar()
        self.toolbar.show()
        self._sync_annotation_actions()
        self._update_cursor()
        self.update()

    def _window_target_at(self, point: QPointF) -> WindowTarget | None:
        for target in self._window_targets:
            if target.rect.contains(point):
                return target
        return None

    def _set_hovered_window(self, target: WindowTarget | None) -> None:
        if target == self._hovered_window:
            return
        self._hovered_window = target
        self.update()

    def _sync_annotation_actions(self) -> None:
        enabled = bool(self.annotations or self.active_path or self._text_editor)
        if hasattr(self, "undo_button"):
            self.undo_button.setEnabled(enabled)
            self.clear_button.setEnabled(enabled)

    def _sync_tool_options(self) -> None:
        pen_active = self.pen_button.isChecked()
        annotation_active = pen_active or self.text_button.isChecked()
        self.color_combo.setEnabled(annotation_active)
        self.width_combo.setEnabled(pen_active)
        self.font_combo.setEnabled(self.text_button.isChecked())

    def _resize_handle_points(self) -> dict[str, QPointF]:
        left = self.selection.left()
        right = self.selection.right()
        top = self.selection.top()
        bottom = self.selection.bottom()
        center_x = self.selection.center().x()
        center_y = self.selection.center().y()
        return {
            "nw": QPointF(left, top),
            "n": QPointF(center_x, top),
            "ne": QPointF(right, top),
            "e": QPointF(right, center_y),
            "se": QPointF(right, bottom),
            "s": QPointF(center_x, bottom),
            "sw": QPointF(left, bottom),
            "w": QPointF(left, center_y),
        }

    def _resize_edge_at(self, point: QPointF) -> str | None:
        if self.state != "editing" or self.selection.isEmpty():
            return None
        for edge, handle in self._resize_handle_points().items():
            hit_area = QRectF(handle.x() - 7, handle.y() - 7, 14, 14)
            if hit_area.contains(point):
                return edge
        return None

    def _begin_selection_transform(self, transform: str, point: QPointF) -> None:
        self._commit_inline_text()
        self._selection_transform = transform
        self._transform_origin_point = QPointF(point)
        self._transform_origin_selection = QRectF(self.selection)
        self._transform_origin_annotations = list(self.annotations)
        self.toolbar.hide()
        self._update_editing_cursor(point)

    def _update_selection_transform(self, point: QPointF) -> None:
        transform = self._selection_transform
        original = self._transform_origin_selection
        if transform == "move":
            dx = point.x() - self._transform_origin_point.x()
            dy = point.y() - self._transform_origin_point.y()
            dx = max(-original.left(), min(dx, self.width() - original.right()))
            dy = max(-original.top(), min(dy, self.height() - original.bottom()))
            self.selection = original.translated(dx, dy)
            self.annotations = translated_annotations(
                self._transform_origin_annotations,
                dx,
                dy,
            )
            self.update()
            return

        if transform is None:
            return
        left = original.left()
        right = original.right()
        top = original.top()
        bottom = original.bottom()
        if "w" in transform:
            left = max(0.0, min(point.x(), right - 2.0))
        if "e" in transform:
            right = min(float(self.width()), max(point.x(), left + 2.0))
        if "n" in transform:
            top = max(0.0, min(point.y(), bottom - 2.0))
        if "s" in transform:
            bottom = min(float(self.height()), max(point.y(), top + 2.0))
        self.selection = QRectF(QPointF(left, top), QPointF(right, bottom))
        self.update()

    def _update_editing_cursor(self, point: QPointF) -> None:
        transform = self._selection_transform
        edge = transform if transform not in {None, "move"} else None
        if edge is None and transform is None:
            edge = self._resize_edge_at(point)
        cursor_by_edge = {
            "n": Qt.CursorShape.SizeVerCursor,
            "s": Qt.CursorShape.SizeVerCursor,
            "e": Qt.CursorShape.SizeHorCursor,
            "w": Qt.CursorShape.SizeHorCursor,
            "nw": Qt.CursorShape.SizeFDiagCursor,
            "se": Qt.CursorShape.SizeFDiagCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor,
            "sw": Qt.CursorShape.SizeBDiagCursor,
        }
        if edge in cursor_by_edge:
            self.setCursor(cursor_by_edge[edge])
        elif transform == "move" or (
            self.select_button.isChecked() and self.selection.contains(point)
        ):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self._update_cursor()

    def _position_toolbar(self) -> None:
        self.toolbar.adjustSize()
        size = self.toolbar.sizeHint()
        x = round(self.selection.right() - size.width())
        x = max(6, min(x, self.width() - size.width() - 6))
        below = round(self.selection.bottom() + 8)
        above = round(self.selection.top() - size.height() - 8)
        y = below if below + size.height() <= self.height() - 6 else above
        y = max(6, min(y, self.height() - size.height() - 6))
        self.toolbar.move(QPoint(x, y))

    def _clamp_point(self, point: QPointF) -> QPointF:
        return QPointF(
            min(max(point.x(), 0.0), float(self.width())),
            min(max(point.y(), 0.0), float(self.height())),
        )

    def _update_cursor(self) -> None:
        if self.state in {"selecting", "reselecting"}:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self.select_button.isChecked():
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self.text_button.isChecked():
            self.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
