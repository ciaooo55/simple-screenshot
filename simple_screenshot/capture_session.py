from __future__ import annotations

import math

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
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QToolButton,
    QWidget,
)

from .annotations import (
    Annotation,
    ArrowAnnotation,
    MosaicAnnotation,
    NumberAnnotation,
    PenAnnotation,
    ShapeAnnotation,
    TextAnnotation,
    draw_annotations,
    render_selection,
)
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
        self._shape_origin: QPointF | None = None
        self._active_shape: Annotation | None = None
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
        self._tool = "pen"

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
            "padding: 2px 4px; min-width: 32px; } "
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
            item.setFixedWidth(42)
            item.clicked.connect(callback)
            layout.addWidget(item)
            return item

        button("复制", "复制并关闭（Ctrl+C）", lambda: self._complete("copy"))
        button("保存", "保存并关闭（Ctrl+S）", lambda: self._complete("save"))

        tool_group = QButtonGroup(toolbar)
        tool_group.setExclusive(True)
        self._tool_buttons: dict[str, QToolButton] = {}

        def tool(
            name: str,
            label: str,
            tooltip: str,
            *,
            visible: bool = True,
        ) -> QToolButton:
            if visible:
                item = button(
                    label,
                    tooltip,
                    lambda _checked=False, selected=name: self.set_tool(selected),
                )
            else:
                item = QToolButton(toolbar)
                item.setText(label)
                item.setToolTip(tooltip)
                item.hide()
            item.setCheckable(True)
            tool_group.addButton(item)
            self._tool_buttons[name] = item
            return item

        self._pen_button = tool("pen", "画笔", "自由画笔（P）")
        tool("arrow", "箭头", "拖动绘制箭头（A）")
        tool("rect", "矩形", "拖动绘制矩形（R）")
        more_tools = (
            ("highlight", "荧光", "半透明荧光笔（G）"),
            ("ellipse", "椭圆", "拖动绘制椭圆（O）"),
            ("number", "序号", "单击放置序号（N）"),
            ("mosaic", "马赛克", "拖动遮盖内容（M）"),
            ("text", "文字", "单击添加文字（T）"),
        )
        for name, label, tooltip in more_tools:
            tool(name, label, tooltip, visible=False)
        self._more_button = QToolButton(toolbar)
        self._more_button.setText("更多")
        self._more_button.setToolTip("荧光、椭圆、序号、马赛克、文字")
        self._more_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._more_button.setFixedWidth(42)
        more_menu = QMenu(self._more_button)
        for name, label, tooltip in more_tools:
            action = more_menu.addAction(label)
            action.setToolTip(tooltip)
            action.triggered.connect(
                lambda _checked=False, selected=name: self.set_tool(selected)
            )
        self._more_button.setMenu(more_menu)
        self._more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(self._more_button)
        self._pen_button.setChecked(True)

        self._color_combo = QComboBox(toolbar)
        self._color_combo.setToolTip("标注颜色")
        self._color_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for label, color in (
            ("红", "#ff3b30"),
            ("黄", "#ffd60a"),
            ("绿", "#34c759"),
            ("蓝", "#0a84ff"),
            ("白", "#ffffff"),
            ("黑", "#111111"),
        ):
            self._color_combo.addItem(label, color)
        self._color_combo.setFixedWidth(48)
        self._color_combo.hide()

        self._width_combo = QComboBox(toolbar)
        self._width_combo.setToolTip("线条粗细")
        self._width_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for width in (2, 4, 6, 8):
            self._width_combo.addItem(str(width), width)
        self._width_combo.setCurrentIndex(1)
        self._width_combo.setFixedWidth(42)
        self._width_combo.hide()

        style_button = QToolButton(toolbar)
        style_button.setText("样式")
        style_button.setToolTip("标注颜色和粗细")
        style_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        style_button.setFixedWidth(42)
        style_menu = QMenu(style_button)
        color_menu = style_menu.addMenu("颜色")
        for index in range(self._color_combo.count()):
            action = color_menu.addAction(self._color_combo.itemText(index))
            action.triggered.connect(
                lambda _checked=False, selected=index: self._color_combo.setCurrentIndex(
                    selected
                )
            )
        width_menu = style_menu.addMenu("粗细")
        for index in range(self._width_combo.count()):
            action = width_menu.addAction(f"{self._width_combo.itemText(index)} px")
            action.triggered.connect(
                lambda _checked=False, selected=index: self._width_combo.setCurrentIndex(
                    selected
                )
            )
        style_button.setMenu(style_menu)
        style_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(style_button)

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

    def set_tool(self, name: str) -> None:
        """切换标注工具；全部工具留在同一个会话窗口内。"""
        if self._ocr_loading or self._ocr_outcome is not None:
            return
        if name not in self._tool_buttons:
            return
        self._discard_active_annotation()
        self._tool = name
        self._tool_buttons[name].setChecked(True)
        hidden_labels = {
            "highlight": "荧光",
            "ellipse": "椭圆",
            "number": "序号",
            "mosaic": "打码",
            "text": "文字",
        }
        self._more_button.setText(hidden_labels.get(name, "更多"))
        self._canvas.setFocus(Qt.FocusReason.MouseFocusReason)
        self._canvas.setCursor(
            Qt.CursorShape.IBeamCursor
            if name == "text"
            else Qt.CursorShape.CrossCursor
        )

    def _activate_pen(self) -> None:
        self.set_tool("pen")

    def _current_color(self) -> str:
        return str(self._color_combo.currentData())

    def _current_width(self) -> float:
        return float(self._width_combo.currentData())

    def _pen_style(self) -> tuple[str, float]:
        color = QColor(self._current_color())
        width = self._current_width()
        if self._tool == "highlight":
            color.setAlpha(102)
            width *= 3.0
        return color.name(QColor.NameFormat.HexArgb), width

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

    def _discard_active_annotation(self) -> None:
        self._active_path = None
        self._shape_origin = None
        self._active_shape = None
        self._press_view_point = None
        self._pen_dragged = False
        self._dblclick_candidate = False

    # 兼容既有调用与测试名称。
    def _discard_active_path(self) -> None:
        self._discard_active_annotation()

    def _undo(self) -> None:
        if self._history:
            self.annotations = self._history.pop()
            self._canvas.update()

    def _push_annotation(self, annotation: Annotation) -> None:
        self._history.append(list(self.annotations))
        self.annotations.append(annotation)
        self._canvas.update()

    def _next_number(self) -> int:
        values = [
            item.number
            for item in self.annotations
            if isinstance(item, NumberAnnotation)
        ]
        return max(values, default=0) + 1

    def _build_shape(self, origin: QPointF, point: QPointF) -> Annotation | None:
        if self._tool == "arrow":
            if math.hypot(point.x() - origin.x(), point.y() - origin.y()) < 3.0:
                return None
            return ArrowAnnotation(
                QPointF(origin),
                QPointF(point),
                self._current_color(),
                self._current_width(),
            )
        rect = QRectF(origin, point).normalized()
        if rect.width() < 3.0 or rect.height() < 3.0:
            return None
        if self._tool == "mosaic":
            block = min(20.0, max(8.0, min(rect.width(), rect.height()) / 20.0))
            return MosaicAnnotation(rect, block)
        if self._tool in {"rect", "ellipse"}:
            return ShapeAnnotation(
                rect,
                self._current_color(),
                self._current_width(),
                self._tool,
            )
        return None

    def _add_text(self, point: QPointF) -> None:
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "添加文字",
            "文字内容：",
        )
        if not accepted or not text.strip():
            return
        width = max(80.0, min(360.0, self._base_size.width() - point.x()))
        self._push_annotation(
            TextAnnotation(
                QPointF(point),
                text.strip(),
                self._current_color(),
                24,
                width,
            )
        )

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
            active: Annotation | None = self._active_shape
            if self._active_path is not None:
                color, width = self._pen_style()
                active = PenAnnotation(self._active_path, color, width)
            draw_annotations(
                painter,
                self.annotations,
                active,
                source=self._image,
                source_scale=self._source_scale,
            )
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
        if self._tool == "number":
            self._push_annotation(
                NumberAnnotation(point, self._next_number(), self._current_color())
            )
            event.accept()
            return
        if self._tool == "text":
            self._add_text(point)
            event.accept()
            return
        if self._tool in {"arrow", "rect", "ellipse", "mosaic"}:
            self._shape_origin = QPointF(point)
            self._press_view_point = QPointF(event.position())
            self._pen_dragged = False
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
        if self._shape_origin is not None:
            point = self._source_point(event.position())
            if point is not None:
                self._active_shape = self._build_shape(self._shape_origin, point)
                if self._press_view_point is not None and (
                    event.position() - self._press_view_point
                ).manhattanLength() >= QApplication.startDragDistance():
                    self._pen_dragged = True
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
        if self._shape_origin is not None:
            release = self._source_point(event.position()) or self._shape_origin
            annotation = self._build_shape(self._shape_origin, release)
            if self._dblclick_candidate and not self._pen_dragged:
                self._discard_active_annotation()
                self._complete(self.primary_action)
                event.accept()
                return
            if annotation is not None:
                self._push_annotation(annotation)
            self._discard_active_annotation()
            event.accept()
            return
        if self._active_path is None:
            return
        if self._dblclick_candidate and not self._pen_dragged:
            self._discard_active_annotation()
            self._complete(self.primary_action)
            event.accept()
            return
        if self._pen_dragged:
            point = self._source_point(event.position()) or self._pen_last
            self._active_path.lineTo(point)
            color, width = self._pen_style()
            self._push_annotation(PenAnnotation(self._active_path, color, width))
        self._discard_active_annotation()
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
        if self._tool in {"number", "text"}:
            event.accept()
            return
        if self._active_path is None and self._shape_origin is None:
            point = self._source_point(event.position())
            if point is not None:
                if self._tool in {"arrow", "rect", "ellipse", "mosaic"}:
                    self._shape_origin = QPointF(point)
                else:
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
        if not event.modifiers():
            shortcuts = {
                Qt.Key.Key_P: "pen",
                Qt.Key.Key_G: "highlight",
                Qt.Key.Key_A: "arrow",
                Qt.Key.Key_R: "rect",
                Qt.Key.Key_O: "ellipse",
                Qt.Key.Key_N: "number",
                Qt.Key.Key_M: "mosaic",
                Qt.Key.Key_T: "text",
            }
            tool = shortcuts.get(event.key())
            if tool is not None:
                self.set_tool(tool)
                event.accept()
                return
        if not event.modifiers() and event.key() == Qt.Key.Key_Escape:
            self._handle_right_click()
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                if self._active_path is not None or self._shape_origin is not None:
                    self._discard_active_annotation()
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
        elif self._active_path is not None or self._shape_origin is not None:
            self._discard_active_annotation()
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
