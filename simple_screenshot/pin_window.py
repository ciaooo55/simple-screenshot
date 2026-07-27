from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QContextMenuEvent,
    QDrag,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from .ocr import OcrOutcome, OcrSpan

from .output import export_drag_copy


MIN_ZOOM = 0.2
MAX_ZOOM = 5.0
# 缩小时窗口短边不低于此值,否则小贴图会缩到无法命中、无法还原。
MIN_PIN_SIDE = 48.0
ZOOM_STEP = 1.1
MIN_OPACITY = 0.2
SNAP_DISTANCE = 12
HUD_DURATION_MS = 900


class PinWindow(QWidget):
    """置顶无边框贴图:把截图钉在屏幕上随时参考。

    拖动移动(靠近屏幕边缘自动吸附),滚轮以光标为锚点缩放,
    Ctrl+滚轮调透明度,方向键微调位置(Shift 加速),
    +/- 缩放,双击或 Ctrl+0 恢复原始大小,
    Ctrl+C 复制,Ctrl+S 保存,Esc 或右键菜单关闭。
    """

    closed = Signal(object)
    save_requested = Signal(QImage)
    save_as_requested = Signal(QImage)
    ocr_requested = Signal(QImage)
    close_all_requested = Signal()

    def __init__(
        self,
        image: QImage,
        logical_size: QSize,
        global_pos: QPoint,
    ) -> None:
        super().__init__(None)
        self._image = image
        self._base_size = QSize(
            max(1, logical_size.width()),
            max(1, logical_size.height()),
        )
        base_short = float(
            min(self._base_size.width(), self._base_size.height())
        )
        # 缩放下限:普通贴图短边不低于 MIN_PIN_SIDE,防止缩到点不中;
        # fit_to 可以为超大图临时放宽这个下限。
        self._min_zoom = min(1.0, max(MIN_ZOOM, MIN_PIN_SIDE / base_short))
        self._zoom = 1.0
        self._drag_offset: QPoint | None = None
        self._ctrl_drag_origin: QPoint | None = None
        self._click_through = False
        self._opacity_before_click_through = 1.0
        self._hud_text: str | None = None
        self._ocr_loading = False
        self._ocr_outcome: OcrOutcome | None = None
        self._ocr_anchor: int | None = None
        self._ocr_focus: int | None = None
        self._ocr_hover: int | None = None
        self._ocr_dragging = False
        self._hud_timer = QTimer(self)
        self._hud_timer.setSingleShot(True)
        self._hud_timer.setInterval(HUD_DURATION_MS)
        self._hud_timer.timeout.connect(self._clear_hud)
        # 连续滚轮缩放期间用快速插值保持跟手,停下后再平滑重绘一次。
        self._smooth_timer = QTimer(self)
        self._smooth_timer.setSingleShot(True)
        self._smooth_timer.setInterval(150)
        self._smooth_timer.timeout.connect(self.update)

        self.setWindowTitle("贴图")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.resize(self._base_size)
        self.move(global_pos)

    @property
    def image(self) -> QImage:
        return self._image

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        """调整缩放;anchor 为窗口内锚点,缩放后保持其屏幕位置不变。"""
        clamped = min(MAX_ZOOM, max(self._min_zoom, zoom))
        # 滚轮往返的连乘会留下 1e-16 级漂移;吸附回精确 1.0,
        # 否则 paintEvent 的 1:1 清晰分支永久失效,高分屏文字发虚。
        if math.isclose(clamped, 1.0, rel_tol=1e-9):
            clamped = 1.0
        if clamped == self._zoom:
            return
        old_width = max(1, self.width())
        old_height = max(1, self.height())
        new_size = QSize(
            max(1, round(self._base_size.width() * clamped)),
            max(1, round(self._base_size.height() * clamped)),
        )
        self._zoom = clamped
        position = self.pos()
        if anchor is not None:
            ratio_x = anchor.x() / old_width
            ratio_y = anchor.y() / old_height
            position = position - QPoint(
                round(ratio_x * (new_size.width() - old_width)),
                round(ratio_y * (new_size.height() - old_height)),
            )
        self._smooth_timer.start()
        self.setGeometry(QRect(position, new_size))
        self.update()

    def fit_to(self, zoom: float) -> None:
        """初始适配屏幕的缩放:必要时放宽下限,滚轮/还原后仍能回到该值。"""
        base_short = float(
            min(self._base_size.width(), self._base_size.height())
        )
        self._min_zoom = min(
            self._min_zoom, max(zoom, 1.0 / max(1.0, base_short))
        )
        self.set_zoom(zoom)

    def reset_view(self) -> None:
        self.set_zoom(1.0)
        self.setWindowOpacity(1.0)
        self._show_hud("100%")

    def copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setImage(self._image)
        self._show_hud("已复制")

    def show_save_result(self, success: bool) -> None:
        self._show_hud("已保存" if success else "保存失败,详见通知")

    @property
    def click_through(self) -> bool:
        return self._click_through

    def set_click_through(self, enabled: bool) -> None:
        """鼠标穿透:贴图变成纯参考图,点击落到下方窗口。

        穿透后本窗口收不到任何鼠标事件,恢复入口在托盘菜单
        「恢复贴图可点击」。
        """
        if enabled == self._click_through:
            return
        self._click_through = enabled
        # 改 window flag 会让窗口隐藏,必须重新 show。
        self.setWindowFlag(
            Qt.WindowType.WindowTransparentForInput, enabled
        )
        self.show()
        if enabled:
            # 压暗作视觉提示,但记住用户自己调的不透明度,恢复时还原。
            self._opacity_before_click_through = self.windowOpacity()
            self.setWindowOpacity(min(self.windowOpacity(), 0.85))
            self._show_hud("已穿透,托盘菜单可恢复")
        else:
            self.setWindowOpacity(self._opacity_before_click_through)
            self._show_hud("已恢复可点击")

    def _start_file_drag(self) -> None:
        """Ctrl+拖动:把贴图导出成临时 PNG,拖进聊天窗口/上传框直接当文件用。"""
        try:
            target = export_drag_copy(self._image)
        except Exception:
            self._show_hud("导出失败")
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setImageData(self._image)
        mime.setUrls([QUrl.fromLocalFile(str(target))])
        drag.setMimeData(mime)
        preview = QPixmap.fromImage(
            self._image.scaled(
                96,
                96,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        drag.setPixmap(preview)
        drag.exec(Qt.DropAction.CopyAction)

    def _show_hud(self, text: str) -> None:
        self._hud_text = text
        self._hud_timer.start()
        self.update()

    def _clear_hud(self) -> None:
        self._hud_text = None
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            not self._smooth_timer.isActive(),
        )
        if (
            self._zoom == 1.0
            and abs(self._image.devicePixelRatio() - self.devicePixelRatioF())
            < 0.001
        ):
            # 100% 且 DPR 匹配时按设备像素 1:1 绘制,高分屏文字不发虚。
            painter.drawImage(QPointF(0.0, 0.0), self._image)
        else:
            painter.drawImage(QRectF(self.rect()), self._image)
        if self._ocr_loading or self._ocr_outcome is not None:
            self._draw_ocr_layer(painter)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#1677ff"), 1.0))
        painter.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        if self._hud_text:
            self._draw_hud(painter, self._hud_text)
        painter.end()

    def _ocr_span_rect(self, span: OcrSpan) -> QRectF:
        return QRectF(
            span.left * self.width() / self._image.width(),
            span.top * self.height() / self._image.height(),
            max(1.0, (span.right - span.left) * self.width() / self._image.width()),
            max(1.0, (span.bottom - span.top) * self.height() / self._image.height()),
        )

    def _ocr_selected_range(self) -> tuple[int, int] | None:
        if self._ocr_anchor is None or self._ocr_focus is None:
            return None
        return min(self._ocr_anchor, self._ocr_focus), max(
            self._ocr_anchor, self._ocr_focus
        )

    def _draw_ocr_layer(self, painter: QPainter) -> None:
        if self._ocr_loading:
            self._draw_hud(painter, "正在识别文字…")
            return
        if self._ocr_outcome is None:
            return
        selected = self._ocr_selected_range()
        for index, span in enumerate(self._ocr_outcome.spans):
            rect = self._ocr_span_rect(span)
            if selected and selected[0] <= index <= selected[1]:
                painter.fillRect(rect.adjusted(-1, -1, 1, 1), QColor(22, 119, 255, 105))
            elif index == self._ocr_hover:
                painter.fillRect(rect.adjusted(-1, -1, 1, 1), QColor(88, 166, 255, 42))

    def _ocr_index_at(self, point: QPointF) -> int | None:
        if self._ocr_outcome is None:
            return None
        nearest: tuple[float, int] | None = None
        for index, span in enumerate(self._ocr_outcome.spans):
            rect = self._ocr_span_rect(span)
            if rect.adjusted(-2, -2, 2, 2).contains(point):
                return index
            if rect.top() - 5 <= point.y() <= rect.bottom() + 5:
                distance = abs(rect.center().x() - point.x())
                if nearest is None or distance < nearest[0]:
                    nearest = distance, index
        return nearest[1] if nearest else None

    def _ocr_text_for_range(self, start: int, end: int) -> str:
        if self._ocr_outcome is None:
            return ""
        parts: list[str] = []
        previous_line: int | None = None
        for span in self._ocr_outcome.spans[start : end + 1]:
            if previous_line is not None and span.line_index != previous_line:
                parts.append("\n")
            parts.append(span.text)
            previous_line = span.line_index
        return "".join(parts).strip()

    def _ocr_word_range(self, index: int) -> tuple[int, int]:
        if self._ocr_outcome is None:
            return index, index
        spans = self._ocr_outcome.spans
        target = spans[index]
        is_word = lambda value: bool(  # noqa: E731
            value
            and value.isascii()
            and (value.isalnum() or value in "_-'")
        )
        if not is_word(target.text):
            return index, index
        start = end = index
        while (
            start > 0
            and spans[start - 1].line_index == target.line_index
            and is_word(spans[start - 1].text)
        ):
            start -= 1
        while (
            end + 1 < len(spans)
            and spans[end + 1].line_index == target.line_index
            and is_word(spans[end + 1].text)
        ):
            end += 1
        return start, end

    def _copy_ocr_selection(self) -> None:
        selected = self._ocr_selected_range()
        if selected is None:
            return
        text = self._ocr_text_for_range(*selected)
        if text:
            QGuiApplication.clipboard().setText(text)
            self._show_hud(f"已复制 {len(text)} 个字符")

    def request_ocr(self) -> None:
        if self._ocr_loading or self._ocr_outcome is not None:
            return
        self._ocr_loading = True
        self.setCursor(Qt.CursorShape.WaitCursor)
        # 等待引擎时贴图只是固定参考,把鼠标交还给下方窗口。结果回来前
        # 用户可以继续聊天、浏览或操作任何其他程序。
        self._set_ocr_input_passthrough(True)
        self.ocr_requested.emit(self._image)
        self.update()

    def set_ocr_result(self, outcome: OcrOutcome) -> None:
        if not self._ocr_loading:
            return
        self._ocr_loading = False
        self._set_ocr_input_passthrough(False)
        if not outcome.text or not outcome.spans:
            self._show_hud("未识别到可选择的文字")
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        self._ocr_outcome = outcome
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.update()

    def set_ocr_error(self, message: str) -> None:
        if not self._ocr_loading:
            return
        self._ocr_loading = False
        self._set_ocr_input_passthrough(False)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._show_hud(message or "识别失败")

    def _exit_ocr_mode(self) -> None:
        self._ocr_loading = False
        self._ocr_outcome = None
        self._ocr_anchor = None
        self._ocr_focus = None
        self._ocr_hover = None
        self._ocr_dragging = False
        self._set_ocr_input_passthrough(self._click_through)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()

    def _set_ocr_input_passthrough(self, enabled: bool) -> None:
        current = bool(
            self.windowFlags() & Qt.WindowType.WindowTransparentForInput
        )
        if current == enabled:
            return
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        # setWindowFlag 会临时隐藏置顶窗口;show() 恢复画面但不抢焦点。
        self.show()

    def _draw_hud(self, painter: QPainter, text: str) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 20
        height = metrics.height() + 10
        rect = QRectF(
            (self.width() - width) / 2,
            max(4.0, (self.height() - height) / 2),
            width,
            height,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 23, 28, 205))
        painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(QColor("white"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _snapped_position(self, pos: QPoint) -> QPoint:
        screen = QGuiApplication.screenAt(pos + QPoint(self.width() // 2, 0))
        if screen is None:
            screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return pos
        area: QRect = screen.availableGeometry()
        x, y = pos.x(), pos.y()
        if abs(x - area.left()) <= SNAP_DISTANCE:
            x = area.left()
        elif abs(x + self.width() - area.right() - 1) <= SNAP_DISTANCE:
            x = area.right() - self.width() + 1
        if abs(y - area.top()) <= SNAP_DISTANCE:
            y = area.top()
        elif abs(y + self.height() - area.bottom() - 1) <= SNAP_DISTANCE:
            y = area.bottom() - self.height() + 1
        return QPoint(x, y)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._ocr_loading:
                event.accept()
                return
            if self._ocr_outcome is not None:
                index = self._ocr_index_at(event.position())
                self._ocr_anchor = index
                self._ocr_focus = index
                self._ocr_dragging = index is not None
                self.update()
                event.accept()
                return
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                # 不立即启动拖出:等移动超过系统拖拽阈值再说,
                # 否则 Ctrl+单击/Ctrl+双击都会误触发并落临时文件。
                self._ctrl_drag_origin = event.position().toPoint()
                event.accept()
                return
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._ocr_loading:
            return
        if self._ocr_outcome is not None:
            index = self._ocr_index_at(event.position())
            if self._ocr_dragging and index is not None:
                self._ocr_focus = index
            else:
                self._ocr_hover = index
            self.update()
            return
        if self._ctrl_drag_origin is not None and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            moved = (
                event.position().toPoint() - self._ctrl_drag_origin
            ).manhattanLength()
            if moved >= QApplication.startDragDistance():
                self._ctrl_drag_origin = None
                self._start_file_drag()
            event.accept()
            return
        if self._drag_offset is not None and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            target = event.globalPosition().toPoint() - self._drag_offset
            self.move(self._snapped_position(target))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._ocr_outcome is not None:
                if self._ocr_dragging:
                    index = self._ocr_index_at(event.position())
                    if index is not None:
                        self._ocr_focus = index
                self._ocr_dragging = False
                self.update()
                event.accept()
                return
            self._ctrl_drag_origin = None
            self._drag_offset = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._ocr_outcome is not None:
                index = self._ocr_index_at(event.position())
                if index is not None:
                    self._ocr_anchor, self._ocr_focus = self._ocr_word_range(index)
                    self.update()
                event.accept()
                return
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        steps = event.angleDelta().y() / 120.0
        if steps == 0:
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            opacity = self.windowOpacity() + 0.1 * steps
            opacity = min(1.0, max(MIN_OPACITY, opacity))
            self.setWindowOpacity(opacity)
            self._show_hud(f"不透明度 {round(opacity * 100)}%")
        else:
            self.set_zoom(self._zoom * (ZOOM_STEP**steps), event.position())
            self._show_hud(f"{round(self._zoom * 100)}%")
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if self._ocr_loading:
            if key == Qt.Key.Key_Escape:
                self._exit_ocr_mode()
            return
        if self._ocr_outcome is not None:
            if key == Qt.Key.Key_Escape:
                self._exit_ocr_mode()
            elif event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if key == Qt.Key.Key_A and self._ocr_outcome.spans:
                    self._ocr_anchor = 0
                    self._ocr_focus = len(self._ocr_outcome.spans) - 1
                    self.update()
                elif key == Qt.Key.Key_C:
                    self._copy_ocr_selection()
            elif key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                self._copy_ocr_selection()
            return
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_C:
                self.copy_to_clipboard()
                return
            if key == Qt.Key.Key_S:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.save_as_requested.emit(self._image)
                else:
                    self.save_requested.emit(self._image)
                return
            if key == Qt.Key.Key_0:
                self.reset_view()
                return
        if key in {Qt.Key.Key_Plus, Qt.Key.Key_Equal}:
            self.set_zoom(self._zoom * ZOOM_STEP)
            self._show_hud(f"{round(self._zoom * 100)}%")
            return
        if key in {Qt.Key.Key_Minus, Qt.Key.Key_Underscore}:
            self.set_zoom(self._zoom / ZOOM_STEP)
            self._show_hud(f"{round(self._zoom * 100)}%")
            return
        if key == Qt.Key.Key_W and not event.modifiers():
            self.request_ocr()
            return
        offset_by_key = {
            Qt.Key.Key_Left: QPoint(-1, 0),
            Qt.Key.Key_Right: QPoint(1, 0),
            Qt.Key.Key_Up: QPoint(0, -1),
            Qt.Key.Key_Down: QPoint(0, 1),
        }
        offset = offset_by_key.get(key)
        if offset is not None:
            factor = (
                10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            )
            self.move(self.pos() + offset * factor)
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if self._ocr_loading or self._ocr_outcome is not None:
            self._exit_ocr_mode()
            event.accept()
            return
        menu = QMenu(self)
        status = menu.addAction(
            f"缩放 {round(self._zoom * 100)}% · "
            f"不透明度 {round(self.windowOpacity() * 100)}%"
        )
        status.setEnabled(False)
        menu.addSeparator()
        copy_action = menu.addAction("复制图片\tCtrl+C")
        save_action = menu.addAction("保存图片\tCtrl+S")
        save_as_action = menu.addAction("另存为…\tCtrl+Shift+S")
        ocr_action = menu.addAction("识别文字")
        from .ocr import is_available as ocr_available

        if not ocr_available():
            ocr_action.setEnabled(False)
            ocr_action.setText("识别文字（缺少系统 OCR 语言）")
        drag_hint = menu.addAction("拖出文件：Ctrl+按住拖动")
        drag_hint.setEnabled(False)
        reset_action = menu.addAction("恢复原始大小\t双击 / Ctrl+0")
        through_action = menu.addAction("鼠标穿透（托盘菜单可恢复）")
        menu.addSeparator()
        close_action = menu.addAction("关闭贴图\tEsc")
        close_all_action = menu.addAction("关闭所有贴图")
        chosen = menu.exec(event.globalPos())
        if chosen == copy_action:
            self.copy_to_clipboard()
        elif chosen == save_action:
            self.save_requested.emit(self._image)
        elif chosen == save_as_action:
            self.save_as_requested.emit(self._image)
        elif chosen == ocr_action:
            self.request_ocr()
        elif chosen == reset_action:
            self.reset_view()
        elif chosen == through_action:
            self.set_click_through(True)
        elif chosen == close_action:
            self.close()
        elif chosen == close_all_action:
            self.close_all_requested.emit()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closed.emit(self)
        event.accept()
