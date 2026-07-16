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
)


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

    def __init__(self, desktop: CapturedDesktop, action: str) -> None:
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
            "background: #3b4250; } "
            "QToolButton:checked { background: #1677ff; } "
            "QPushButton:hover, QToolButton:hover { background: #536078; } "
            "QComboBox { background: #3b4250; padding: 4px; border: 0; }"
        )
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(5)

        self.pen_button = QToolButton(toolbar)
        self.pen_button.setText("画笔")
        self.pen_button.setCheckable(True)
        self.text_button = QToolButton(toolbar)
        self.text_button.setText("文字")
        self.text_button.setCheckable(True)
        tool_group = QButtonGroup(toolbar)
        tool_group.setExclusive(True)
        tool_group.addButton(self.pen_button)
        tool_group.addButton(self.text_button)
        self.pen_button.setChecked(True)

        self.color_combo = QComboBox(toolbar)
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
        for width in (2, 4, 8):
            self.width_combo.addItem(f"{width}px", width)
        self.width_combo.setCurrentIndex(1)

        self.font_combo = QComboBox(toolbar)
        for size in (16, 24, 32):
            self.font_combo.addItem(f"{size}px", size)
        self.font_combo.setCurrentIndex(1)

        undo_button = QPushButton("撤销", toolbar)
        clear_button = QPushButton("清空", toolbar)
        cancel_button = QPushButton("取消", toolbar)
        finish_button = QPushButton("复制" if self.action == "copy" else "保存", toolbar)
        finish_button.setStyleSheet(
            "QPushButton { background: #1677ff; font-weight: 600; } "
            "QPushButton:hover { background: #4096ff; }"
        )

        layout.addWidget(self.pen_button)
        layout.addWidget(self.text_button)
        layout.addWidget(QLabel("颜色", toolbar))
        layout.addWidget(self.color_combo)
        layout.addWidget(QLabel("粗细", toolbar))
        layout.addWidget(self.width_combo)
        layout.addWidget(QLabel("字号", toolbar))
        layout.addWidget(self.font_combo)
        layout.addWidget(undo_button)
        layout.addWidget(clear_button)
        layout.addWidget(cancel_button)
        layout.addWidget(finish_button)

        undo_button.clicked.connect(self.undo)
        clear_button.clicked.connect(self.clear_annotations)
        cancel_button.clicked.connect(self.cancel)
        finish_button.clicked.connect(self.finish)
        self.pen_button.toggled.connect(self._update_cursor)
        self.text_button.toggled.connect(self._update_cursor)
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

        if not self.selection.isEmpty():
            painter.save()
            painter.setClipRect(self.selection)
            painter.drawImage(QRectF(self.rect()), self.desktop.image)
            draw_annotations(painter, self.annotations, self._active_pen_annotation())
            painter.restore()
            border = QPen(QColor("#58a6ff"), 1.5, Qt.PenStyle.SolidLine)
            painter.setPen(border)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.selection)
            self._draw_size_label(painter)
        painter.end()

    def _draw_size_label(self, painter: QPainter) -> None:
        width = max(0, round(self.selection.width()))
        height = max(0, round(self.selection.height()))
        text = f"{width} × {height}"
        label_rect = QRectF(
            self.selection.left(),
            max(0.0, self.selection.top() - 26.0),
            110.0,
            22.0,
        )
        painter.fillRect(label_rect, QColor(20, 23, 28, 215))
        painter.setPen(QColor("white"))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        if self.state == "selecting":
            self.drag_origin = self._clamp_point(point)
            self.selection = QRectF(self.drag_origin, self.drag_origin)
            self.toolbar.hide()
            self.update()
            return

        if not self.selection.contains(point):
            return
        if self.text_button.isChecked():
            self._begin_text(point)
            return
        self.active_path = QPainterPath(point)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        point = self._clamp_point(event.position())
        if self.state == "selecting" and self.drag_origin is not None:
            self.selection = QRectF(self.drag_origin, point).normalized()
            self.update()
            return
        if self.active_path is not None:
            self.active_path.lineTo(point)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.state == "selecting" and self.drag_origin is not None:
            self.drag_origin = None
            if self.selection.width() < 2 or self.selection.height() < 2:
                self.selection = QRectF()
                self.update()
                return
            self.state = "editing"
            self._position_toolbar()
            self.toolbar.show()
            self._update_cursor()
            self.update()
            return
        if self.active_path is not None:
            self.annotations.append(
                PenAnnotation(
                    QPainterPath(self.active_path),
                    self._current_color(),
                    float(self.width_combo.currentData()),
                )
            )
            self.active_path = None
            self.update()

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
            self.update()

    def clear_annotations(self) -> None:
        self._discard_inline_text()
        self.active_path = None
        self.annotations.clear()
        self.update()

    def finish(self) -> None:
        if self._resolved or self.selection.isEmpty():
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
        self.completed.emit(image, self.action)
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
        editor.escape_requested.connect(self.cancel)
        editor.show()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)

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
            self.update()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _discard_inline_text(self) -> None:
        editor = self._text_editor
        self._text_editor = None
        if editor is not None:
            editor.hide()
            editor.deleteLater()

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
        if self.state == "selecting":
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self.text_button.isChecked():
            self.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
