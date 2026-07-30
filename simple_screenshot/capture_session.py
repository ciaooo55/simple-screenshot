from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
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
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QToolButton, QWidget

from .annotations import Annotation, PenAnnotation, draw_annotations, render_selection
from .ocr import OcrOutcome, OcrSpan


ZOOM_STEP = 1.1
MIN_ZOOM = 0.2
MAX_ZOOM = 5.0


class _CaptureCanvas(QWidget):
    """会话窗口唯一的图片交互区，避免原生窗口和工具栏抢走手势。"""

    def __init__(self, session: "CaptureSessionWindow") -> None:
        super().__init__(session)
        self._session = session
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        self._session._paint_canvas(painter)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._session.mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._session.mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._session.mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._session.mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._session.wheelEvent(event)


class CaptureSessionWindow(QWidget):
    """一次截图的普通任务栏窗口:默认画笔,双击完成,可回到框选。"""

    completed = Signal(object, str)
    reselect_requested = Signal()
    ocr_requested = Signal(object)
    closed = Signal(object)

    def __init__(self, image: QImage, primary_action: str) -> None:
        super().__init__(None)
        self._image = QImage(image)
        self._base_size = self._image.deviceIndependentSize().toSize()
        self._source_scale = max(1.0, float(self._image.devicePixelRatio()))
        self.primary_action = primary_action
        self.annotations: list[Annotation] = []
        self._history: list[list[Annotation]] = []
        self._active_path: QPainterPath | None = None
        self._pen_last = QPointF()
        self._press_view_point: QPointF | None = None
        self._pen_dragged = False
        self._dblclick_candidate = False
        self._zoom = 1.0
        self._min_zoom = MIN_ZOOM
        self._toolbar_height = 34
        self._canvas_margin = 6.0
        self._ocr_loading = False
        self._ocr_outcome: OcrOutcome | None = None
        self._ocr_anchor: int | None = None
        self._ocr_focus: int | None = None
        self._ocr_dragging = False
        self._closed = False

        action_text = "复制" if primary_action == "copy" else "保存"
        self.setWindowTitle(f"截图 - 双击{action_text}")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._canvas = _CaptureCanvas(self)
        self._toolbar = self._create_toolbar()
        self._configure_viewport()
        self._canvas.setCursor(Qt.CursorShape.CrossCursor)

    @property
    def image(self) -> QImage:
        return self._image

    def _create_toolbar(self) -> QFrame:
        toolbar = QFrame(self)
        toolbar.setStyleSheet(
            "QFrame { background: #ffffff; border-bottom: 1px solid #d8dde5; } "
            "QToolButton { color: #30343b; border: 0; border-radius: 4px; "
            "padding: 2px 6px; min-width: 36px; } "
            "QToolButton:hover { background: #edf1f6; } "
            "QToolButton:checked { background: #dbeafe; color: #0f5fbf; }"
        )
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(2)

        def button(label: str, tooltip: str, callback) -> QToolButton:  # type: ignore[no-untyped-def]
            item = QToolButton(toolbar)
            item.setText(label)
            item.setToolTip(tooltip)
            item.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            item.clicked.connect(callback)
            layout.addWidget(item)
            return item

        button("复制", "复制并关闭（Ctrl+C）", lambda: self._complete("copy"))
        button("保存", "保存并关闭（Ctrl+S）", lambda: self._complete("save"))
        self._pen_button = button("画笔", "画笔已启用：在图片上按住左键拖动", self._activate_pen)
        self._pen_button.setCheckable(True)
        self._pen_button.setChecked(True)
        self._ocr_button = button("识别", "识别文字（W）", self.request_ocr)
        layout.addStretch(1)
        return toolbar

    def _configure_viewport(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else self.rect()
        margin = self._canvas_margin
        toolbar_width = max(300, self._toolbar.sizeHint().width())
        max_window_width = max(toolbar_width, round(available.width() * 0.86))
        max_window_height = max(180, round(available.height() * 0.84))
        max_image_width = max(1.0, max_window_width - margin * 2)
        max_image_height = max(
            1.0,
            max_window_height - self._toolbar_height - margin * 2,
        )
        fit = min(
            1.0,
            max_image_width / max(1.0, self._base_size.width()),
            max_image_height / max(1.0, self._base_size.height()),
        )
        image_width = max(1, round(self._base_size.width() * fit))
        image_height = max(1, round(self._base_size.height() * fit))
        width = max(toolbar_width, image_width + round(margin * 2))
        height = max(
            180,
            image_height + self._toolbar_height + round(margin * 2),
        )
        self.setMinimumSize(min(300, width), min(140, height))
        self.resize(width, height)
        # QWidget 首次隐藏创建时不会把子控件标记为 visible；显式布局后
        # 再计算缩放，避免空画布导出负缩放值，导致图片无法命中鼠标事件。
        self._layout_children()
        canvas = self._canvas_rect()
        self._min_zoom = min(
            MIN_ZOOM,
            canvas.width() / max(1.0, self._base_size.width()),
            canvas.height() / max(1.0, self._base_size.height()),
        )
        self._zoom = fit

    def _activate_pen(self) -> None:
        """画笔是默认工具；按钮用于把焦点明确还给绘制画布。"""
        if self._ocr_loading or self._ocr_outcome is not None:
            return
        self._pen_button.setChecked(True)
        self._canvas.setFocus(Qt.FocusReason.MouseFocusReason)
        self._canvas.setCursor(Qt.CursorShape.CrossCursor)

    def _canvas_rect(self) -> QRectF:
        return QRectF(self._canvas.rect()).adjusted(
            self._canvas_margin,
            self._canvas_margin,
            -self._canvas_margin,
            -self._canvas_margin,
        )

    def _image_rect(self) -> QRectF:
        canvas = self._canvas_rect()
        width = self._base_size.width() * self._zoom
        height = self._base_size.height() * self._zoom
        return QRectF(
            canvas.center().x() - width / 2,
            canvas.center().y() - height / 2,
            width,
            height,
        )

    def _source_point(self, point: QPointF) -> QPointF | None:
        target = self._image_rect()
        if not target.contains(point):
            return None
        return QPointF(
            (point.x() - target.left()) * self._base_size.width() / target.width(),
            (point.y() - target.top()) * self._base_size.height() / target.height(),
        )

    def _span_rect(self, span: OcrSpan) -> QRectF:
        target = self._image_rect()
        return QRectF(
            target.left() + span.left * target.width() / self._image.width(),
            target.top() + span.top * target.height() / self._image.height(),
            max(1.0, (span.right - span.left) * target.width() / self._image.width()),
            max(1.0, (span.bottom - span.top) * target.height() / self._image.height()),
        )

    def _selected_range(self) -> tuple[int, int] | None:
        if self._ocr_anchor is None or self._ocr_focus is None:
            return None
        return min(self._ocr_anchor, self._ocr_focus), max(self._ocr_anchor, self._ocr_focus)

    def _ocr_index_at(self, point: QPointF) -> int | None:
        if self._ocr_outcome is None:
            return None
        closest: tuple[float, int] | None = None
        for index, span in enumerate(self._ocr_outcome.spans):
            rect = self._span_rect(span)
            if rect.adjusted(-2, -2, 2, 2).contains(point):
                return index
            if rect.top() - 5 <= point.y() <= rect.bottom() + 5:
                distance = abs(rect.center().x() - point.x())
                if closest is None or distance < closest[0]:
                    closest = distance, index
        return closest[1] if closest else None

    def _ocr_text(self, start: int, end: int) -> str:
        if self._ocr_outcome is None:
            return ""
        parts: list[str] = []
        previous_line: int | None = None
        for span in self._ocr_outcome.spans[start : end + 1]:
            if previous_line is not None and previous_line != span.line_index:
                parts.append("\n")
            parts.append(span.text)
            previous_line = span.line_index
        return "".join(parts).strip()

    def _copy_selected_text(self) -> None:
        selected = self._selected_range()
        if selected is None:
            return
        text = self._ocr_text(*selected)
        if text:
            QApplication.clipboard().setText(text)

    def _word_range(self, index: int) -> tuple[int, int]:
        if self._ocr_outcome is None:
            return index, index
        spans = self._ocr_outcome.spans
        is_word = lambda value: bool(value and value.isascii() and (value.isalnum() or value in "_-'"))  # noqa: E731
        if not is_word(spans[index].text):
            return index, index
        start = end = index
        while start > 0 and spans[start - 1].line_index == spans[index].line_index and is_word(spans[start - 1].text):
            start -= 1
        while end + 1 < len(spans) and spans[end + 1].line_index == spans[index].line_index and is_word(spans[end + 1].text):
            end += 1
        return start, end

    def _discard_active_path(self) -> None:
        self._active_path = None
        self._press_view_point = None
        self._pen_dragged = False
        self._dblclick_candidate = False

    def _undo(self) -> None:
        if self._history:
            self.annotations = self._history.pop()
            self._canvas.update()

    def _complete(self, action: str) -> None:
        image = render_selection(
            self._image,
            QRectF(0.0, 0.0, float(self._base_size.width()), float(self._base_size.height())),
            self._source_scale,
            self.annotations,
        )
        if image.isNull():
            return
        image.setDevicePixelRatio(self._source_scale)
        self.completed.emit(image, action)

    def request_ocr(self) -> None:
        if self._ocr_loading or self._ocr_outcome is not None:
            return
        self._discard_active_path()
        self._ocr_loading = True
        self._toolbar.hide()
        self._layout_children()
        self._canvas.setCursor(Qt.CursorShape.WaitCursor)
        self.ocr_requested.emit(QImage(self._image))
        self._canvas.update()

    def set_ocr_result(self, outcome: OcrOutcome) -> None:
        if not self._ocr_loading:
            return
        self._ocr_loading = False
        if not outcome.text or not outcome.spans:
            self._exit_ocr_mode()
            return
        self._ocr_outcome = outcome
        self._canvas.setCursor(Qt.CursorShape.IBeamCursor)
        self._canvas.update()

    def set_ocr_error(self, message: str) -> None:
        del message
        if self._ocr_loading:
            self._exit_ocr_mode()

    def _exit_ocr_mode(self) -> None:
        self._ocr_loading = False
        self._ocr_outcome = None
        self._ocr_anchor = None
        self._ocr_focus = None
        self._ocr_dragging = False
        self._toolbar.show()
        self._layout_children()
        self._canvas.setCursor(Qt.CursorShape.CrossCursor)
        self._canvas.update()

    def _paint_canvas(self, painter: QPainter) -> None:
        painter.fillRect(self._canvas.rect(), QColor("#e9edf2"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        target = self._image_rect()
        painter.drawImage(target, self._image)
        painter.setPen(QPen(QColor("#aeb7c2"), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(target.adjusted(0.5, 0.5, -0.5, -0.5))
        if self._ocr_outcome is not None:
            selected = self._selected_range()
            for index, span in enumerate(self._ocr_outcome.spans):
                if selected and selected[0] <= index <= selected[1]:
                    painter.fillRect(self._span_rect(span).adjusted(-1, -1, 1, 1), QColor(22, 119, 255, 105))
        else:
            painter.save()
            painter.translate(target.left(), target.top())
            painter.scale(target.width() / self._base_size.width(), target.height() / self._base_size.height())
            active = PenAnnotation(self._active_path, "#ff3b30", 4.0) if self._active_path is not None else None
            draw_annotations(painter, self.annotations, active)
            painter.restore()
    def _layout_children(self) -> None:
        toolbar_visible = not self._ocr_loading and self._ocr_outcome is None
        top = self._toolbar_height if toolbar_visible else 0
        self._toolbar.setGeometry(0, 0, self.width(), self._toolbar_height)
        self._canvas.setGeometry(0, top, self.width(), max(1, self.height() - top))

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._layout_children()
        super().resizeEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._handle_right_click()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._ocr_outcome is not None:
            index = self._ocr_index_at(event.position())
            self._ocr_anchor = index
            self._ocr_focus = index
            self._ocr_dragging = index is not None
            self._canvas.update()
            event.accept()
            return
        if self._ocr_loading:
            event.accept()
            return
        point = self._source_point(event.position())
        if point is None:
            event.accept()
            return
        self._active_path = QPainterPath(point)
        self._pen_last = point
        self._press_view_point = QPointF(event.position())
        self._pen_dragged = False
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._ocr_outcome is not None:
            if self._ocr_dragging:
                index = self._ocr_index_at(event.position())
                if index is not None:
                    self._ocr_focus = index
                self._canvas.update()
            return
        if self._active_path is None or self._press_view_point is None:
            return
        if (event.position() - self._press_view_point).manhattanLength() >= QApplication.startDragDistance():
            self._pen_dragged = True
            point = self._source_point(event.position())
            if point is not None:
                midpoint = QPointF((self._pen_last.x() + point.x()) / 2, (self._pen_last.y() + point.y()) / 2)
                self._active_path.quadTo(self._pen_last, midpoint)
                self._pen_last = point
                self._canvas.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._ocr_outcome is not None:
            if self._ocr_dragging:
                index = self._ocr_index_at(event.position())
                if index is not None:
                    self._ocr_focus = index
            self._ocr_dragging = False
            self._canvas.update()
            event.accept()
            return
        if self._active_path is None:
            return
        if self._dblclick_candidate and not self._pen_dragged:
            self._discard_active_path()
            self._complete(self.primary_action)
            event.accept()
            return
        if self._pen_dragged:
            point = self._source_point(event.position()) or self._pen_last
            self._active_path.lineTo(point)
            self._history.append(list(self.annotations))
            self.annotations.append(PenAnnotation(self._active_path, "#ff3b30", 4.0))
        self._discard_active_path()
        self._canvas.update()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._ocr_outcome is not None:
            index = self._ocr_index_at(event.position())
            if index is not None:
                self._ocr_anchor, self._ocr_focus = self._word_range(index)
                self._canvas.update()
            event.accept()
            return
        if self._active_path is None:
            point = self._source_point(event.position())
            if point is not None:
                self._active_path = QPainterPath(point)
                self._pen_last = point
                self._press_view_point = QPointF(event.position())
        self._dblclick_candidate = True
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._ocr_loading or self._ocr_outcome is not None:
            event.accept()
            return
        steps = event.angleDelta().y() / 120.0
        if steps:
            self._zoom = min(MAX_ZOOM, max(self._min_zoom, self._zoom * (ZOOM_STEP**steps)))
            self._canvas.update()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._ocr_loading:
            event.accept()
            return
        if self._ocr_outcome is not None:
            if event.key() == Qt.Key.Key_Escape:
                self._exit_ocr_mode()
            elif event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if event.key() == Qt.Key.Key_A and self._ocr_outcome.spans:
                    self._ocr_anchor = 0
                    self._ocr_focus = len(self._ocr_outcome.spans) - 1
                    self._canvas.update()
                elif event.key() == Qt.Key.Key_C:
                    self._copy_selected_text()
            event.accept()
            return
        if not event.modifiers() and event.key() == Qt.Key.Key_W:
            self.request_ocr()
            event.accept()
            return
        if not event.modifiers() and event.key() == Qt.Key.Key_Escape:
            self._handle_right_click()
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                if self._active_path is not None:
                    self._discard_active_path()
                    self._canvas.update()
                else:
                    self._undo()
                event.accept()
                return
            if event.key() == Qt.Key.Key_C:
                self._complete("copy")
                event.accept()
                return
            if event.key() == Qt.Key.Key_S:
                self._complete("save")
                event.accept()
                return
        super().keyPressEvent(event)

    def _handle_right_click(self) -> None:
        if self._ocr_loading or self._ocr_outcome is not None:
            self._exit_ocr_mode()
        elif self._active_path is not None:
            self._discard_active_path()
            self._canvas.update()
        elif self.annotations:
            self._undo()
        else:
            self.reselect_requested.emit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closed:
            self._closed = True
            self.closed.emit(self)
        event.accept()
