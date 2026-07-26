from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QCursor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
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
    ArrowAnnotation,
    MosaicAnnotation,
    NumberAnnotation,
    PenAnnotation,
    ShapeAnnotation,
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._released = False

    def release_editor(self) -> None:
        """标记编辑器已被回收,吞掉仍在队列里的失焦提交。"""
        self._released = True

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
        # 工具栏下拉框弹出抢焦点不算"离开输入":跳过提交,
        # 用户才能边输入边换颜色/字号。
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            QTimer.singleShot(0, self._commit_from_focus_out)

    def _commit_from_focus_out(self) -> None:
        # 提交/丢弃后 hide() 会再触发一次失焦;此时 C++ 对象可能已进入
        # deleteLater 队列,访问信号会抛 RuntimeError,只能靠纯 Python 标记拦截。
        if not self._released:
            self.commit_requested.emit()


ACTION_LABELS = {"copy": "复制", "save": "保存", "pin": "钉住"}

# Tools that create an annotation by dragging out a rectangle-like region.
DRAG_SHAPE_TOOLS = {"arrow", "rect", "ellipse", "mosaic"}

TOOL_SHORTCUTS: dict[int, str] = {
    Qt.Key.Key_V: "select",
    Qt.Key.Key_1: "select",
    Qt.Key.Key_P: "pen",
    Qt.Key.Key_2: "pen",
    Qt.Key.Key_G: "highlight",
    Qt.Key.Key_9: "highlight",
    Qt.Key.Key_A: "arrow",
    Qt.Key.Key_3: "arrow",
    Qt.Key.Key_R: "rect",
    Qt.Key.Key_4: "rect",
    Qt.Key.Key_O: "ellipse",
    Qt.Key.Key_5: "ellipse",
    Qt.Key.Key_N: "number",
    Qt.Key.Key_6: "number",
    Qt.Key.Key_M: "mosaic",
    Qt.Key.Key_7: "mosaic",
    Qt.Key.Key_T: "text",
    Qt.Key.Key_8: "text",
}

# 荧光笔:半透明 + 加粗的画笔,高亮文字而不遮盖内容。
HIGHLIGHT_ALPHA = 102
HIGHLIGHT_WIDTH_FACTOR = 3.0


def _color_swatch(color: str) -> QIcon:
    pixmap = QPixmap(14, 14)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(QPen(QColor("#8b949e"), 1))
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(1, 1, 12, 12, 3, 3)
    painter.end()
    return QIcon(pixmap)


class CaptureOverlay(QWidget):
    completed = Signal(object, str, object)
    # OCR 专用的干净渲染(剔除覆盖物、保留马赛克);completed 仍携带
    # 完整标注图,托盘"保存最近一张"的语义不受影响。
    ocr_ready = Signal(object)
    cancelled = Signal()

    # 进程内记忆:上次完成的选区(R 键恢复)与上次使用的标注样式。
    _last_finished_selection: QRectF | None = None
    _remembered_style: dict[str, object] = {}

    def __init__(
        self,
        desktop: CapturedDesktop,
        action: str,
        window_targets: list[WindowTarget] | None = None,
    ) -> None:
        super().__init__(None)
        self.desktop = desktop
        self.action = action
        self._backdrop: QPixmap | None = None
        self._backdrop_key: tuple[int, int, float] | None = None
        self.state = "selecting"
        self.selection = QRectF()
        self.drag_origin: QPointF | None = None
        self.annotations: list[Annotation] = []
        self.active_path: QPainterPath | None = None
        self._history: list[list[Annotation]] = []
        self._redo_stack: list[list[Annotation]] = []
        self._shape_origin: QPointF | None = None
        self._active_shape: Annotation | None = None
        self._pointer_pos: QPointF | None = None
        self._copied_color_notice: str | None = None
        self._style_notice: str | None = None
        self._pen_last_point: QPointF | None = None
        self._pen_press_point: QPointF | None = None
        self._pen_moved = False
        self._help_visible = False
        self._suppress_next_dblclick = False
        self._dblclick_finish_candidate = False
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
            "QToolButton, QPushButton { padding: 5px 7px; border-radius: 4px; "
            "border: 1px solid transparent; background: #3b4250; } "
            "QToolButton:checked { background: #1677ff; } "
            "QPushButton:hover, QToolButton:hover { background: #536078; } "
            "QPushButton:focus, QToolButton:focus, QComboBox:focus { "
            "border: 1px solid #8ec5ff; } "
            "QPushButton:disabled, QToolButton:disabled, QComboBox:disabled { "
            "color: #8b949e; background: #303641; } "
            "QComboBox { background: #3b4250; padding: 4px; border: 0; } "
            "QFrame[frameShape=\"5\"] { color: #596273; }"
        )
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(4)

        tool_group = QButtonGroup(toolbar)
        tool_group.setExclusive(True)
        self._tool_buttons: dict[str, QToolButton] = {}

        def add_tool(name: str, label: str, tooltip: str) -> QToolButton:
            button = QToolButton(toolbar)
            button.setText(label)
            button.setCheckable(True)
            button.setToolTip(tooltip)
            tool_group.addButton(button)
            layout.addWidget(button)
            self._tool_buttons[name] = button
            return button

        self.select_button = add_tool(
            "select",
            "选择",
            "选择/移动选区（V）；方向键微调位置，Ctrl+方向键调整大小，"
            "加 Shift 每次 10px",
        )
        self.pen_button = add_tool("pen", "画笔", "自由画笔（P）")
        self.highlight_button = add_tool(
            "highlight", "荧光", "荧光笔:半透明高亮,不遮挡文字（G）"
        )
        self.arrow_button = add_tool("arrow", "箭头", "拖动绘制箭头（A）")
        self.rect_button = add_tool("rect", "矩形", "拖动绘制矩形框（R）")
        self.ellipse_button = add_tool("ellipse", "椭圆", "拖动绘制椭圆框（O）")
        self.number_button = add_tool("number", "序号", "单击放置自增序号标记（N）")
        self.mosaic_button = add_tool("mosaic", "马赛克", "拖动打码遮盖隐私（M）")
        self.text_button = add_tool("text", "文字", "单击输入文字（T）")
        self.select_button.setChecked(True)

        layout.addWidget(self._separator(toolbar))

        self.color_combo = QComboBox(toolbar)
        self.color_combo.setToolTip("标注颜色")
        for label, color in [
            ("红", "#ff3b30"),
            ("橙", "#ff9500"),
            ("黄", "#ffd60a"),
            ("绿", "#34c759"),
            ("蓝", "#0a84ff"),
            ("紫", "#af52de"),
            ("黑", "#111111"),
            ("白", "#ffffff"),
        ]:
            self.color_combo.addItem(_color_swatch(color), label, color)

        self.width_combo = QComboBox(toolbar)
        self.width_combo.setToolTip("线条粗细")
        for width in (2, 4, 6, 8):
            self.width_combo.addItem(f"{width}px", width)
        self.width_combo.setCurrentIndex(1)

        self.font_combo = QComboBox(toolbar)
        self.font_combo.setToolTip("文字字号")
        for size in (16, 24, 32, 48):
            self.font_combo.addItem(f"{size}px", size)
        self.font_combo.setCurrentIndex(1)
        # QComboBox 自带的滚轮是"向上选上一项"(数值变小),与画布滚轮
        # 方向相反;接管成统一的"向上加大",并走同一套浮签提示。
        self.width_combo.installEventFilter(self)
        self.font_combo.installEventFilter(self)

        layout.addWidget(self.color_combo)
        layout.addWidget(self.width_combo)
        layout.addWidget(self.font_combo)
        layout.addWidget(self._separator(toolbar))

        self.undo_button = QPushButton("撤销", toolbar)
        self.undo_button.setToolTip("撤销上一步标注（Ctrl+Z）")
        self.redo_button = QPushButton("重做", toolbar)
        self.redo_button.setToolTip("重做已撤销的标注（Ctrl+Y）")
        self.clear_button = QPushButton("清空", toolbar)
        self.clear_button.setToolTip("清空全部标注")
        cancel_button = QPushButton("取消", toolbar)
        cancel_button.setToolTip("取消截图（Esc / 右键）")

        default_action_text = ACTION_LABELS.get(self.action, "复制")
        shortcut_hint = QLabel(f"双击/Enter：{default_action_text}", toolbar)
        shortcut_hint.setStyleSheet("color: #c9d1d9; padding: 0 3px;")

        self.ocr_button = QPushButton("识别", toolbar)
        self.pin_button = QPushButton("钉住", toolbar)
        self.copy_button = QPushButton("复制", toolbar)
        self.save_button = QPushButton("保存", toolbar)
        primary_button = {
            "copy": self.copy_button,
            "save": self.save_button,
            "pin": self.pin_button,
        }.get(self.action, self.copy_button)
        primary_button.setStyleSheet(
            "QPushButton { background: #1677ff; font-weight: 600; } "
            "QPushButton:hover { background: #4096ff; }"
        )
        self.pin_button.setToolTip("钉住为置顶贴图（Ctrl+D）")
        self.copy_button.setToolTip("复制到剪贴板（Ctrl+C）")
        self.save_button.setToolTip(
            "保存到默认目录（Ctrl+S）；另存为…（Ctrl+Shift+S）"
        )
        from .ocr import is_available as ocr_available

        if ocr_available():
            self.ocr_button.setToolTip("识别选区文字并弹出结果面板（W）")
        else:
            self.ocr_button.setEnabled(False)
            self.ocr_button.setToolTip(
                "系统缺少可用的 OCR 语言,请在 Windows 设置中添加中文/英文语言包"
            )

        layout.addWidget(self.undo_button)
        layout.addWidget(self.redo_button)
        layout.addWidget(self.clear_button)
        layout.addWidget(cancel_button)
        layout.addWidget(shortcut_hint)
        layout.addWidget(self.ocr_button)
        layout.addWidget(self.pin_button)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.save_button)

        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.clear_button.clicked.connect(self.clear_annotations)
        cancel_button.clicked.connect(self.cancel)
        self.ocr_button.clicked.connect(lambda: self.finish("ocr"))
        self.pin_button.clicked.connect(lambda: self.finish("pin"))
        self.copy_button.clicked.connect(lambda: self.finish("copy"))
        self.save_button.clicked.connect(lambda: self.finish("save"))
        for button in self._tool_buttons.values():
            button.toggled.connect(self._update_cursor)
            button.toggled.connect(self._sync_tool_options)
        # 文字输入中改颜色/字号要实时应用到输入框,而不是把文字提交掉;
        # 工具栏控件一律不抢焦点,点它们时输入框保持编辑状态。
        self.color_combo.currentIndexChanged.connect(
            lambda _index: self._apply_style_to_text_editor()
        )
        self.font_combo.currentIndexChanged.connect(
            lambda _index: self._apply_style_to_text_editor()
        )
        for child in toolbar.findChildren(QWidget):
            child.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._apply_remembered_style()
        self._sync_tool_options()
        self._sync_annotation_actions()
        return toolbar

    @staticmethod
    def _separator(parent: QWidget) -> QFrame:
        line = QFrame(parent)
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        return line

    def _current_tool(self) -> str:
        for name, button in self._tool_buttons.items():
            if button.isChecked():
                return name
        return "select"

    def set_tool(self, name: str) -> None:
        button = self._tool_buttons.get(name)
        if button is not None:
            button.setChecked(True)

    def start(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.grabKeyboard()
        local = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(local):
            self._pointer_pos = QPointF(local)

    def _restore_last_selection(self) -> None:
        last = CaptureOverlay._last_finished_selection
        if last is None:
            return
        restored = QRectF(last).intersected(
            QRectF(0.0, 0.0, float(self.width()), float(self.height()))
        )
        if restored.width() < 2 or restored.height() < 2:
            return
        if self.state == "reselecting":
            self._reset_annotations()
        self._discard_reselection_backup()
        self.drag_origin = None
        self._pressed_window = None
        self.selection = restored
        self._accept_selection()

    def select_all(self) -> None:
        self._discard_inline_text()
        self.drag_origin = None
        self._pressed_window = None
        self._shape_origin = None
        self._active_shape = None
        self._selection_transform = None
        self._discard_reselection_backup()
        self.selection = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
        self._accept_selection()

    def _backdrop_pixmap(self) -> QPixmap:
        """桌面底图按窗口分辨率预缩放并缓存。

        paintEvent 每次鼠标移动都会全屏重绘;直接 drawImage 意味着
        每帧把整张(可能是 4K)截图平滑缩放一遍。缓存后重绘只剩纯拷贝。
        """
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if self._backdrop is None or self._backdrop_key != key:
            # ceil 与 capture_virtual_desktop 建图一致:DPR 匹配时尺寸恒相等,
            # 直接跳过 scaled(),分数缩放(150%/175%)下也不会重采样。
            target_width = max(1, math.ceil(self.width() * dpr))
            target_height = max(1, math.ceil(self.height() * dpr))
            image = self.desktop.image
            if (image.width(), image.height()) != (target_width, target_height):
                image = image.scaled(
                    target_width,
                    target_height,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(dpr)
            self._backdrop = pixmap
            self._backdrop_key = key
        return self._backdrop

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # 点定位重载:pixmap 自带 DPR 与 painter 相抵,走真正的 1:1 快速
        # 拷贝路径;右/下边缘至多 1 设备像素的溢出会被窗口裁掉,不可见。
        painter.drawPixmap(0, 0, self._backdrop_pixmap())
        painter.fillRect(self.rect(), QColor(0, 0, 0, 115))

        preview_rect = QRectF(self.selection)
        if preview_rect.isEmpty() and self._hovered_window is not None:
            preview_rect = QRectF(self._hovered_window.rect)

        if self.selection.isEmpty():
            self._draw_selection_hint(painter)
        if not preview_rect.isEmpty():
            painter.save()
            painter.setClipRect(preview_rect)
            painter.drawPixmap(0, 0, self._backdrop_pixmap())
            if not self.selection.isEmpty():
                draw_annotations(
                    painter,
                    self.annotations,
                    self._active_annotation(),
                    source=self.desktop.image,
                    source_scale=self.desktop.render_scale,
                )
            painter.restore()
            border = QPen(QColor("#58a6ff"), 1.5, Qt.PenStyle.SolidLine)
            painter.setPen(border)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(preview_rect)
            self._draw_size_label(painter, preview_rect)
            if self.selection.isEmpty():
                self._draw_window_title_label(painter, preview_rect)
            if self.state == "editing" and not self.selection.isEmpty():
                self._draw_resize_handles(painter)
        if self.state in {"selecting", "reselecting"} or (
            self._selection_transform is not None
            and self._selection_transform != "move"
        ):
            self._draw_magnifier(painter)
        if self.state == "editing" and self._style_notice:
            self._draw_style_notice(painter)
        if self._help_visible:
            self._draw_help_panel(painter)
        painter.end()

    def _draw_style_notice(self, painter: QPainter) -> None:
        """滚轮调样式时在光标旁短暂显示当前数值。"""
        anchor = self._pointer_pos or self.selection.center()
        metrics = painter.fontMetrics()
        text = self._style_notice or ""
        width = metrics.horizontalAdvance(text) + 16
        height = metrics.height() + 8
        x = min(max(4.0, anchor.x() + 16), self.width() - width - 4.0)
        y = min(max(4.0, anchor.y() + 16), self.height() - height - 4.0)
        rect = QRectF(x, y, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 23, 28, 215))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor("white"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    _HELP_ROWS = (
        ("单击窗口 / 拖动", "吸附选择 / 自由框选(Shift 正方形)"),
        ("Ctrl+A / R", "全屏 / 恢复上次选区"),
        ("方向键 / Ctrl+方向键", "移动选区 / 调整大小(加 Shift ×10)"),
        ("V P G A R O", "选择 · 画笔 · 荧光 · 箭头 · 矩形 · 椭圆"),
        ("N M T", "序号 · 马赛克 · 文字(数字键同效)"),
        ("W", "识别选区文字(OCR)"),
        ("滚轮", "调画笔粗细 / 文字字号"),
        ("Shift 拖动", "正方形 / 正圆 / 45° 箭头"),
        ("Ctrl+Z / Ctrl+Y", "撤销 / 重做"),
        ("双击 / Enter", "完成默认动作"),
        ("Ctrl+C / S / D", "复制 / 保存 / 钉住"),
        ("Ctrl+Shift+S", "另存为(自选路径)"),
        ("C", "框选时复制光标处颜色值"),
        ("右键 / Esc", "逐级返回;拖拽中只取消当前一笔"),
    )

    def _draw_help_panel(self, painter: QPainter) -> None:
        metrics = painter.fontMetrics()
        key_w = max(
            metrics.horizontalAdvance(key) for key, _ in self._HELP_ROWS
        )
        desc_w = max(
            metrics.horizontalAdvance(desc) for _, desc in self._HELP_ROWS
        )
        row_h = metrics.height() + 8
        pad = 18
        gap = 24
        title_h = row_h + 10
        width = pad * 2 + key_w + gap + desc_w
        height = pad * 2 + title_h + row_h * len(self._HELP_ROWS)
        rect = QRectF(
            (self.width() - width) / 2.0,
            max(8.0, (self.height() - height) / 2.0),
            width,
            height,
        )
        painter.setPen(QPen(QColor("#58a6ff"), 1.0))
        painter.setBrush(QColor(16, 19, 24, 242))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor("#8ec5ff"))
        painter.drawText(
            QRectF(rect.left(), rect.top() + pad, rect.width(), row_h),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "快捷键一览(F1 或点击关闭)",
        )
        y = rect.top() + pad + title_h
        for key, desc in self._HELP_ROWS:
            painter.setPen(QColor("#f0b64c"))
            painter.drawText(
                QRectF(rect.left() + pad, y, key_w, row_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                key,
            )
            painter.setPen(QColor("white"))
            painter.drawText(
                QRectF(rect.left() + pad + key_w + gap, y, desc_w, row_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                desc,
            )
            y += row_h

    def _physical_rect_size(self, rect: QRectF) -> tuple[int, int]:
        """与 render_selection 相同的取整方式,保证标签数字 = 导出 PNG 像素。"""
        scale = self.desktop.render_scale
        image = self.desktop.image
        left = max(0, math.floor(rect.left() * scale))
        top = max(0, math.floor(rect.top() * scale))
        right = min(image.width(), math.ceil(rect.right() * scale))
        bottom = min(image.height(), math.ceil(rect.bottom() * scale))
        return max(0, right - left), max(0, bottom - top)

    def _draw_size_label(self, painter: QPainter, rect: QRectF) -> None:
        width, height = self._physical_rect_size(rect)
        text = f"{width} × {height}"
        metrics = painter.fontMetrics()
        label_width = metrics.horizontalAdvance(text) + 16.0
        label_top = rect.top() - 26.0
        if label_top < 4.0:
            # 选区贴住屏幕顶端时,把标签挪进选区内,避免被裁掉。
            label_top = rect.top() + 4.0
        label_rect = QRectF(
            max(0.0, min(rect.left(), self.width() - label_width)),
            label_top,
            label_width,
            22.0,
        )
        if self.toolbar.isVisible() and QRectF(
            self.toolbar.geometry()
        ).intersects(label_rect):
            # 工具栏被挪到选区上方时会盖住标签,把标签挪进选区内部。
            label_rect.moveTop(rect.top() + 4.0)
            label_rect.moveLeft(
                max(0.0, min(rect.left() + 4.0, self.width() - label_width))
            )
        painter.fillRect(label_rect, QColor(20, 23, 28, 215))
        painter.setPen(QColor("white"))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_window_title_label(self, painter: QPainter, rect: QRectF) -> None:
        target = self._hovered_window
        if target is None or not target.title:
            return
        metrics = painter.fontMetrics()
        text = metrics.elidedText(
            target.title,
            Qt.TextElideMode.ElideRight,
            max(60, round(rect.width()) - 28),
        )
        label_width = metrics.horizontalAdvance(text) + 16.0
        label_rect = QRectF(
            max(0.0, min(rect.left() + 4.0, self.width() - label_width)),
            max(0.0, rect.top() + 4.0),
            label_width,
            22.0,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 23, 28, 215))
        painter.drawRoundedRect(label_rect, 4, 4)
        painter.setPen(QColor("white"))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_selection_hint(self, painter: QPainter) -> None:
        parts = ["单击选择窗口", "拖动框选(Shift 正方形)", "Ctrl+A 全屏"]
        if CaptureOverlay._last_finished_selection is not None:
            parts.append("R 上次选区")
        parts += ["C 取色", "右键/Esc 取消"]
        text = " · ".join(parts)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 32
        height = 36
        rect = QRectF((self.width() - width) / 2, 20, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 23, 28, 220))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QColor("white"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _color_at_pointer(self) -> QColor | None:
        point = self._pointer_pos
        if point is None:
            return None
        scale = self.desktop.render_scale
        image = self.desktop.image
        px = min(max(round(point.x() * scale), 0), image.width() - 1)
        py = min(max(round(point.y() * scale), 0), image.height() - 1)
        return image.pixelColor(px, py)

    def _draw_magnifier(self, painter: QPainter) -> None:
        point = self._pointer_pos
        if point is None:
            return
        scale = self.desktop.render_scale
        image = self.desktop.image

        source_w, source_h = 25, 19
        zoom = 6
        panel_w = source_w * zoom
        panel_h = source_h * zoom
        phys_w = max(3, round(source_w * scale))
        phys_h = max(3, round(source_h * scale))
        cx = round(point.x() * scale)
        cy = round(point.y() * scale)
        source_rect = QRect(cx - phys_w // 2, cy - phys_h // 2, phys_w, phys_h)
        region = image.copy(source_rect)
        zoomed = region.scaled(
            QSize(panel_w, panel_h),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

        color = self._color_at_pointer()
        hex_text = color.name().upper() if color is not None else "--"
        rgb_text = (
            f"RGB {color.red()}, {color.green()}, {color.blue()}"
            if color is not None
            else "RGB --"
        )
        info_lines = [f"({round(point.x())}, {round(point.y())})   {hex_text}"]
        adjusting_selection = self.drag_origin is not None or (
            self._selection_transform is not None
            and self._selection_transform != "move"
        )
        if adjusting_selection and not self.selection.isEmpty():
            width_px, height_px = self._physical_rect_size(self.selection)
            info_lines[0] = f"{width_px} × {height_px}   {hex_text}"
        info_lines.append(rgb_text)
        info_lines.append(self._copied_color_notice or "C 复制颜色值")
        info_h = 58
        total_h = panel_h + info_h

        offset = 24
        x = point.x() + offset
        y = point.y() + offset
        if x + panel_w + 8 > self.width():
            x = point.x() - offset - panel_w
        if y + total_h + 8 > self.height():
            y = point.y() - offset - total_h
        x = max(4.0, min(x, self.width() - panel_w - 4.0))
        y = max(4.0, min(y, self.height() - total_h - 4.0))
        panel_rect = QRectF(x, y, panel_w, panel_h)

        painter.drawImage(panel_rect, zoomed)
        crosshair = QPen(QColor(88, 166, 255, 170), 1.0)
        painter.setPen(crosshair)
        painter.drawLine(
            QPointF(panel_rect.left(), panel_rect.center().y()),
            QPointF(panel_rect.right(), panel_rect.center().y()),
        )
        painter.drawLine(
            QPointF(panel_rect.center().x(), panel_rect.top()),
            QPointF(panel_rect.center().x(), panel_rect.bottom()),
        )
        painter.setPen(QPen(QColor("#596273"), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(panel_rect)

        info_rect = QRectF(x, y + panel_h, panel_w, info_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 23, 28, 235))
        painter.drawRect(info_rect)
        line_h = info_h / 3.0
        line_colors = (QColor("white"), QColor("white"), QColor("#8ec5ff"))
        for index, (line, line_color) in enumerate(zip(info_lines, line_colors)):
            painter.setPen(line_color)
            painter.drawText(
                QRectF(x + 6, y + panel_h + index * line_h, panel_w - 12, line_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                line,
            )

    def _draw_resize_handles(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#1677ff"), 1.0))
        painter.setBrush(QColor("white"))
        for point in self._resize_handle_points().values():
            painter.drawRect(QRectF(point.x() - 3, point.y() - 3, 6, 6))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._handle_right_press()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._help_visible:
            self._help_visible = False
            # 关面板的这次点击不该触达底层;它若是双击的前半段,
            # 后半段(dblclick 事件)也要一并吞掉,否则会直接完成截图。
            self._suppress_next_dblclick = True
            self.update()
            event.accept()
            return
        self._suppress_next_dblclick = False
        point = event.position()
        if self._is_on_toolbar(point):
            # 工具栏的内边距/分隔条/提示文字不吃鼠标事件,
            # 会穿透到遮罩触发重选区,一次误点就清空全部标注。
            event.accept()
            return
        self._pointer_pos = QPointF(self._clamp_point(point))
        if self.state in {"selecting", "reselecting"}:
            self.drag_origin = self._clamp_point(point)
            self._pressed_window = self._window_target_at(point)
            self.selection = QRectF(self.drag_origin, self.drag_origin)
            self.toolbar.hide()
            self.update()
            return

        # 双击完成候选转发来的按下要跳过缩放把手判定:手柄命中区向选区
        # 内延伸 7px,小选区里几乎无处双击,不能让它吞掉完成手势。
        resize_edge = (
            None
            if self._dblclick_finish_candidate
            else self._resize_edge_at(point)
        )
        if resize_edge is not None:
            self._begin_selection_transform(resize_edge, point)
            return
        if not self.selection.contains(point):
            self._begin_reselection(point)
            return
        tool = self._current_tool()
        if tool == "select":
            self._begin_selection_transform("move", point)
            return
        if tool == "text":
            self._begin_text(point)
            return
        if tool == "number":
            self._commit_inline_text()
            self._push_history()
            self.annotations.append(
                NumberAnnotation(
                    QPointF(point),
                    self._next_number(),
                    self._current_color(),
                )
            )
            self._sync_annotation_actions()
            self.update()
            return
        if tool in DRAG_SHAPE_TOOLS:
            self._commit_inline_text()
            self._shape_origin = QPointF(point)
            self._active_shape = None
            return
        self.active_path = QPainterPath(point)
        self._pen_last_point = QPointF(point)
        self._pen_press_point = QPointF(point)
        self._pen_moved = False
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        point = self._clamp_point(event.position())
        self._pointer_pos = QPointF(point)
        if self._selection_transform is not None:
            self._update_selection_transform(point)
            return
        if self.state == "selecting" and self.drag_origin is None:
            self._set_hovered_window(self._window_target_at(point))
            self.update()
            return
        if (
            self.state in {"selecting", "reselecting"}
            and self.drag_origin is not None
        ):
            end = point
            if self._shift_pressed():
                end = self._constrain_square(self.drag_origin, point)
            self.selection = (
                QRectF(self.drag_origin, end)
                .normalized()
                .intersected(QRectF(self.rect()))
            )
            self.update()
            return
        if self._shape_origin is not None:
            self._active_shape = self._build_shape(self._shape_origin, point)
            self.update()
            return
        if self.active_path is not None:
            # 二次贝塞尔过中点平滑:控制点取上一实际点,笔迹不再有折角。
            last = self._pen_last_point or QPointF(point)
            mid = QPointF(
                (last.x() + point.x()) / 2.0,
                (last.y() + point.y()) / 2.0,
            )
            self.active_path.quadTo(last, mid)
            self._pen_last_point = QPointF(point)
            if not self._pen_moved:
                # 与形状工具一致的 3px 阈值:双击自带的 1-3px 抖动
                # 不算"拖动",否则真实双击时灵时不灵还留下杂点。
                origin = self._pen_press_point or last
                if (
                    math.hypot(
                        point.x() - origin.x(), point.y() - origin.y()
                    )
                    >= 3.0
                ):
                    self._pen_moved = True
            self.update()
            return
        if self.state == "editing":
            self._update_editing_cursor(point)
        if self.state == "reselecting":
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # 一次性消费双击完成候选:只有本次释放确实没画出内容才生效。
        dblclick_finish = self._dblclick_finish_candidate
        self._dblclick_finish_candidate = False
        if self._selection_transform is not None:
            if self._selection_transform == "move":
                dx = self.selection.left() - self._transform_origin_selection.left()
                dy = self.selection.top() - self._transform_origin_selection.top()
                self._translate_history(dx, dy)
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
                        self._archive_annotations_for_reselect()
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
                self._archive_annotations_for_reselect()
                self._discard_reselection_backup()
            self._pressed_window = None
            self._accept_selection()
            return
        if self._shape_origin is not None:
            release_point = self._clamp_point(event.position())
            # "没拖动"按真实位移判定,不能拿形状有效性冒充:
            # 50×2px 的细长拖拽同样返回 None,但绝不是双击。
            dragged = (
                math.hypot(
                    release_point.x() - self._shape_origin.x(),
                    release_point.y() - self._shape_origin.y(),
                )
                >= 3.0
            )
            shape = self._build_shape(self._shape_origin, release_point)
            self._shape_origin = None
            self._active_shape = None
            if shape is not None:
                self._push_history()
                self.annotations.append(shape)
            elif dblclick_finish and not dragged:
                # 双击且确实没拖动:按默认动作完成截图。
                self.finish()
                return
            self._sync_annotation_actions()
            self.update()
            return
        if self.active_path is not None:
            if dblclick_finish and not self._pen_moved:
                # 双击没有落笔画线(3px 抖动容差内):按默认动作完成。
                self.active_path = None
                self._pen_last_point = None
                self._pen_press_point = None
                self.finish()
                return
            if self._pen_moved:
                # 平滑段终点停在中点,补一段到真实抬笔位置。
                self.active_path.lineTo(self._clamp_point(event.position()))
            # 亚阈值的抖动路径不提交:免得单击/双击留下肉眼难辨的杂点
            # 被烧进导出图,还占一格撤销历史。
            if self._pen_moved and self.active_path.elementCount() > 1:
                self._push_history()
                color, width = self._pen_style()
                self.annotations.append(
                    PenAnnotation(QPainterPath(self.active_path), color, width)
                )
            self.active_path = None
            self._pen_last_point = None
            self._pen_press_point = None
            self._pen_moved = False
            self._sync_annotation_actions()
            self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._suppress_next_dblclick:
            self._suppress_next_dblclick = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_on_toolbar(event.position()):
                event.accept()
                return
            if self.state == "editing" and self.selection.contains(
                event.position()
            ):
                tool = self._current_tool()
                if tool == "select":
                    self.finish()
                else:
                    # 快速连击是标注操作(比如连放序号),把双击转成普通
                    # 按下,让第二个标注正常落下。对画笔/形状类工具再多
                    # 一层判断:若这次双击最终没画出内容(释放时无拖动),
                    # 就视为"双击完成",执行默认动作——默认工具是画笔,
                    # 用户习惯的"双击直接复制/保存"必须继续可用。
                    if tool in {"pen", "highlight"} | DRAG_SHAPE_TOOLS:
                        self._dblclick_finish_candidate = True
                    self.mousePressEvent(event)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _is_on_toolbar(self, point: QPointF) -> bool:
        return self.toolbar.isVisible() and QRectF(
            self.toolbar.geometry()
        ).contains(point)

    def _handle_right_press(self) -> None:
        """右键分级回退:帮助 → 文字框 → 当前拖拽 → 编辑态回框选 → 退出。"""
        if self._resolved:
            return
        if self._help_visible:
            self._help_visible = False
            self.update()
            return
        if self._text_editor is not None:
            self._discard_inline_text()
            return
        if self.state == "reselecting":
            self.drag_origin = None
            self._pressed_window = None
            if self._selection_before_reselect is not None:
                self.selection = QRectF(self._selection_before_reselect)
                self.annotations = list(self._annotations_before_reselect or [])
                self.state = "editing"
                self._discard_reselection_backup()
                self._position_toolbar()
                self.toolbar.show()
                self._update_cursor()
            else:
                self.state = "selecting"
                self.selection = QRectF()
                self._discard_reselection_backup()
            self.update()
            return
        if self._cancel_active_gesture():
            return
        if self.state == "editing":
            self._back_to_selecting()
            return
        if self.drag_origin is not None:
            self.drag_origin = None
            self._pressed_window = None
            self.selection = QRectF()
            self.update()
            return
        self.cancel()

    def _cancel_active_gesture(self) -> bool:
        """取消进行中的一笔标注或选区变换;有可取消的手势时返回 True。"""
        if (
            self._shape_origin is not None
            or self._active_shape is not None
            or self.active_path is not None
        ):
            # 只丢弃拖到一半的这一笔,已有标注不动。
            self._shape_origin = None
            self._active_shape = None
            self.active_path = None
            self._pen_last_point = None
            self._pen_press_point = None
            self._pen_moved = False
            self.update()
            return True
        if self._selection_transform is not None:
            # 还原移动/缩放开始前的选区和标注位置。
            self.selection = QRectF(self._transform_origin_selection)
            self.annotations = list(self._transform_origin_annotations)
            self._selection_transform = None
            self._transform_origin_annotations = []
            self._position_toolbar()
            self.toolbar.show()
            self.update()
            return True
        return False

    def _back_to_selecting(self) -> None:
        self._discard_inline_text()
        self.drag_origin = None
        self._pressed_window = None
        self._shape_origin = None
        self._active_shape = None
        self.active_path = None
        self._pen_last_point = None
        self._pen_press_point = None
        self._pen_moved = False
        self._selection_transform = None
        self._discard_reselection_backup()
        self._reset_annotations()
        self.selection = QRectF()
        self.state = "selecting"
        self.toolbar.hide()
        self._sync_annotation_actions()
        self.setCursor(Qt.CursorShape.CrossCursor)
        if self._pointer_pos is not None:
            self._set_hovered_window(self._window_target_at(self._pointer_pos))
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in {Qt.Key.Key_F1, Qt.Key.Key_H}
            and not event.modifiers()
            and self._text_editor is None
        ):
            self._help_visible = not self._help_visible
            self.update()
            return
        if self._help_visible:
            # 帮助面板打开时,任意按键只负责收起面板,不再继续执行:
            # 否则 Enter/Ctrl+C 这类"关闭手势"会直接把截图完成掉。
            self._help_visible = False
            self.update()
            return
        if event.key() == Qt.Key.Key_Escape:
            # 拖到一半时 Esc 只取消当前手势,和右键的分级语义一致;
            # 没有进行中的手势才退出整个截图。
            if self._cancel_active_gesture():
                return
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
            if event.key() == Qt.Key.Key_A:
                self.select_all()
                return
            if (
                event.key() in {Qt.Key.Key_Z, Qt.Key.Key_Y}
                and self.state == "reselecting"
            ):
                # 重选拖拽期间撤销/重做会与右键还原备份打架,
                # 造成撤销链断裂,这里直接吞掉。
                return
            if event.key() == Qt.Key.Key_Z:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.redo()
                else:
                    self.undo()
                return
            if event.key() == Qt.Key.Key_Y:
                self.redo()
                return
            if event.key() == Qt.Key.Key_C and self.state == "editing":
                self.finish("copy")
                return
            if event.key() == Qt.Key.Key_S and self.state == "editing":
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.finish("save_as")
                else:
                    self.finish("save")
                return
            if event.key() == Qt.Key.Key_D and self.state == "editing":
                self.finish("pin")
                return
        if (
            self.state in {"selecting", "reselecting"}
            and event.key() == Qt.Key.Key_C
            and not event.modifiers()
        ):
            self._copy_pointer_color()
            return
        if (
            self.state in {"selecting", "reselecting"}
            and event.key() == Qt.Key.Key_R
            and not event.modifiers()
            and self.drag_origin is None
        ):
            self._restore_last_selection()
            return
        if self.state == "editing" and self._text_editor is None:
            direction_by_key = {
                Qt.Key.Key_Left: (-1.0, 0.0),
                Qt.Key.Key_Right: (1.0, 0.0),
                Qt.Key.Key_Up: (0.0, -1.0),
                Qt.Key.Key_Down: (0.0, 1.0),
            }
            direction = direction_by_key.get(event.key())
            if direction is not None:
                distance = (
                    10.0
                    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                    else 1.0
                )
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._resize_selection_by(
                        direction[0] * distance, direction[1] * distance
                    )
                else:
                    self._nudge_selection(
                        direction[0] * distance, direction[1] * distance
                    )
                event.accept()
                return
            if not event.modifiers() and event.key() == Qt.Key.Key_W:
                # 与工具栏按钮同一道门:OCR 不可用时绝不能 finish,
                # 否则截图会话连同标注被白白销毁,只换来一条报错。
                if self.ocr_button.isEnabled():
                    self.finish("ocr")
                else:
                    self._style_notice = "系统缺少 OCR 语言,无法识别文字"
                    QTimer.singleShot(1600, self._clear_style_notice)
                    self.update()
                event.accept()
                return
            if not event.modifiers() and event.key() in TOOL_SHORTCUTS:
                self.set_tool(TOOL_SHORTCUTS[event.key()])
                event.accept()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._resolved:
            self._resolved = True
            self.cancelled.emit()
        self.releaseKeyboard()
        event.accept()

    def _copy_pointer_color(self) -> None:
        color = self._color_at_pointer()
        if color is None:
            return
        hex_text = color.name().upper()
        QGuiApplication.clipboard().setText(hex_text)
        self._copied_color_notice = f"已复制 {hex_text}"
        QTimer.singleShot(1600, self._clear_color_notice)
        self.update()

    def _clear_color_notice(self) -> None:
        self._copied_color_notice = None
        if not self._resolved:
            self.update()

    def eventFilter(self, obj, event) -> bool:  # type: ignore[no-untyped-def]
        if (
            obj in (self.width_combo, self.font_combo)
            and event.type() == QEvent.Type.Wheel
        ):
            delta = event.angleDelta().y()
            if delta:
                direction = 1 if delta > 0 else -1
                combo = obj
                index = max(
                    0, min(combo.count() - 1, combo.currentIndex() + direction)
                )
                if index != combo.currentIndex():
                    combo.setCurrentIndex(index)
                label = "字号" if combo is self.font_combo else "粗细"
                unit = "" if combo is self.font_combo else "px"
                self._style_notice = f"{label} {combo.currentData()}{unit}"
                QTimer.singleShot(900, self._clear_style_notice)
                self.update()
            return True
        return super().eventFilter(obj, event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.state != "editing" or self._text_editor is not None:
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        if self._step_tool_style(1 if delta > 0 else -1):
            event.accept()
        else:
            event.ignore()

    def _step_tool_style(self, direction: int) -> bool:
        """滚轮微调当前工具的样式:画笔/箭头/形状调粗细,文字调字号。"""
        tool = self._current_tool()
        if tool == "text":
            combo, label, unit = self.font_combo, "字号", ""
        elif tool in {"pen", "highlight", "arrow", "rect", "ellipse"}:
            combo, label, unit = self.width_combo, "粗细", "px"
        else:
            return False
        index = combo.currentIndex() + direction
        index = max(0, min(combo.count() - 1, index))
        if index != combo.currentIndex():
            combo.setCurrentIndex(index)
        self._style_notice = f"{label} {combo.currentData()}{unit}"
        QTimer.singleShot(900, self._clear_style_notice)
        self.update()
        return True

    def _clear_style_notice(self) -> None:
        self._style_notice = None
        if not self._resolved:
            self.update()

    def _push_history(self) -> None:
        self._history.append(list(self.annotations))
        self._redo_stack.clear()

    def _translate_history(self, dx: float, dy: float) -> None:
        if dx == 0 and dy == 0:
            return
        self._history = [
            translated_annotations(snapshot, dx, dy) for snapshot in self._history
        ]
        self._redo_stack = [
            translated_annotations(snapshot, dx, dy) for snapshot in self._redo_stack
        ]

    def _reset_annotations(self) -> None:
        self.annotations.clear()
        self._history.clear()
        self._redo_stack.clear()

    def _archive_annotations_for_reselect(self) -> None:
        """重选生效时旧标注压进撤销栈而不是销毁:误点选区外 Ctrl+Z 可找回。"""
        if self.annotations:
            self._push_history()
            self.annotations = []

    def undo(self) -> None:
        self._commit_inline_text()
        if self._history:
            self._redo_stack.append(list(self.annotations))
            self.annotations = self._history.pop()
            self._sync_annotation_actions()
            self.update()

    def redo(self) -> None:
        self._commit_inline_text()
        if self._redo_stack:
            self._history.append(list(self.annotations))
            self.annotations = self._redo_stack.pop()
            self._sync_annotation_actions()
            self.update()

    def clear_annotations(self) -> None:
        self._discard_inline_text()
        self.active_path = None
        self._shape_origin = None
        self._active_shape = None
        if self.annotations:
            self._push_history()
            self.annotations = []
        self._sync_annotation_actions()
        self.update()

    def finish(self, action: str | None = None) -> None:
        if self._resolved or self.selection.isEmpty():
            return
        resolved_action = action or self.action
        if resolved_action not in {"copy", "save", "pin", "save_as", "ocr"}:
            return
        self._commit_inline_text()
        ocr_image: QImage | None = None
        if resolved_action == "ocr":
            # 识别用干净图:箭头/荧光/文字等覆盖物会干扰引擎。
            # 马赛克必须保留——用户打码隐藏的内容绝不能泄漏进识别结果。
            ocr_image = render_selection(
                self.desktop.image,
                self.selection,
                self.desktop.render_scale,
                [
                    command
                    for command in self.annotations
                    if isinstance(command, MosaicAnnotation)
                ],
            )
            ocr_image.setDevicePixelRatio(self.desktop.render_scale)
        image = render_selection(
            self.desktop.image,
            self.selection,
            self.desktop.render_scale,
            self.annotations,
        )
        if image.isNull():
            return
        image.setDevicePixelRatio(self.desktop.render_scale)
        global_pos = QPoint(
            self.desktop.virtual_geometry.x() + round(self.selection.left()),
            self.desktop.virtual_geometry.y() + round(self.selection.top()),
        )
        CaptureOverlay._last_finished_selection = QRectF(self.selection)
        self._store_toolbar_style()
        self._resolved = True
        self.releaseKeyboard()
        self.hide()
        if ocr_image is not None:
            self.ocr_ready.emit(ocr_image)
        self.completed.emit(image, resolved_action, global_pos)
        self.close()

    def cancel(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        self._store_toolbar_style()
        self._discard_inline_text()
        self.releaseKeyboard()
        self.hide()
        self.cancelled.emit()
        self.close()

    def _store_toolbar_style(self) -> None:
        CaptureOverlay._remembered_style = {
            "color": self.color_combo.currentData(),
            "width": self.width_combo.currentData(),
            "font": self.font_combo.currentData(),
        }

    def _apply_remembered_style(self) -> None:
        style = CaptureOverlay._remembered_style
        for combo, key in (
            (self.color_combo, "color"),
            (self.width_combo, "width"),
            (self.font_combo, "font"),
        ):
            value = style.get(key)
            if value is None:
                continue
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)

    def _pen_style(self) -> tuple[str, float]:
        """画笔/荧光笔的落笔样式:荧光笔=半透明 + 3 倍宽。"""
        color = self._current_color()
        width = float(self.width_combo.currentData())
        if self._current_tool() == "highlight":
            translucent = QColor(color)
            translucent.setAlpha(HIGHLIGHT_ALPHA)
            color = translucent.name(QColor.NameFormat.HexArgb)
            width *= HIGHLIGHT_WIDTH_FACTOR
        return color, width

    def _active_annotation(self) -> Annotation | None:
        if self.active_path is not None:
            color, width = self._pen_style()
            return PenAnnotation(self.active_path, color, width)
        return self._active_shape

    @staticmethod
    def _shift_pressed() -> bool:
        return bool(
            QGuiApplication.keyboardModifiers()
            & Qt.KeyboardModifier.ShiftModifier
        )

    @staticmethod
    def _constrain_square(origin: QPointF, point: QPointF) -> QPointF:
        dx = point.x() - origin.x()
        dy = point.y() - origin.y()
        side = max(abs(dx), abs(dy))
        return QPointF(
            origin.x() + (side if dx >= 0 else -side),
            origin.y() + (side if dy >= 0 else -side),
        )

    @staticmethod
    def _snap_angle(origin: QPointF, point: QPointF) -> QPointF:
        dx = point.x() - origin.x()
        dy = point.y() - origin.y()
        length = math.hypot(dx, dy)
        if length < 1.0:
            return point
        step = math.pi / 4.0
        angle = round(math.atan2(dy, dx) / step) * step
        return QPointF(
            origin.x() + length * math.cos(angle),
            origin.y() + length * math.sin(angle),
        )

    def _build_shape(self, origin: QPointF, point: QPointF) -> Annotation | None:
        tool = self._current_tool()
        if self._shift_pressed():
            # Shift 约束:箭头吸附 45°,框类拉正方形/正圆。
            if tool == "arrow":
                point = self._snap_angle(origin, point)
            else:
                point = self._constrain_square(origin, point)
        if tool == "arrow":
            if math.hypot(point.x() - origin.x(), point.y() - origin.y()) < 3.0:
                return None
            return ArrowAnnotation(
                QPointF(origin),
                QPointF(point),
                self._current_color(),
                float(self.width_combo.currentData()),
            )
        rect = QRectF(origin, point).normalized()
        if rect.width() < 3.0 or rect.height() < 3.0:
            return None
        if tool == "mosaic":
            # 大区域用更大的块,遮盖强度随面积自适应。
            block = min(20.0, max(8.0, min(rect.width(), rect.height()) / 20.0))
            return MosaicAnnotation(rect, block)
        if tool == "ellipse":
            return ShapeAnnotation(
                rect,
                self._current_color(),
                float(self.width_combo.currentData()),
                "ellipse",
            )
        if tool == "rect":
            return ShapeAnnotation(
                rect,
                self._current_color(),
                float(self.width_combo.currentData()),
                "rect",
            )
        return None

    def _next_number(self) -> int:
        numbers = [
            command.number
            for command in self.annotations
            if isinstance(command, NumberAnnotation)
        ]
        return (max(numbers) + 1) if numbers else 1

    def _current_color(self) -> str:
        return str(self.color_combo.currentData())

    def _begin_text(self, point: QPointF) -> None:
        self._commit_inline_text()
        width = max(80.0, min(320.0, self.selection.right() - point.x()))
        height = max(58.0, min(130.0, self.selection.bottom() - point.y()))
        width = min(width, max(40.0, self.selection.width()))
        height = min(height, max(30.0, self.selection.height()))
        # 把输入框整个收进选区,靠近右/下边缘输入的文字才不会在导出时被裁掉。
        x = max(self.selection.left(), min(point.x(), self.selection.right() - width))
        y = max(self.selection.top(), min(point.y(), self.selection.bottom() - height))
        self._text_position = QPointF(x, y)
        editor = InlineTextEdit(self)
        self._text_editor = editor
        editor.setPlaceholderText("输入文字（Ctrl+Enter 完成）")
        editor.setStyleSheet(
            f"QTextEdit {{ color: {self._current_color()}; "
            "background: rgba(20, 23, 28, 220); border: 1px solid #58a6ff; "
            "border-radius: 4px; padding: 3px; }}"
        )
        # 排版区与最终渲染共用同一原点与宽度,保证提交时文字零跳动、换行一致。
        editor.document().setDocumentMargin(0)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        font = editor.font()
        font.setFamily("Microsoft YaHei")
        font.setPixelSize(int(self.font_combo.currentData()))
        editor.setFont(font)
        editor.setGeometry(
            QRect(
                round(x),
                round(y),
                round(width),
                round(height),
            )
        )
        editor.commit_requested.connect(
            lambda current=editor: self._commit_inline_text(current)
        )
        editor.escape_requested.connect(self._discard_inline_text)
        editor.textChanged.connect(
            lambda current=editor: self._grow_text_editor(current)
        )
        editor.show()
        # 键盘抓取的优先级高于焦点控件,不释放的话输入框收不到任何按键。
        self.releaseKeyboard()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        self._sync_annotation_actions()

    def _apply_style_to_text_editor(self) -> None:
        """把当前颜色/字号实时应用到打开中的文字输入框,保持所见即所得。"""
        editor = self._text_editor
        if editor is None:
            return
        editor.setStyleSheet(
            f"QTextEdit {{ color: {self._current_color()}; "
            "background: rgba(20, 23, 28, 220); border: 1px solid #58a6ff; "
            "border-radius: 4px; padding: 3px; }}"
        )
        font = editor.font()
        font.setPixelSize(int(self.font_combo.currentData()))
        editor.setFont(font)
        self._grow_text_editor(editor)

    def _grow_text_editor(self, editor: InlineTextEdit) -> None:
        # 内容变高时输入框跟着长高,直到贴住选区底;避免内部滚动
        # 造成"输入时看到的"与"提交后渲染的"错位。
        if editor is not self._text_editor:
            return
        frame = editor.height() - editor.viewport().height()
        needed = math.ceil(editor.document().size().height()) + frame
        available = int(self.selection.bottom() - editor.y())
        new_height = min(max(editor.height(), needed), max(editor.height(), available))
        if new_height > editor.height():
            editor.resize(editor.width(), new_height)

    def _commit_inline_text(self, expected: InlineTextEdit | None = None) -> None:
        editor = self._text_editor
        if editor is None or (expected is not None and editor is not expected):
            return
        self._text_editor = None
        # 只裁尾部空白:行首空行/空格参与排版,裁掉会让文字上移,破坏所见即所得。
        text = editor.toPlainText().rstrip()
        # 用真实视口原点换算,渲染文字与输入时看到的位置、换行完全一致;
        # 再扣掉内部滚动量,长文本溢出输入框时可见行也不跳动。
        origin = editor.viewport().mapTo(editor, QPoint(0, 0))
        margin = float(editor.document().documentMargin())
        scroll = float(editor.verticalScrollBar().value())
        position = QPointF(
            self._text_position.x() + origin.x() + margin,
            self._text_position.y() + origin.y() + margin - scroll,
        )
        width = max(1.0, float(editor.viewport().width()) - 2.0 * margin)
        editor.release_editor()
        editor.hide()
        editor.deleteLater()
        if not self._resolved:
            self.grabKeyboard()
        if text:
            self._push_history()
            self.annotations.append(
                TextAnnotation(
                    position,
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
            editor.release_editor()
            editor.hide()
            editor.deleteLater()
            if not self._resolved:
                self.grabKeyboard()
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
        # 框选一确定就能直接涂画:默认切到画笔。重选区回来时保留用户
        # 显式选过的标注工具;V/1 可随时切回"选择"来拖动选区或双击完成。
        if self._current_tool() == "select":
            self.set_tool("pen")
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
        if not hasattr(self, "redo_button"):
            return
        pending = bool(
            self.active_path or self._text_editor or self._active_shape
        )
        self.undo_button.setEnabled(bool(self._history) or pending)
        self.redo_button.setEnabled(bool(self._redo_stack))
        self.clear_button.setEnabled(bool(self.annotations) or pending)

    def _sync_tool_options(self) -> None:
        tool = self._current_tool()
        self.color_combo.setEnabled(
            tool
            in {"pen", "highlight", "arrow", "rect", "ellipse", "number", "text"}
        )
        self.width_combo.setEnabled(
            tool in {"pen", "highlight", "arrow", "rect", "ellipse"}
        )
        self.font_combo.setEnabled(tool == "text")

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

    def _resize_selection_by(self, dw: float, dh: float) -> None:
        if self.selection.isEmpty():
            return
        right = min(
            float(self.width()),
            max(self.selection.left() + 2.0, self.selection.right() + dw),
        )
        bottom = min(
            float(self.height()),
            max(self.selection.top() + 2.0, self.selection.bottom() + dh),
        )
        if right == self.selection.right() and bottom == self.selection.bottom():
            return
        self.selection = QRectF(
            self.selection.topLeft(), QPointF(right, bottom)
        )
        self._position_toolbar()
        self.update()

    def _nudge_selection(self, dx: float, dy: float) -> None:
        if self.selection.isEmpty():
            return
        dx = max(-self.selection.left(), min(dx, self.width() - self.selection.right()))
        dy = max(-self.selection.top(), min(dy, self.height() - self.selection.bottom()))
        if dx == 0 and dy == 0:
            return
        self.selection = self.selection.translated(dx, dy)
        self.annotations = translated_annotations(self.annotations, dx, dy)
        self._translate_history(dx, dy)
        self._position_toolbar()
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
            self._current_tool() == "select" and self.selection.contains(point)
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
            return
        tool = self._current_tool()
        if tool == "select":
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif tool == "text":
            self.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
